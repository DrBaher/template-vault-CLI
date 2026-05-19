#!/usr/bin/env python3
"""template-vault-cli — Git-backed, clause-aware legal-document template manager.

Single-file Python CLI. Stdlib-only. MIT licensed.

Storage model: a Git repository whose top-level directories are categories
(nda, employment, licensing, investment, msa, dpa, ...). Each template is a
directory containing one or more versioned files plus exactly one meta.json.

Design ethos (shared with the rest of the suite):
  - Local-first by default; any network call is opt-in and disclosed.
  - Deterministic where possible; same input + config = same output.
  - Audit-friendly: provenance recorded in meta.json, not inferred.
  - Composable: standard files in, standard files out.
  - The CLI structures existing templates; it does NOT generate clause text.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

__version__ = "0.4.2"

VAULT_CONFIG_FILENAME = ".vault.json"
META_FILENAME = "meta.json"
SCHEMA_VERSION = 1

KNOWN_CATEGORIES = {
    "nda",
    "employment",
    "licensing",
    "investment",
    "msa",
    "dpa",
    "ip-assignment",
    "term-sheet",
    "consulting",
    "saas",
    "service",
    "other",
}

NO_CONFIRM_ENV = "NDA_VAULT_NO_CONFIRM"
LLM_ENV_PREFIX = "NDA_VAULT_LLM_"

REQUIRED_META_FIELDS = ("name", "category", "latest_version", "versions")
META_DEFAULTS = {
    "jurisdiction": [],
    "party_type": [],
    "deal_type": [],
    "tags": [],
    "owner": None,
    "license": "private",
    "source": None,
    "uploaded_by": None,
    "use_count": 0,
    "last_used": None,
    "summary": "",
    "derived_from": None,
    "forked_at_parent_version": None,
    "clauses": None,
    "clause_overrides": [],
    "clause_aliases": {},
}

# Auto-detect clause headers by H2 only (not H3+). Anchored at line start.
H2_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)

# Fallback heading patterns for non-Markdown-conformant templates (typically
# DOCX → text conversions). These ONLY run when H2 detection returns empty,
# so they can't shadow real H2 sections. Each pattern captures the title.
#
# - Bold-numbered:  **1. Purpose**  /  **Section 4. Term**
# - ALL-CAPS line:  CONFIDENTIALITY OBLIGATIONS  (≥4 chars, ≥2 letters,
#   surrounded by blank lines so we don't snag inline shouts)
_BOLD_HEADING_RE = re.compile(
    r"^\*\*\s*"
    r"(?:"
    r"(?:Article|Section|Sec\.?|Art\.?|Clause|Part|§)\s+\S+\.?"  # word-prefixed
    r"|"
    r"\(\d+\)"                                                    # (1)
    r"|"
    r"\d+(?:\.\d+)*"                                              # 1 / 1.2.3
    r")"
    r"[\.\):\s]+"
    r"([^\*\n]+?)"
    r"\s*\*\*\s*$",
    re.MULTILINE,
)
# ALL-CAPS heading detection. Required: blank-line frame on both sides (so
# inline shouts in prose don't qualify); ≥ 3 characters total; at least one
# ASCII letter; doesn't start with `[` (so `[BRACKETED]` placeholders never
# match). Single-token ALL-CAPS additionally requires ≥ 4 ASCII letters
# (handled in _matches_to_clauses) — multi-token allows shorter individual
# words. Tracks compare-cli's clause-detection.md spec, modulo the
# blank-line frame which is intentionally stricter here. See
# docs/clause-detection-divergence.md.
_ALL_CAPS_HEADING_RE = re.compile(
    r"(?:^|\n)\n([A-Z][A-Z0-9 \-/&,]{1,}[A-Z0-9])\s*\n\n",
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class VaultError(Exception):
    """User-actionable error. Caller prints message and exits non-zero."""


class NotFoundError(VaultError):
    pass


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _color_enabled(stream: Any = None) -> bool:
    """Auto-detect color support: opt out via NO_COLOR
    (https://no-color.org/), and never emit codes when stdout isn't a tty."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    s = stream if stream is not None else sys.stdout
    try:
        return bool(s.isatty())
    except Exception:
        return False


def _c(text: str, code: str) -> str:
    if not _color_enabled():
        return text
    return f"\033[{code}m{text}\033[0m"


def _green(s: str) -> str: return _c(s, "32")
def _yellow(s: str) -> str: return _c(s, "33")
def _red(s: str) -> str: return _c(s, "31")
def _dim(s: str) -> str: return _c(s, "2")


def _eprint(*args: Any, **kwargs: Any) -> None:
    print(*args, file=sys.stderr, **kwargs)


def _why_print(args_ns: argparse.Namespace, header: str, *lines: str) -> None:
    """Emit a `--why` block explaining what the command actually did.
    No-op unless `--why` was passed. Block goes to stdout so it's
    pipe-able with the command's primary output."""
    if not getattr(args_ns, "why", False):
        return
    print(f"\n[why] {header}")
    for line in lines:
        print(f"  {line}")


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_iso() -> str:
    return _dt.date.today().isoformat()


# ---------------------------------------------------------------------------
# Vault discovery + config
# ---------------------------------------------------------------------------


def find_vault_root(start: Optional[Path] = None) -> Path:
    """Walk upward from `start` (cwd by default) looking for .vault.json."""
    p = (start or Path.cwd()).resolve()
    for parent in [p] + list(p.parents):
        if (parent / VAULT_CONFIG_FILENAME).exists():
            return parent
    raise NotFoundError(
        f"No vault found. Run `template-vault init` in the directory you want "
        f"to use as the vault root, or `cd` into an existing vault."
    )


def read_vault_config(root: Path) -> Dict[str, Any]:
    cfg_path = root / VAULT_CONFIG_FILENAME
    try:
        return json.loads(cfg_path.read_text())
    except FileNotFoundError as e:
        raise NotFoundError(f"Vault config missing: {cfg_path}") from e
    except json.JSONDecodeError as e:
        raise VaultError(f"Malformed {VAULT_CONFIG_FILENAME}: {e.msg} (line {e.lineno})") from e


def write_vault_config(root: Path, cfg: Dict[str, Any]) -> None:
    (root / VAULT_CONFIG_FILENAME).write_text(_dump_json(cfg), encoding="utf-8")


def validate_vault_config(cfg: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not isinstance(cfg, dict):
        return ["vault config must be a JSON object"]
    if cfg.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"vault schema_version is {cfg.get('schema_version')!r}, expected {SCHEMA_VERSION}"
        )
    sources = cfg.get("sources")
    if sources is not None and not isinstance(sources, list):
        errors.append("'sources' must be a list when present")
    td = cfg.get("template_defaults")
    if td is not None and not isinstance(td, dict):
        errors.append("'template_defaults' must be a JSON object when present")
    ca = cfg.get("clause_aliases")
    if ca is not None and not isinstance(ca, dict):
        errors.append("'clause_aliases' must be a JSON object when present")
    return errors


# ---------------------------------------------------------------------------
# meta.json operations
# ---------------------------------------------------------------------------


def _dump_json(obj: Any) -> str:
    """Stable JSON dump with trailing newline for clean diffs."""
    return json.dumps(obj, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def template_dir(root: Path, category: str, name: str) -> Path:
    return root / category / name


def load_meta(t_dir: Path) -> Dict[str, Any]:
    """Read the raw per-template meta.json. Mutating callers use this and
    round-trip through `save_meta` without leaking vault-level defaults into
    the file. For read-mostly use that wants vault defaults overlaid, call
    `load_meta_resolved` instead.
    """
    mp = t_dir / META_FILENAME
    if not mp.exists():
        raise NotFoundError(f"Missing {META_FILENAME} in {t_dir}")
    try:
        meta = json.loads(mp.read_text())
    except json.JSONDecodeError as e:
        raise VaultError(f"Malformed {mp}: {e.msg}") from e
    return meta


def effective_clause_aliases(t_dir: Path,
                             raw_meta: Optional[Dict[str, Any]] = None
                             ) -> Optional[Dict[str, List[str]]]:
    """Return the alias map a mutating command should USE (per-template
    unioned with vault-level) without forcing the caller to round-trip the
    overlay back through `save_meta`."""
    meta = raw_meta if raw_meta is not None else load_meta(t_dir)
    try:
        cfg = read_vault_config(find_vault_root(t_dir))
    except (NotFoundError, VaultError):
        per = meta.get("clause_aliases")
        return per if isinstance(per, dict) and per else None
    overlaid = _overlay_vault_defaults(meta, cfg)
    out = overlaid.get("clause_aliases")
    return out if isinstance(out, dict) and out else None


def load_meta_resolved(t_dir: Path) -> Dict[str, Any]:
    """Like `load_meta`, but overlays vault-level `template_defaults` and
    `clause_aliases` from .vault.json. Per-template values always win on
    scalar/list keys; for `clause_aliases` (a dict) per-template aliases are
    unioned with vault-level aliases for the same canonical title."""
    meta = load_meta(t_dir)
    try:
        vault_root = find_vault_root(t_dir)
        cfg = read_vault_config(vault_root)
    except (NotFoundError, VaultError):
        return meta
    return _overlay_vault_defaults(meta, cfg)


def _overlay_vault_defaults(meta: Dict[str, Any], cfg: Dict[str, Any]
                            ) -> Dict[str, Any]:
    """Merge .vault.json's `template_defaults` (a partial meta.json) and
    `clause_aliases` (a vault-wide alias map) underneath the per-template
    meta. Per-template values always win on key collision; for
    `clause_aliases` (a dict) the per-template entries override matching
    keys in the vault-level dict, and aliases for a given canonical title
    are unioned across both layers.
    """
    out = dict(meta)
    defaults = cfg.get("template_defaults") if isinstance(cfg.get("template_defaults"), dict) else None
    if defaults:
        for k, v in defaults.items():
            if k not in out or out[k] in (None, "", [], {}):
                # Deep-ish copy so callers can't mutate the cfg by accident.
                out[k] = type(v)(v) if isinstance(v, (list, dict)) else v
    vault_aliases = cfg.get("clause_aliases") if isinstance(cfg.get("clause_aliases"), dict) else None
    if vault_aliases:
        merged: Dict[str, List[str]] = {}
        for k, v in vault_aliases.items():
            if isinstance(v, list):
                merged[k] = list(v)
        per = out.get("clause_aliases") or {}
        if isinstance(per, dict):
            for k, v in per.items():
                if not isinstance(v, list):
                    continue
                # Union with vault-level aliases for the same canonical key.
                existing = merged.get(k, [])
                merged[k] = list(dict.fromkeys(existing + list(v)))
        out["clause_aliases"] = merged
    return out


def save_meta(t_dir: Path, meta: Dict[str, Any]) -> None:
    (t_dir / META_FILENAME).write_text(_dump_json(meta), encoding="utf-8")


def validate_meta(meta: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable error strings; empty list if valid."""
    errors: List[str] = []
    if not isinstance(meta, dict):
        return ["meta.json must be a JSON object"]
    for f in REQUIRED_META_FIELDS:
        if f not in meta:
            errors.append(f"missing required field: {f}")
    versions = meta.get("versions")
    if isinstance(versions, list):
        seen = set()
        for v in versions:
            if not isinstance(v, dict) or "id" not in v:
                errors.append("each version must be an object with an 'id'")
                continue
            vid = v["id"]
            if vid in seen:
                errors.append(f"duplicate version id: {vid}")
            seen.add(vid)
            sup = v.get("supersedes")
            if sup is not None and sup not in seen and sup != v.get("id"):
                # supersedes can point to a not-yet-listed prior; relax:
                pass
        latest = meta.get("latest_version")
        if latest and latest not in {v.get("id") for v in versions if isinstance(v, dict)}:
            errors.append(f"latest_version {latest!r} is not present in versions[]")
    elif "versions" in meta:
        errors.append("'versions' must be a list")
    cat = meta.get("category")
    if cat is not None and cat not in KNOWN_CATEGORIES:
        # warning, not blocking — vault can use ad-hoc categories
        pass
    return errors


def fill_meta_defaults(meta: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(meta)
    for k, v in META_DEFAULTS.items():
        out.setdefault(k, v if not isinstance(v, (list, dict)) else type(v)(v))
    return out


# ---------------------------------------------------------------------------
# Vault enumeration
# ---------------------------------------------------------------------------


def iter_templates(root: Path) -> Iterable[Tuple[str, str, Path, Dict[str, Any]]]:
    """Yield (category, name, path, meta) for every template in the vault.

    Meta is `load_meta_resolved`: vault-level defaults from `.vault.json` are
    overlaid. All callers of `iter_templates` are read-only paths (list, find,
    clause-library, ask listing builder), so it's safe to surface the merged
    view here. Mutating commands load per-template meta directly.
    """
    for cat_dir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if cat_dir.name in {"config", "tests", ".git", ".github", "clauses"}:
            continue
        for t_dir in sorted(p for p in cat_dir.iterdir() if p.is_dir()):
            if (t_dir / META_FILENAME).exists():
                try:
                    meta = load_meta_resolved(t_dir)
                except VaultError:
                    continue
                yield cat_dir.name, t_dir.name, t_dir, meta


def parse_ref(ref: str) -> Tuple[str, str, Optional[str]]:
    """Parse 'category/name[@version]' into a 3-tuple."""
    version = None
    body = ref
    if "@" in ref:
        body, version = ref.rsplit("@", 1)
        if not version:
            raise VaultError(f"Invalid reference {ref!r}: empty version after '@'")
    if "/" not in body:
        raise VaultError(
            f"Invalid template reference {ref!r}: expected 'category/name[@version]'"
        )
    cat, name = body.split("/", 1)
    if not cat or not name:
        raise VaultError(f"Invalid reference {ref!r}: empty category or name")
    return cat, name, version


def resolve_version_file(t_dir: Path, meta: Dict[str, Any], version: Optional[str]) -> Path:
    """Find the file on disk for a given version (or @latest)."""
    versions = meta.get("versions") or []
    vid = version or meta.get("latest_version")
    if not vid or vid == "latest":
        vid = meta.get("latest_version")
    if not vid:
        raise NotFoundError(f"Template {t_dir} has no versions recorded")
    if vid not in {v.get("id") for v in versions}:
        raise NotFoundError(
            f"Version {vid!r} not found. Available: "
            + ", ".join(v.get("id", "?") for v in versions)
        )
    candidates = sorted(t_dir.glob(f"{vid}.*"))
    candidates = [c for c in candidates if c.name != META_FILENAME]
    if not candidates:
        raise NotFoundError(f"No file on disk for version {vid!r} in {t_dir}")
    if len(candidates) > 1:
        # Prefer markdown if multiple extensions
        md = [c for c in candidates if c.suffix.lower() == ".md"]
        if md:
            return md[0]
    return candidates[0]


def auto_increment_version(meta: Dict[str, Any]) -> str:
    """Pick next version id (v1, v2, ...) based on existing list."""
    existing = {v.get("id", "") for v in meta.get("versions") or []}
    n = 1
    while f"v{n}" in existing:
        n += 1
    return f"v{n}"


# ---------------------------------------------------------------------------
# Clause detection + manipulation
# ---------------------------------------------------------------------------


def detect_clauses(text: str,
                   explicit_map: Optional[List[Dict[str, str]]] = None,
                   aliases_map: Optional[Dict[str, List[str]]] = None,
                   ) -> List[Dict[str, Any]]:
    """Return [{title, anchor, start, end, aliases}, ...] for each clause.

    H2 (`## ...`) only — H3+ subsections stay inside the parent clause body.

    If `explicit_map` is given, use those anchors instead. Anchors must be the
    full header line as it appears in the file ("## 1. Purpose"); we locate
    each one by string match. Body extends from the matched line to the next
    matched anchor (or EOF).

    `aliases_map` is `{canonical_title: [alias, ...]}` from meta.json's
    `clause_aliases`. Each detected clause gets an `aliases` list of normalized
    alternate names that `find_clause_by_title` will accept.
    """
    if explicit_map:
        clauses = _detect_from_explicit(text, explicit_map)
    else:
        matches = list(H2_RE.finditer(text))
        clauses = []
        for i, m in enumerate(matches):
            title = _strip_clause_number(m.group(1).strip())
            anchor = m.group(0)
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            clauses.append({"title": title, "anchor": anchor,
                            "start": start, "end": end})
        # Fallback only — never shadows real H2 sections.
        if not clauses:
            clauses = _detect_fallback_headings(text)
    _attach_aliases(clauses, aliases_map)
    return clauses


def _detect_fallback_headings(text: str) -> List[Dict[str, Any]]:
    """Best-effort detection for non-H2 templates (typically DOCX-converted).

    Tries bold-numbered headings (`**1. Purpose**`) first, then ALL-CAPS
    standalone lines. Returns the first non-empty result. Conservative on
    purpose — false negatives (zero clauses) are better than false positives
    (a clause inside a clause body); the user can always fall back to the
    explicit `clauses` map in meta.json.
    """
    matches = list(_BOLD_HEADING_RE.finditer(text))
    if len(matches) >= 2:
        return _matches_to_clauses(text, matches, group=1)
    # ALL-CAPS pass: regex catches the structural shape; this post-filter
    # enforces the spec's single-token rule (single-token lines need >= 4
    # ASCII letters, so "TER" doesn't qualify but "TERM" does). Multi-token
    # lines have no per-token minimum.
    raw_matches = list(_ALL_CAPS_HEADING_RE.finditer(text))
    matches = [m for m in raw_matches if _qualifies_as_all_caps_heading(m.group(1))]
    if len(matches) >= 2:
        return _matches_to_clauses(text, matches, group=1)
    return []


def _qualifies_as_all_caps_heading(title: str) -> bool:
    """Apply the spec's single-token-min-4-letters rule on top of the
    regex's structural match. Multi-token lines pass through."""
    tokens = title.split()
    if len(tokens) >= 2:
        return True
    # Single-token: count ASCII letters; need >= 4.
    letters = sum(1 for ch in title if "A" <= ch <= "Z")
    return letters >= 4


def _matches_to_clauses(text: str, matches: List["re.Match[str]"],
                        group: int) -> List[Dict[str, Any]]:
    """Build clause dicts from a list of regex matches whose `group` is the
    title and whose match span includes the heading line itself."""
    out: List[Dict[str, Any]] = []
    for i, m in enumerate(matches):
        title = _strip_clause_number(m.group(group).strip())
        # Anchor is the matched heading text exactly as it appears.
        # For ALL_CAPS we step past the leading newline gap captured by the regex.
        anchor_start = text.rfind(m.group(group), m.start(), m.end())
        anchor_line_start = text.rfind("\n", 0, anchor_start) + 1
        anchor_line_end = text.find("\n", anchor_line_start)
        if anchor_line_end == -1:
            anchor_line_end = len(text)
        anchor = text[anchor_line_start:anchor_line_end]
        start = anchor_line_start
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append({"title": title, "anchor": anchor,
                    "start": start, "end": end})
    return out


def _norm_clause_key(s: str) -> str:
    """Normalize a clause title or alias for matching."""
    return _strip_clause_number(s).strip().lower()


def _attach_aliases(clauses: List[Dict[str, Any]],
                    aliases_map: Optional[Dict[str, List[str]]]) -> None:
    """Mutates each clause dict to include an `aliases` list (lowercased,
    number-stripped). Aliases whose key doesn't match a real clause are
    silently ignored here (`doctor` surfaces them)."""
    if not aliases_map:
        for c in clauses:
            c["aliases"] = []
        return
    norm_to_aliases: Dict[str, List[str]] = {}
    for canonical, aliases in aliases_map.items():
        if not isinstance(aliases, list):
            continue
        key = _norm_clause_key(canonical)
        norm_to_aliases.setdefault(key, []).extend(
            _norm_clause_key(a) for a in aliases if isinstance(a, str) and a.strip()
        )
    for c in clauses:
        c["aliases"] = list(dict.fromkeys(norm_to_aliases.get(c["title"].lower(), [])))


def _detect_from_explicit(text: str, explicit_map: List[Dict[str, str]]
                          ) -> List[Dict[str, Any]]:
    located: List[Tuple[int, str, str]] = []
    for entry in explicit_map:
        anchor = entry.get("anchor", "")
        title = entry.get("title", "").strip()
        if not anchor or not title:
            continue
        idx = text.find(anchor)
        if idx == -1:
            # Skip silently; doctor surfaces these.
            continue
        located.append((idx, title, anchor))
    located.sort()
    out: List[Dict[str, Any]] = []
    for i, (start, title, anchor) in enumerate(located):
        end = located[i + 1][0] if i + 1 < len(located) else len(text)
        out.append({"title": title, "anchor": anchor, "start": start, "end": end})
    return out


_ROMAN_RE = r"(?:M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{1,3})|I{1,3})"

# Match leading numbering tokens we want to strip. Order matters: longer
# Article/Section forms come before bare numbers so they're consumed first.
_NUMBER_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"(?:Article|Section|Sec\.?|Art\.?|Clause|Part)\s+"  # word prefix …
    r"(?:" + _ROMAN_RE + r"|\d+(?:\.\d+)*)"              # … followed by I/IV or 1.2.3
    r"|"
    r"§\s*\d+(?:\.\d+)*"                                  # § 4 / § 4.2.1
    r"|"
    r"\(\d+\)"                                            # (1) / (12)
    r"|"
    r"\[\d+\]"                                            # [1]
    r"|"
    r"\d+(?:\.\d+)+"                                      # 1.2 / 1.2.3
    r"|"
    r"\d+"                                                # bare 1 / 42
    r")"
    r"[\.\)\]:\s]*",                                      # trailing punctuation
    re.IGNORECASE,
)


def _strip_clause_number(s: str) -> str:
    """Normalize clause-title numbering for matching.

    Handles a wider set of numbering styles than just `1.` / `1)`:
      - 1.   1)   (1)   [1]
      - 1.1  1.2.3
      - Article I.   Article 1.   Section 4.   § 4.   Sec 4.
    Returns the title with the numbering token removed and surrounding
    whitespace cleaned up. Idempotent.
    """
    out = _NUMBER_PREFIX_RE.sub("", s, count=1)
    return out.strip()


def find_clause_by_title(clauses: List[Dict[str, Any]], title: str
                         ) -> Optional[Dict[str, Any]]:
    """Resolve a user-supplied clause name to a clause.

    Match order, on a normalized (lowercased, number-stripped) needle:
      1. Exact match against any clause's title or its `aliases`.
      2. Substring match against any clause's title or its `aliases`.

    If step 2 matches more than one distinct clause, raises `VaultError`
    listing the candidates so the caller can disambiguate. Returns `None`
    only when there's no match at all (preserves existing API).
    """
    needle = _norm_clause_key(title)
    if not needle:
        return None
    # Exact match: title first, then aliases.
    for c in clauses:
        if c["title"].lower() == needle:
            return c
    for c in clauses:
        if needle in (c.get("aliases") or []):
            return c
    # Substring: collect distinct candidate clauses.
    matches: List[Dict[str, Any]] = []
    seen_starts: set = set()
    for c in clauses:
        candidates = [c["title"].lower()] + list(c.get("aliases") or [])
        if any(needle in cand for cand in candidates):
            if c["start"] not in seen_starts:
                matches.append(c)
                seen_starts.add(c["start"])
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(repr(c["title"]) for c in matches)
        raise VaultError(
            f"Clause name {title!r} is ambiguous; matches {len(matches)} clauses: "
            f"{names}. Pass the full clause title to disambiguate."
        )
    return None


def slice_clause_text(text: str, clause: Dict[str, Any]) -> str:
    """Extract clause body including its header line."""
    return text[clause["start"]:clause["end"]]


def replace_clause(text: str, target: Dict[str, Any], replacement_body: str) -> str:
    """Replace a clause's region in `text` with `replacement_body`.

    `replacement_body` should already include its own H2 header line. We DO NOT
    rewrite the header to match the target — the caller is responsible. By
    default the swap command preserves the *target's* header so numbering stays
    consistent (see cmd_swap).
    """
    if not replacement_body.endswith("\n"):
        replacement_body += "\n"
    # Ensure the prior segment ends with a single trailing newline before the
    # replacement, and the replacement is followed by a newline before the
    # next clause begins. This keeps round-trips clean.
    before = text[:target["start"]]
    after = text[target["end"]:]
    if before and not before.endswith("\n"):
        before += "\n"
    return before + replacement_body + after


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------


def _git(args: List[str], cwd: Path, check: bool = True,
         capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=check,
        capture_output=capture,
        text=True,
    )


def _git_init(root: Path, bare: bool = False) -> None:
    args = ["init"]
    if bare:
        args.append("--bare")
    _git(args, root, check=True)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------------------
# LLM config + adapters
# ---------------------------------------------------------------------------


def _load_llm_config(args_ns: argparse.Namespace) -> Dict[str, Any]:
    """Resolve LLM config from (in order): CLI flags > env > shared config files.

    Falls back silently to an empty dict; commands that need an API key surface
    a friendly error if they don't get one.
    """
    cfg: Dict[str, Any] = {}
    candidates = [
        Path.home() / ".config" / "nda-review-cli" / "llm.json",
        Path.home() / ".config" / "template-vault-cli" / "llm.json",
        Path.cwd() / "config" / "llm.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                data = json.loads(p.read_text())
                if isinstance(data, dict):
                    cfg.update({k: v for k, v in data.items() if not k.startswith("_")})
                    break
            except (json.JSONDecodeError, OSError):
                continue
    for env_key, cfg_key in (
        ("PROVIDER", "provider"),
        ("MODEL", "model"),
        ("API_KEY", "api_key"),
        ("BASE_URL", "base_url"),
    ):
        env_val = os.environ.get(LLM_ENV_PREFIX + env_key)
        if env_val:
            cfg[cfg_key] = env_val
    if getattr(args_ns, "llm", None):
        cfg["provider"] = args_ns.llm
    if getattr(args_ns, "llm_model", None):
        cfg["model"] = args_ns.llm_model
    if getattr(args_ns, "llm_base_url", None):
        cfg["base_url"] = args_ns.llm_base_url
    return cfg


def _llm_request(cfg: Dict[str, Any], system: str, user: str,
                 timeout: int = 60) -> str:
    """Send a chat-completion-style request and return the assistant text.

    Supports two providers:
      - 'anthropic' → POST https://api.anthropic.com/v1/messages
      - 'openai'    → POST {base_url or https://api.openai.com/v1}/chat/completions

    'openai' covers OpenAI, Ollama, OpenRouter, vLLM, LM Studio.
    """
    provider = (cfg.get("provider") or "anthropic").lower()
    api_key = cfg.get("api_key")
    model = cfg.get("model") or ("claude-sonnet-4-6" if provider == "anthropic" else "gpt-4o-mini")
    if not api_key:
        raise VaultError(
            "No LLM API key found. Set NDA_VAULT_LLM_API_KEY or write "
            "~/.config/template-vault-cli/llm.json (see config/llm.json.example)."
        )
    if provider == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = json.dumps({
            "model": model,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }).encode("utf-8")
    else:  # openai-compatible
        base = (cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        url = f"{base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": 1024,
        }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise VaultError(f"LLM HTTP {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise VaultError(f"LLM network error: {e.reason}") from e
    if provider == "anthropic":
        try:
            return "".join(p.get("text", "") for p in data["content"])
        except (KeyError, TypeError) as e:
            raise VaultError(f"Unexpected Anthropic response shape: {e}") from e
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise VaultError(f"Unexpected OpenAI-compatible response shape: {e}") from e


# ---------------------------------------------------------------------------
# Sources registry
# ---------------------------------------------------------------------------


SOURCES_ENV = "NDA_VAULT_SOURCES"


def _sources_path() -> Path:
    return Path(__file__).resolve().parent / "config" / "default-sources.json"


def _resolve_sources_path(args_ns: Optional[argparse.Namespace]) -> Optional[Path]:
    """Pick the sources registry path: CLI flag > env var > bundled (None)."""
    if args_ns is not None and getattr(args_ns, "sources", None):
        return Path(args_ns.sources)
    env = os.environ.get(SOURCES_ENV)
    if env:
        return Path(env)
    return None


def load_sources_registry(override_path: Optional[Path] = None) -> Dict[str, Any]:
    p = override_path if override_path is not None else _sources_path()
    if not p.exists():
        if override_path is not None:
            raise VaultError(f"Sources registry not found: {p}")
        return {"schema_version": SCHEMA_VERSION, "sources": []}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise VaultError(f"Malformed sources registry {p}: {e.msg}") from e


def _fetch_url(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": f"template-vault-cli/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# Command: init
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.path or ".").resolve()
    target.mkdir(parents=True, exist_ok=True)
    cfg_path = target / VAULT_CONFIG_FILENAME
    if cfg_path.exists():
        _eprint(f"Vault already initialized at {target}")
        return 0
    cfg = {
        "schema_version": SCHEMA_VERSION,
        "created": _today_iso(),
        "defaults": {"license": "private"},
        "sources": [],
    }
    write_vault_config(target, cfg)
    if not (target / ".git").exists() and not args.bare:
        try:
            _git_init(target, bare=False)
        except subprocess.CalledProcessError as e:
            _eprint(f"warning: git init failed: {e.stderr or e}")
    elif args.bare:
        try:
            _git_init(target, bare=True)
        except subprocess.CalledProcessError as e:
            _eprint(f"warning: git init --bare failed: {e.stderr or e}")
    print(f"Initialized vault at {target}")
    print("Next: `template-vault sources` to see available imports, or "
          "`template-vault upload <file> --category nda --name house-mutual`.")
    return 0


# ---------------------------------------------------------------------------
# Command: upload
# ---------------------------------------------------------------------------


def _prompt(label: str, default: Optional[str] = None,
            non_interactive: bool = False) -> str:
    if non_interactive:
        return default or ""
    prompt = f"{label}"
    if default:
        prompt += f" [{default}]"
    prompt += ": "
    try:
        ans = input(prompt).strip()
    except EOFError:
        ans = ""
    return ans or (default or "")


def _docx_to_markdown(src: Path) -> str:
    """Convert a .docx to a Markdown string. Headings → `#`/`##`/...; other
    paragraphs → prose lines. Lazily imports python-docx; raises VaultError
    with install instructions if the extra isn't installed."""
    try:
        import docx as _docx  # type: ignore[import-not-found]
    except ImportError as e:
        raise VaultError(
            "Uploading .docx requires the optional [docx] extra. "
            "Install with: pip install template-vault-cli[docx]"
        ) from e
    try:
        document = _docx.Document(str(src))
    except Exception as e:
        raise VaultError(f"Could not read {src.name} as a .docx: {e}") from e
    out: List[str] = []
    for para in document.paragraphs:
        style = (getattr(para.style, "name", "") or "").strip()
        text = (para.text or "").rstrip()
        if not text:
            out.append("")
            continue
        if style.lower().startswith("heading "):
            tail = style[len("Heading "):].strip()
            try:
                level = max(1, min(6, int(tail)))
            except ValueError:
                level = 2  # unknown heading style → treat as H2
            out.append(("#" * level) + " " + text)
        elif style.lower() in {"title"}:
            out.append("# " + text)
        else:
            out.append(text)
    md = "\n".join(out).strip() + "\n"
    return md


_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _markdown_to_docx(text: str, dest: Path) -> None:
    """Round-trip the .docx ingestion: convert a Markdown body back to .docx
    using `Heading 1`/`Heading 2`/... styles. Each line starting with `#` is
    a heading at the corresponding level. Blank lines preserved. All other
    lines become body paragraphs. Lazily imports python-docx."""
    try:
        import docx as _docx  # type: ignore[import-not-found]
    except ImportError as e:
        raise VaultError(
            "Exporting to .docx requires the optional [docx] extra. "
            "Install with: pip install template-vault-cli[docx]"
        ) from e
    document = _docx.Document()
    for line in text.splitlines():
        if not line.strip():
            document.add_paragraph("")
            continue
        m = _MARKDOWN_HEADING_RE.match(line)
        if m:
            level = min(6, len(m.group(1)))
            title = m.group(2)
            style = "Title" if level == 1 else f"Heading {level}"
            document.add_paragraph(title, style=style)
        else:
            document.add_paragraph(line)
    document.save(str(dest))


def cmd_export(args: argparse.Namespace) -> int:
    root = find_vault_root()
    cat, name, version = parse_ref(args.ref)
    t_dir = template_dir(root, cat, name)
    if not t_dir.exists():
        raise NotFoundError(
            f"No such template: {cat}/{name}. "
            f"Run `template-vault list` to see what's in the vault."
        )
    meta = load_meta_resolved(t_dir)
    f = resolve_version_file(t_dir, meta, version)
    text = f.read_text(encoding="utf-8")
    fmt = (args.as_ or "").lower()
    if fmt != "docx":
        raise VaultError(f"Unsupported export format: {args.as_!r}. Only 'docx' is supported.")
    dest = Path(args.output) if args.output else Path(f"{name}.docx")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _markdown_to_docx(text, dest)
    print(f"{_green('Exported')} {cat}/{name}@{meta.get('latest_version')} -> {dest}")
    _why_print(
        args,
        f"source: {f.relative_to(root)}",
        f"format: {fmt}",
        f"output: {dest}",
        f"headings: lines starting with '#' become Heading 1/2/3/... (H1 -> Title)",
    )
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    root = find_vault_root()
    src = Path(args.file).resolve()
    if not src.is_file():
        raise VaultError(f"Source file not found: {src}")
    category = args.category
    name = args.name
    if not category or not name:
        raise VaultError("--category and --name are required")
    t_dir = template_dir(root, category, name)
    new = not t_dir.exists()

    # If the input is .docx, convert to Markdown. The vault stores Markdown so
    # H2 clause detection works downstream. The original .docx is not kept.
    is_docx = src.suffix.lower() == ".docx"
    converted_text: Optional[str] = None
    if is_docx:
        converted_text = _docx_to_markdown(src)

    t_dir.mkdir(parents=True, exist_ok=True)

    # Load or initialize meta
    if (t_dir / META_FILENAME).exists():
        meta = load_meta(t_dir)
    else:
        meta = {
            "name": name,
            "category": category,
            "latest_version": None,
            "versions": [],
        }
    meta = fill_meta_defaults(meta)

    # --amend mode: overwrite an existing version in place rather than
    # appending a new one. Records the SHA-256 of the prior content in the
    # version's changelog so the change is auditable in git.
    if getattr(args, "amend", None):
        amend_vid = args.amend
        target = next((v for v in meta["versions"] if v.get("id") == amend_vid), None)
        if target is None:
            raise VaultError(
                f"--amend {amend_vid}: no such version in {category}/{name}. "
                f"Existing: {', '.join(v.get('id') for v in meta['versions']) or '(none)'}"
            )
        existing_files = sorted(p for p in t_dir.glob(f"{amend_vid}.*") if p.is_file())
        if not existing_files:
            raise VaultError(f"--amend: version {amend_vid} has no file on disk")
        if len(existing_files) > 1:
            raise VaultError(
                f"--amend: ambiguous file for {amend_vid}: {[p.name for p in existing_files]}"
            )
        old_path = existing_files[0]
        if not (args.yes_amend or args.non_interactive):
            try:
                ans = input(
                    f"Overwrite {old_path.relative_to(root)} in place? "
                    f"This is a destructive operation; the prior content's "
                    f"SHA-256 will be recorded in the version's changelog. [y/N] "
                ).strip().lower()
            except EOFError:
                ans = "n"
            if ans != "y":
                _eprint("aborted")
                return 1
        old_bytes = old_path.read_bytes()
        old_sha = sha256_bytes(old_bytes)
        new_bytes = converted_text.encode("utf-8") if converted_text is not None else src.read_bytes()
        old_path.write_bytes(new_bytes)
        amend_note = f"amended (prior sha256: {old_sha})"
        if args.changelog:
            amend_note = f"{args.changelog} — {amend_note}"
        target["changelog"] = amend_note
        target["amended"] = _today_iso()
        save_meta(t_dir, meta)
        print(f"Amended: {category}/{name}@{amend_vid}")
        print(f"  file: {old_path.relative_to(root)}  ({len(new_bytes)} bytes)")
        print(f"  prior sha256: {old_sha}")
        return 0

    # Determine version id
    vid = args.version or auto_increment_version(meta)
    if vid in {v.get("id") for v in meta["versions"]}:
        raise VaultError(f"Version {vid!r} already exists for {category}/{name}")

    # Copy file (or write converted Markdown for .docx).
    dest_suffix = ".md" if is_docx else (src.suffix.lower() or ".md")
    dest = t_dir / f"{vid}{dest_suffix}"
    if converted_text is not None:
        dest.write_text(converted_text)
    else:
        dest.write_bytes(src.read_bytes())

    # Append version entry
    base_changelog = args.changelog or (
        "initial" if not meta["versions"] else f"superseded {args.supersedes or ''}".strip()
    )
    if is_docx:
        base_changelog = (
            f"{base_changelog} — converted from {src.name}"
        )
    entry = {
        "id": vid,
        "added": _today_iso(),
        "supersedes": args.supersedes,
        "changelog": base_changelog,
    }
    meta["versions"].append(entry)
    meta["latest_version"] = vid

    # Update prior version's supersedes_by, if applicable
    if args.supersedes:
        for v in meta["versions"]:
            if v.get("id") == args.supersedes:
                v["supersedes_by"] = vid

    # Required-ish fields
    summary = args.summary
    if not summary and not args.non_interactive:
        summary = _prompt(
            "Summary (one or two sentences -- used for LLM recall)",
            default=meta.get("summary") or "",
        )
    if summary is not None:
        meta["summary"] = summary

    if args.tags:
        existing = set(meta.get("tags") or [])
        new_tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        meta["tags"] = sorted(existing.union(new_tags))
    if args.jurisdiction:
        existing = set(meta.get("jurisdiction") or [])
        new_j = [j.strip() for j in args.jurisdiction.split(",") if j.strip()]
        meta["jurisdiction"] = sorted(existing.union(new_j))
    if args.party_type:
        meta["party_type"] = sorted(set((meta.get("party_type") or []) + [args.party_type]))
    if args.deal_type:
        meta["deal_type"] = sorted(set((meta.get("deal_type") or []) + [args.deal_type]))
    if args.license:
        meta["license"] = args.license
    if args.owner:
        meta["owner"] = args.owner
    if args.uploaded_by:
        meta["uploaded_by"] = args.uploaded_by
    if args.source:
        meta["source"] = args.source

    # Optional LLM-generated summary (opt-in)
    if args.llm_summarize:
        try:
            content = src.read_text(errors="replace")[:8000]
        except OSError as e:
            raise VaultError(f"Could not read source for LLM summary: {e}") from e
        cfg = _load_llm_config(args)
        text = _llm_request(
            cfg,
            system=(
                "You write concise, factual one-paragraph summaries of legal "
                "templates for a librarian's index. Plain text. No marketing. "
                "Mention category, party-side, and any unusual provisions."
            ),
            user=f"Template: {category}/{name}\n\nFirst 8000 chars:\n\n{content}",
        )
        meta["summary"] = text.strip()

    # Validate before writing
    errors = validate_meta(meta)
    if errors:
        raise VaultError("meta.json invalid after upload:\n  - " + "\n  - ".join(errors))

    save_meta(t_dir, meta)

    print(f"{_green('Created:') if new else _green('Updated:')} {category}/{name}@{vid}")
    print(f"  file: {dest.relative_to(root)}")
    print(f"  meta: {(t_dir / META_FILENAME).relative_to(root)}")
    if not meta.get("summary"):
        _eprint(_yellow("note:") + " summary is empty -- `ask` recall will be weaker. "
                "Re-upload with --summary or edit meta.json.")
    return 0


# ---------------------------------------------------------------------------
# Command: list / find / get / info / diff
# ---------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    root = find_vault_root()
    rows: List[Dict[str, Any]] = []
    for cat, name, _path, meta in iter_templates(root):
        if args.category and cat != args.category:
            continue
        if args.tag and args.tag not in (meta.get("tags") or []):
            continue
        if args.jurisdiction and args.jurisdiction not in (meta.get("jurisdiction") or []):
            continue
        rows.append({
            "category": cat,
            "name": name,
            "ref": f"{cat}/{name}",
            "latest_version": meta.get("latest_version") or "?",
            "tags": list(meta.get("tags") or []),
            "jurisdiction": list(meta.get("jurisdiction") or []),
            "summary": meta.get("summary") or "",
        })
    if getattr(args, "json", False):
        json.dump({"results": rows}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    if not rows:
        print("(no templates match)")
        return 0
    width = max(len(r["ref"]) for r in rows)
    verbose = bool(getattr(args, "verbose", False))
    for r in rows:
        ref = r["ref"].ljust(width)
        if verbose:
            print(f"{ref}  {r['latest_version']}")
            if r["summary"]:
                # Truncate to ~80 chars to keep one summary line readable.
                s = r["summary"][:80] + ("..." if len(r["summary"]) > 80 else "")
                print(f"  {_dim(s)}")
            meta_bits = []
            if r["tags"]:
                meta_bits.append("tags=" + ",".join(r["tags"]))
            if r["jurisdiction"]:
                meta_bits.append("juris=" + ",".join(r["jurisdiction"]))
            if meta_bits:
                print(f"  {_dim('  '.join(meta_bits))}")
        else:
            extra = []
            if r["tags"]:
                extra.append("tags=" + ",".join(r["tags"]))
            if r["jurisdiction"]:
                extra.append("juris=" + ",".join(r["jurisdiction"]))
            print(f"{ref}  {r['latest_version']}  " + "  ".join(extra))
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    root = find_vault_root()
    q = args.query.lower()
    hits: List[Tuple[float, str, str, str, Dict[str, Any]]] = []
    for cat, name, _path, meta in iter_templates(root):
        haystack_parts = [
            cat, name,
            meta.get("summary") or "",
            " ".join(meta.get("tags") or []),
            " ".join(meta.get("jurisdiction") or []),
            " ".join(meta.get("deal_type") or []),
            " ".join(meta.get("party_type") or []),
        ]
        haystack = " ".join(haystack_parts).lower()
        if q in haystack:
            score = 2.0
        else:
            score = difflib.SequenceMatcher(None, q, haystack).ratio()
        if score >= 0.3:
            hits.append((score, cat, name, meta.get("latest_version") or "?", meta))
    hits.sort(reverse=True, key=lambda t: (t[0], t[1], t[2]))
    hits = hits[: args.top_k]
    if getattr(args, "json", False):
        payload = {
            "query": args.query,
            "results": [
                {
                    "ref": f"{cat}/{name}",
                    "latest_version": ver,
                    "score": round(score, 4),
                    "summary": meta.get("summary") or "",
                    "tags": list(meta.get("tags") or []),
                    "jurisdiction": list(meta.get("jurisdiction") or []),
                }
                for score, cat, name, ver, meta in hits
            ],
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    if not hits:
        print(f"(no matches for {args.query!r})")
        return 0
    for score, cat, name, ver, _meta in hits:
        print(f"{cat}/{name}@{ver}    score={score:.2f}")
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    root = find_vault_root()
    cat, name, version = parse_ref(args.ref)
    t_dir = template_dir(root, cat, name)
    if not t_dir.exists():
        raise NotFoundError(
            f"No such template: {cat}/{name}. "
            f"Run `template-vault list` to see what's in the vault."
        )
    meta = load_meta(t_dir)
    f = resolve_version_file(t_dir, meta, version)
    # Bump usage stats (best-effort; don't crash if read-only)
    try:
        meta["use_count"] = int(meta.get("use_count") or 0) + 1
        meta["last_used"] = _today_iso()
        save_meta(t_dir, meta)
    except OSError:
        pass
    if args.path_only:
        print(str(f))
        return 0
    sys.stdout.write(f.read_text())
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    root = find_vault_root()
    cat, name, _v = parse_ref(args.ref)
    t_dir = template_dir(root, cat, name)
    if not t_dir.exists():
        raise NotFoundError(
            f"No such template: {cat}/{name}. "
            f"Run `template-vault list` to see what's in the vault."
        )
    meta = load_meta_resolved(t_dir)
    if getattr(args, "json", False):
        # Structured payload for downstream tools (e.g. nda-review-cli).
        try:
            f = resolve_version_file(t_dir, meta, None)
            text = f.read_text()
            cs = detect_clauses(
                text,
                explicit_map=meta.get("clauses") if isinstance(meta.get("clauses"), list) else None,
                aliases_map=meta.get("clause_aliases") if isinstance(meta.get("clause_aliases"), dict) else None,
            )
            clause_summary = [
                {"title": c["title"], "anchor": c["anchor"], "aliases": c.get("aliases") or []}
                for c in cs
            ]
            latest_path = str(f)
        except (VaultError, OSError):
            clause_summary = []
            latest_path = None
        payload = {
            "ref": f"{cat}/{name}",
            "latest_version": meta.get("latest_version"),
            "latest_path": latest_path,
            "version_count": len(meta.get("versions") or []),
            "jurisdiction": list(meta.get("jurisdiction") or []),
            "party_type": list(meta.get("party_type") or []),
            "deal_type": list(meta.get("deal_type") or []),
            "tags": list(meta.get("tags") or []),
            "license": meta.get("license"),
            "source": meta.get("source"),
            "derived_from": meta.get("derived_from"),
            "forked_at_parent_version": meta.get("forked_at_parent_version"),
            "summary": meta.get("summary") or "",
            "use_count": meta.get("use_count") or 0,
            "last_used": meta.get("last_used"),
            "clauses": clause_summary,
            "clause_overrides": list(meta.get("clause_overrides") or []),
            "clause_aliases": dict(meta.get("clause_aliases") or {}),
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    print(f"{cat}/{name}")
    print(f"  latest:        {meta.get('latest_version')}")
    print(f"  versions:      {len(meta.get('versions') or [])}")
    print(f"  jurisdiction:  {', '.join(meta.get('jurisdiction') or []) or '-'}")
    print(f"  party_type:    {', '.join(meta.get('party_type') or []) or '-'}")
    print(f"  deal_type:     {', '.join(meta.get('deal_type') or []) or '-'}")
    print(f"  tags:          {', '.join(meta.get('tags') or []) or '-'}")
    print(f"  license:       {meta.get('license')}")
    print(f"  owner:         {meta.get('owner') or '-'}")
    print(f"  source:        {meta.get('source') or '-'}")
    print(f"  derived_from:  {meta.get('derived_from') or '-'}")
    print(f"  used:          {meta.get('use_count')} (last: {meta.get('last_used') or '-'})")
    print(f"  summary:       {meta.get('summary') or '(none)'}")
    overrides = meta.get("clause_overrides") or []
    if overrides:
        print("  clause_overrides:")
        for o in overrides:
            print(f"    - {o.get('clause_title')!r} from {o.get('source_template')}@{o.get('source_version')}")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    """Friendly version timeline for one template. Synthesizes meta.json's
    versions[] + clause_overrides[] into a single chronological view."""
    root = find_vault_root()
    cat, name, _ = parse_ref(args.ref)
    t_dir = template_dir(root, cat, name)
    if not t_dir.exists():
        raise NotFoundError(
            f"No such template: {cat}/{name}. "
            f"Run `template-vault list` to see what's in the vault."
        )
    meta = load_meta_resolved(t_dir)
    versions = list(meta.get("versions") or [])
    overrides = list(meta.get("clause_overrides") or [])
    # Merge into an event list, sorted by (date, kind-priority).
    events: List[Tuple[str, str, Dict[str, Any]]] = []
    for v in versions:
        when = v.get("added") or "?"
        events.append((when, "version", v))
    for o in overrides:
        when = (o.get("swapped_at") or "").split("T", 1)[0] or "?"
        events.append((when, "swap", o))
    # Sort: by date asc; within same date, versions before swaps.
    kind_order = {"version": 0, "swap": 1}
    events.sort(key=lambda e: (e[0], kind_order.get(e[1], 9)))

    if getattr(args, "json", False):
        payload = {
            "ref": f"{cat}/{name}",
            "latest_version": meta.get("latest_version"),
            "derived_from": meta.get("derived_from"),
            "forked_at_parent_version": meta.get("forked_at_parent_version"),
            "events": [
                {"date": when, "kind": kind, **data}
                for when, kind, data in events
            ],
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"{cat}/{name}  (latest: {meta.get('latest_version')})")
    if meta.get("derived_from"):
        print(f"  forked from {meta['derived_from']} "
              f"at parent {meta.get('forked_at_parent_version') or '?'}")
    if not events:
        print("  (no history)")
        return 0
    for when, kind, data in events:
        if kind == "version":
            vid = data.get("id")
            sup = data.get("supersedes")
            cl = data.get("changelog") or ""
            tag = "[amended]" if data.get("amended") else ""
            arrow = f" (supersedes {sup})" if sup else ""
            print(f"  {when}  {vid}{arrow} {tag}")
            if cl:
                print(f"             - {cl}")
        elif kind == "swap":
            print(f"  {when}  swap   '{data.get('clause_title')}' from "
                  f"{data.get('source_template')}@{data.get('source_version')}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    root = find_vault_root()
    cat, name, _v = parse_ref(args.ref)
    t_dir = template_dir(root, cat, name)
    meta = load_meta(t_dir)
    a = resolve_version_file(t_dir, meta, args.version_a).read_text().splitlines(keepends=True)
    b = resolve_version_file(t_dir, meta, args.version_b).read_text().splitlines(keepends=True)
    out = difflib.unified_diff(
        a, b,
        fromfile=f"{cat}/{name}@{args.version_a}",
        tofile=f"{cat}/{name}@{args.version_b}",
        n=3,
    )
    sys.stdout.writelines(out)
    return 0


# ---------------------------------------------------------------------------
# Command: clauses
# ---------------------------------------------------------------------------


def _load_template_text_and_clauses(root: Path, cat: str, name: str,
                                    version: Optional[str] = None
                                    ) -> Tuple[Path, str, List[Dict[str, Any]], Dict[str, Any]]:
    t_dir = template_dir(root, cat, name)
    if not t_dir.exists():
        raise NotFoundError(
            f"No such template: {cat}/{name}. "
            f"Run `template-vault list` to see what's in the vault."
        )
    meta = load_meta_resolved(t_dir)
    f = resolve_version_file(t_dir, meta, version)
    text = f.read_text()
    explicit = meta.get("clauses")
    aliases = meta.get("clause_aliases") if isinstance(meta.get("clause_aliases"), dict) else None
    clauses = detect_clauses(
        text,
        explicit_map=explicit if isinstance(explicit, list) else None,
        aliases_map=aliases,
    )
    return f, text, clauses, meta


def cmd_clauses(args: argparse.Namespace) -> int:
    root = find_vault_root()
    cat, name, version = parse_ref(args.ref)
    _f, _text, clauses, meta = _load_template_text_and_clauses(root, cat, name, version)
    if not clauses:
        print(f"(no clauses detected in {cat}/{name}@{meta.get('latest_version')}) -- "
              "templates use H2 (`## Heading`) for clause boundaries, or supply "
              "an explicit `clauses` map in meta.json.")
        return 0
    print(f"{cat}/{name}@{version or meta.get('latest_version')}  ({len(clauses)} clauses)")
    for c in clauses:
        print(f"  - {c['title']}    (anchor: {c['anchor']})")
        if c.get("aliases"):
            print(f"      aliases: {', '.join(c['aliases'])}")
    return 0


# ---------------------------------------------------------------------------
# Command: compose
# ---------------------------------------------------------------------------


def cmd_compose(args: argparse.Namespace) -> int:
    root = find_vault_root()
    base_cat, base_name, base_version = parse_ref(args.base)
    new_cat, new_name, _ = parse_ref(args.as_ref)
    base_dir = template_dir(root, base_cat, base_name)
    if not base_dir.exists():
        raise NotFoundError(f"Base template not found: {base_cat}/{base_name}")
    base_meta = load_meta(base_dir)
    base_file = resolve_version_file(base_dir, base_meta, base_version)
    base_vid = base_version or base_meta["latest_version"]
    new_dir = template_dir(root, new_cat, new_name)
    if new_dir.exists():
        raise VaultError(f"Target already exists: {new_cat}/{new_name}")
    new_dir.mkdir(parents=True)
    new_file = new_dir / f"v1{base_file.suffix}"
    new_file.write_bytes(base_file.read_bytes())
    new_meta = {
        "name": new_name,
        "category": new_cat,
        "latest_version": "v1",
        "versions": [{
            "id": "v1",
            "added": _today_iso(),
            "supersedes": None,
            "changelog": f"forked from {base_cat}/{base_name}@{base_vid}",
        }],
    }
    new_meta = fill_meta_defaults(new_meta)
    new_meta["jurisdiction"] = list(base_meta.get("jurisdiction") or [])
    new_meta["party_type"] = list(base_meta.get("party_type") or [])
    new_meta["deal_type"] = list(base_meta.get("deal_type") or [])
    new_meta["tags"] = list(base_meta.get("tags") or [])
    new_meta["summary"] = (
        f"Derived from {base_cat}/{base_name}@{base_vid}. "
        + (base_meta.get("summary") or "")
    ).strip()
    new_meta["derived_from"] = f"{base_cat}/{base_name}@{base_vid}"
    new_meta["forked_at_parent_version"] = base_vid
    new_meta["clause_overrides"] = []
    new_meta["license"] = base_meta.get("license", "private")
    save_meta(new_dir, new_meta)
    print(f"{_green('Composed:')} {new_cat}/{new_name}@v1  (forked from {base_cat}/{base_name}@{base_vid})")
    _why_print(
        args,
        f"forked {base_cat}/{base_name}@{base_vid} into {new_cat}/{new_name}@v1",
        f"copied file: {base_file.name} -> {new_file.relative_to(root)}",
        f"meta.derived_from set to: {new_meta['derived_from']}",
        f"meta.forked_at_parent_version set to: {new_meta['forked_at_parent_version']}",
        f"inherited fields: jurisdiction, party_type, deal_type, tags, license",
        f"clause_overrides starts empty (any future swap will append here)",
    )
    return 0


# ---------------------------------------------------------------------------
# Command: swap
# ---------------------------------------------------------------------------


def cmd_swap(args: argparse.Namespace) -> int:
    root = find_vault_root()
    target_cat, target_name, target_version = parse_ref(args.target)
    src_cat, src_name, src_version = parse_ref(args.from_ref)
    target_dir = template_dir(root, target_cat, target_name)
    src_dir = template_dir(root, src_cat, src_name)
    if not target_dir.exists():
        raise NotFoundError(f"Target template not found: {target_cat}/{target_name}")
    if not src_dir.exists():
        raise NotFoundError(f"Source template not found: {src_cat}/{src_name}")

    target_meta = load_meta(target_dir)
    src_meta = load_meta(src_dir)
    target_file = resolve_version_file(target_dir, target_meta, target_version)
    src_file = resolve_version_file(src_dir, src_meta, src_version)
    src_vid = src_version or src_meta["latest_version"]

    target_text = target_file.read_text()
    src_text = src_file.read_text()
    target_clauses = detect_clauses(
        target_text,
        explicit_map=target_meta.get("clauses") if isinstance(target_meta.get("clauses"), list) else None,
        aliases_map=effective_clause_aliases(target_dir, target_meta),
    )
    src_clauses = detect_clauses(
        src_text,
        explicit_map=src_meta.get("clauses") if isinstance(src_meta.get("clauses"), list) else None,
        aliases_map=effective_clause_aliases(src_dir, src_meta),
    )
    src_clause = find_clause_by_title(src_clauses, args.clause)
    if src_clause is None:
        avail = ", ".join(c["title"] for c in src_clauses) or "(none detected -- H2 headers missing? See `clauses` map in meta.json.)"
        raise VaultError(
            f"Clause {args.clause!r} not found in {src_cat}/{src_name}@{src_vid}. "
            f"Available: {avail}"
        )
    target_clause = find_clause_by_title(target_clauses, args.clause)
    if target_clause is None:
        avail = ", ".join(c["title"] for c in target_clauses) or "(none detected -- H2 headers missing? See `clauses` map in meta.json.)"
        raise VaultError(
            f"Clause {args.clause!r} not present in target {target_cat}/{target_name}. "
            f"Available: {avail}"
        )

    src_body = slice_clause_text(src_text, src_clause)
    # Preserve target's H2 header line so existing numbering stays intact.
    src_body_after_header = src_body.split("\n", 1)[1] if "\n" in src_body else ""
    replacement = target_clause["anchor"] + "\n" + src_body_after_header
    new_text = replace_clause(target_text, target_clause, replacement)
    target_file.write_text(new_text)

    overrides = target_meta.get("clause_overrides") or []
    overrides.append({
        "clause_title": args.clause,
        "source_template": f"{src_cat}/{src_name}",
        "source_version": src_vid,
        "swapped_at": _now_iso(),
    })
    target_meta["clause_overrides"] = overrides
    save_meta(target_dir, target_meta)

    print(f"{_green('Swapped')} clause {args.clause!r} in {target_cat}/{target_name} "
          f"from {src_cat}/{src_name}@{src_vid}.")
    _why_print(
        args,
        f"resolved source clause: {src_clause['title']!r} (anchor: {src_clause['anchor']!r})",
        f"resolved target clause: {target_clause['title']!r} (anchor: {target_clause['anchor']!r})",
        f"target H2 header preserved (so numbering stays intact)",
        f"replaced body region: chars {target_clause['start']}..{target_clause['end']}",
        f"meta.clause_overrides now has {len(overrides)} entry(ies)",
        f"target file rewritten in place: {target_file.relative_to(root)}",
    )
    return 0


# ---------------------------------------------------------------------------
# Command: compare-clauses
# ---------------------------------------------------------------------------


def cmd_compare_clauses(args: argparse.Namespace) -> int:
    root = find_vault_root()
    a_cat, a_name, a_v = parse_ref(args.a)
    b_cat, b_name, b_v = parse_ref(args.b)
    _af, a_text, a_clauses, a_meta = _load_template_text_and_clauses(root, a_cat, a_name, a_v)
    _bf, b_text, b_clauses, b_meta = _load_template_text_and_clauses(root, b_cat, b_name, b_v)
    a_label = f"{a_cat}/{a_name}@{a_v or a_meta.get('latest_version')}"
    b_label = f"{b_cat}/{b_name}@{b_v or b_meta.get('latest_version')}"

    if args.clause:
        ac = find_clause_by_title(a_clauses, args.clause)
        bc = find_clause_by_title(b_clauses, args.clause)
        if not ac:
            raise VaultError(
                f"Clause {args.clause!r} not in {a_label}. "
                f"Available: {', '.join(c['title'] for c in a_clauses) or '(none)'}"
            )
        if not bc:
            raise VaultError(
                f"Clause {args.clause!r} not in {b_label}. "
                f"Available: {', '.join(c['title'] for c in b_clauses) or '(none)'}"
            )
        a_body = slice_clause_text(a_text, ac).splitlines(keepends=True)
        b_body = slice_clause_text(b_text, bc).splitlines(keepends=True)
        out = difflib.unified_diff(
            a_body, b_body,
            fromfile=f"{a_label}#{args.clause}",
            tofile=f"{b_label}#{args.clause}",
            n=3,
        )
        sys.stdout.writelines(out)
        return 0

    # Build alias-aware equivalence over both templates' titles + aliases.
    eq = _UnionFind()
    for c in a_clauses + b_clauses:
        t = c["title"].lower()
        eq.add(t)
        for a in (c.get("aliases") or []):
            eq.union(t, a)

    a_by_repr: Dict[str, Dict[str, Any]] = {}
    b_by_repr: Dict[str, Dict[str, Any]] = {}
    for c in a_clauses:
        a_by_repr.setdefault(eq.find(c["title"].lower()), c)
    for c in b_clauses:
        b_by_repr.setdefault(eq.find(c["title"].lower()), c)

    common = sorted(set(a_by_repr) & set(b_by_repr))
    only_a = sorted(set(a_by_repr) - set(b_by_repr))
    only_b = sorted(set(b_by_repr) - set(a_by_repr))
    print(f"# {a_label}  vs  {b_label}")
    print()
    print(f"## Common clauses ({len(common)})")
    if common:
        # Width the title column so the similarity column lines up.
        labels = []
        for k in common:
            ac = a_by_repr[k]
            bc = b_by_repr[k]
            label = ac["title"]
            if bc["title"].lower() != ac["title"].lower():
                label = f"{ac['title']} / {bc['title']}"
            labels.append((k, label))
        width = max(len(lab) for _k, lab in labels)
        for k, label in labels:
            ac = a_by_repr[k]
            bc = b_by_repr[k]
            a_body = _strip_header_line(slice_clause_text(a_text, ac))
            b_body = _strip_header_line(slice_clause_text(b_text, bc))
            ratio = difflib.SequenceMatcher(None, a_body, b_body).ratio()
            marker = "identical" if a_body == b_body else f"sim={ratio:.2f}"
            print(f"  - {label.ljust(width)}    [{marker}]")
    print()
    print(f"## Only in {a_label} ({len(only_a)})")
    for k in only_a:
        print(f"  - {a_by_repr[k]['title']}")
    print()
    print(f"## Only in {b_label} ({len(only_b)})")
    for k in only_b:
        print(f"  - {b_by_repr[k]['title']}")
    return 0


# ---------------------------------------------------------------------------
# Command: upgrade
# ---------------------------------------------------------------------------


def _llm_explain_clause_diff(args: argparse.Namespace, *, clause_title: str,
                             old_body: str, new_body: str, parent_label: str,
                             old_ver: str, new_ver: str) -> str:
    """Send a clause diff to the configured LLM and return a one-paragraph
    explanation. The user opts into this with `--interactive-explain` and
    by typing `?` at the prompt; that's the consent gate (the diff content
    leaves the local machine)."""
    cfg = _load_llm_config(args)
    diff_lines = list(difflib.unified_diff(
        old_body.splitlines(keepends=True),
        new_body.splitlines(keepends=True),
        fromfile=f"{parent_label}@{old_ver}",
        tofile=f"{parent_label}@{new_ver}",
        n=3,
    ))
    diff_text = "".join(diff_lines)[:4000]
    system = (
        "You are a contracts-savvy reviewer. Given a unified diff of one "
        "clause between two versions of a legal template, write ONE short "
        "paragraph (≤80 words) that says (a) what changed and (b) what "
        "risk or shift in obligation that introduces. Be concrete. No "
        "marketing, no caveats, no list formatting."
    )
    user = (
        f"Clause: {clause_title}\n"
        f"Parent: {parent_label}\n"
        f"From: {old_ver}\nTo: {new_ver}\n\n"
        f"```diff\n{diff_text}\n```"
    )
    return _llm_request(cfg, system=system, user=user)


def cmd_upgrade(args: argparse.Namespace) -> int:
    root = find_vault_root()
    cat, name, _ = parse_ref(args.ref)
    t_dir = template_dir(root, cat, name)
    if not t_dir.exists():
        raise NotFoundError(
            f"No such template: {cat}/{name}. "
            f"Run `template-vault list` to see what's in the vault."
        )
    meta = load_meta(t_dir)
    parent_ref = meta.get("derived_from")
    parent_v_at_fork = meta.get("forked_at_parent_version")
    if not parent_ref:
        raise VaultError(
            f"{cat}/{name} has no parent (derived_from is null). "
            "Only composed/derived templates can be upgraded."
        )
    p_cat, p_name, _ = parse_ref(parent_ref)
    p_dir = template_dir(root, p_cat, p_name)
    if not p_dir.exists():
        raise NotFoundError(f"Parent template not found in vault: {p_cat}/{p_name}")
    p_meta = load_meta(p_dir)
    parent_latest = p_meta["latest_version"]
    if parent_latest == parent_v_at_fork:
        print(f"Up to date. Parent {p_cat}/{p_name} is still at {parent_latest}.")
        return 0
    fork_file = resolve_version_file(p_dir, p_meta, parent_v_at_fork)
    latest_file = resolve_version_file(p_dir, p_meta, parent_latest)
    fork_text = fork_file.read_text()
    latest_text = latest_file.read_text()
    p_aliases = effective_clause_aliases(p_dir, p_meta)
    p_explicit = p_meta.get("clauses") if isinstance(p_meta.get("clauses"), list) else None
    fork_clauses = detect_clauses(fork_text, explicit_map=p_explicit, aliases_map=p_aliases)
    latest_clauses = detect_clauses(latest_text, explicit_map=p_explicit, aliases_map=p_aliases)

    derived_file = resolve_version_file(t_dir, meta, meta["latest_version"])
    derived_text = derived_file.read_text()
    d_aliases = effective_clause_aliases(t_dir, meta)
    d_explicit = meta.get("clauses") if isinstance(meta.get("clauses"), list) else None
    derived_clauses = detect_clauses(
        derived_text, explicit_map=d_explicit, aliases_map=d_aliases,
    )

    # Build per-clause diff fork→latest
    fork_idx = {c["title"].lower(): c for c in fork_clauses}
    latest_idx = {c["title"].lower(): c for c in latest_clauses}
    derived_idx = {c["title"].lower(): c for c in derived_clauses}

    # Don't overwrite clauses the user explicitly swapped from another source.
    overridden = {o["clause_title"].lower() for o in (meta.get("clause_overrides") or [])}

    accepted = 0
    skipped_overridden = 0
    new_text = derived_text
    dry_run = getattr(args, "dry_run", False)
    if dry_run:
        print(f"(dry-run: showing changes from {p_cat}/{p_name}@{parent_v_at_fork} -> {parent_latest}; nothing will be written)")
    # Re-detect each iteration since indices shift after replacement
    for title_lc in sorted(set(fork_idx) & set(latest_idx)):
        fb = slice_clause_text(fork_text, fork_idx[title_lc])
        lb = slice_clause_text(latest_text, latest_idx[title_lc])
        if fb == lb:
            continue
        if title_lc in overridden:
            skipped_overridden += 1
            print(f"  skipped (locally swapped): {fork_idx[title_lc]['title']}")
            continue
        if title_lc not in derived_idx:
            print(f"  not present in derived: {fork_idx[title_lc]['title']}  (skipping)")
            continue
        # Show the diff
        print(f"--- {fork_idx[title_lc]['title']} ---")
        for line in difflib.unified_diff(
            fb.splitlines(keepends=True),
            lb.splitlines(keepends=True),
            fromfile=f"parent@{parent_v_at_fork}",
            tofile=f"parent@{parent_latest}",
            n=2,
        ):
            sys.stdout.write(line)
        if dry_run:
            accepted += 1
            continue
        if args.accept_all:
            decision = "y"
        else:
            explain_prompt = " or ? for an LLM explanation" if getattr(args, "interactive_explain", False) else ""
            decision = "n"
            while True:
                try:
                    raw = input(f"Accept this upstream change? [y/N{explain_prompt}] ").strip().lower()
                except EOFError:
                    raw = "n"
                if raw == "?" and getattr(args, "interactive_explain", False):
                    try:
                        explanation = _llm_explain_clause_diff(
                            args, clause_title=fork_idx[title_lc]["title"],
                            old_body=fb, new_body=lb,
                            parent_label=f"{p_cat}/{p_name}",
                            old_ver=parent_v_at_fork, new_ver=parent_latest,
                        )
                        print("\n[LLM] " + explanation.strip() + "\n")
                    except VaultError as exc:
                        _eprint(f"  (explain failed: {exc})")
                    continue
                decision = raw
                break
        if decision == "y":
            # Re-detect derived clauses against current new_text
            cur_clauses = detect_clauses(
                new_text, explicit_map=d_explicit, aliases_map=d_aliases,
            )
            cur_target = find_clause_by_title(cur_clauses, fork_idx[title_lc]["title"])
            if cur_target is None:
                print("  (skipping; clause vanished mid-merge)")
                continue
            replacement_body = lb
            # Preserve derived's existing header
            replacement_body_after_header = (
                replacement_body.split("\n", 1)[1] if "\n" in replacement_body else ""
            )
            replacement = cur_target["anchor"] + "\n" + replacement_body_after_header
            new_text = replace_clause(new_text, cur_target, replacement)
            accepted += 1

    if accepted == 0 and skipped_overridden == 0:
        print(f"No upstream changes to merge from {p_cat}/{p_name}@{parent_latest}.")
        if not dry_run:
            meta["forked_at_parent_version"] = parent_latest
            save_meta(t_dir, meta)
        return 0

    if dry_run:
        print(f"\n(dry-run summary) would accept {accepted} clause change(s); "
              f"{skipped_overridden} skipped due to local swap. "
              f"Re-run without --dry-run to apply.")
        return 0

    # Write a new version
    next_vid = auto_increment_version(meta)
    new_file = t_dir / f"{next_vid}{derived_file.suffix}"
    new_file.write_text(new_text)
    meta["versions"].append({
        "id": next_vid,
        "added": _today_iso(),
        "supersedes": meta["latest_version"],
        "changelog": f"upgraded from parent {parent_v_at_fork} → {parent_latest} "
                     f"({accepted} clauses accepted, {skipped_overridden} skipped due to local swap)",
    })
    for v in meta["versions"]:
        if v.get("id") == meta["latest_version"]:
            v["supersedes_by"] = next_vid
    meta["latest_version"] = next_vid
    meta["forked_at_parent_version"] = parent_latest
    save_meta(t_dir, meta)
    print(f"{_green('Wrote')} {cat}/{name}@{next_vid}: accepted={accepted}, skipped_overridden={skipped_overridden}.")
    _why_print(
        args,
        f"parent: {p_cat}/{p_name} moved {parent_v_at_fork} -> {parent_latest}",
        f"per-clause merge: {accepted} accepted, {skipped_overridden} skipped (locally swapped)",
        f"new derived version: {next_vid}; file written: {new_file.relative_to(root)}",
        f"meta.forked_at_parent_version now: {parent_latest}",
        f"locally-swapped clauses (in clause_overrides) were NOT touched",
    )
    return 0


# ---------------------------------------------------------------------------
# Command: clause-library
# ---------------------------------------------------------------------------


def _slug_from_title(title: str) -> str:
    """Lowercase, hyphenate, strip non-[a-z0-9-] for use as a filename."""
    s = re.sub(r"\s+", "-", title.strip().lower())
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "clause"


def _strip_header_line(body: str) -> str:
    """Drop the leading `## …` header from a clause body before similarity
    comparison. Two clauses with different numbering ('## 4. Foo' vs '## 7. Foo')
    have identical content but different headers; including the header line
    depresses ratio() and under-clusters."""
    return body.split("\n", 1)[1] if "\n" in body else ""


class _UnionFind:
    """Minimal string-keyed union-find for clause-title equivalence classes."""

    def __init__(self) -> None:
        self._parent: Dict[str, str] = {}

    def add(self, x: str) -> None:
        self._parent.setdefault(x, x)

    def find(self, x: str) -> str:
        self.add(x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Make the lexicographically smaller one the representative so the
            # output is deterministic across runs.
            self._parent[max(ra, rb)] = min(ra, rb)


def _suggest_aliases(per_template: List[Tuple[str, str, str, List[Dict[str, Any]], str]],
                     eq: "_UnionFind", threshold: float) -> None:
    """Cross-bucket near-misses: clause bodies that look the same but have
    different normalized titles AND aren't already in the same equivalence
    class. The user can promote any of these to clause_aliases.
    """
    # (normalized_title, raw_title, label, body_no_header)
    items: List[Tuple[str, str, str, str]] = []
    for _cat, label, _ver, clauses, text in per_template:
        for c in clauses:
            body = _strip_header_line(slice_clause_text(text, c))
            items.append((c["title"].lower(), c["title"], label, body))

    # Group {(canonical_title_pair) → list of (label_a, label_b, ratio, raw_a, raw_b)}.
    suggestions: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for i in range(len(items)):
        ti, raw_i, label_i, body_i = items[i]
        for j in range(i + 1, len(items)):
            tj, raw_j, label_j, body_j = items[j]
            if ti == tj:
                continue  # already same title bucket
            if eq.find(ti) == eq.find(tj):
                continue  # already aliased somewhere
            r = difflib.SequenceMatcher(None, body_i, body_j).ratio()
            if r < threshold:
                continue
            # Stable order: lexicographic on normalized title.
            (a_norm, a_raw, a_label), (b_norm, b_raw, b_label) = sorted(
                ((ti, raw_i, label_i), (tj, raw_j, label_j))
            )
            suggestions.setdefault((a_norm, b_norm), []).append({
                "ratio": r, "a_raw": a_raw, "b_raw": b_raw,
                "a_label": a_label, "b_label": b_label,
            })

    if not suggestions:
        print("\n(no alias suggestions; no near-miss bodies with different titles)")
        return

    print(f"\nAlias suggestions (sim >= {threshold:.2f}, different titles, "
          f"not already aliased):")
    sorted_pairs = sorted(suggestions.items(),
                          key=lambda kv: (-len(kv[1]), -max(s["ratio"] for s in kv[1])))
    for (_a, _b), entries in sorted_pairs:
        a_raw = entries[0]["a_raw"]
        b_raw = entries[0]["b_raw"]
        max_r = max(s["ratio"] for s in entries)
        labels = sorted({s["a_label"] for s in entries} | {s["b_label"] for s in entries})
        print(f"  - {a_raw!r}  <->  {b_raw!r}   (best sim={max_r:.2f}, "
              f"in {len(labels)} template(s))")
        for lab in labels:
            print(f"      - {lab}")
    print("\nTo accept a suggestion, add to the canonical template's meta.json:")
    print('  "clause_aliases": { "<canonical title>": ["<alternate title>"] }')


def cmd_clause_library(args: argparse.Namespace) -> int:
    root = find_vault_root()
    threshold = args.threshold

    # Pass 1: collect occurrences and build the title equivalence map.
    Occurrence = Tuple[str, str, str, str, str, str]  # (cat, label, ver, raw_title, body, body_no_header)
    per_template: List[Tuple[str, str, str, List[Dict[str, Any]], str]] = []
    eq = _UnionFind()
    for cat, name, _path, meta in iter_templates(root):
        try:
            f = resolve_version_file(template_dir(root, cat, name), meta, None)
            text = f.read_text()
        except (VaultError, OSError):
            continue
        explicit = meta.get("clauses") if isinstance(meta.get("clauses"), list) else None
        aliases = meta.get("clause_aliases") if isinstance(meta.get("clause_aliases"), dict) else None
        clauses = detect_clauses(text, explicit_map=explicit, aliases_map=aliases)
        per_template.append((cat, f"{cat}/{name}", meta.get("latest_version") or "?", clauses, text))
        for c in clauses:
            t = c["title"].lower()
            eq.add(t)
            for a in (c.get("aliases") or []):
                eq.union(t, a)

    # Pass 2: bucket occurrences by union-find representative.
    by_repr: Dict[str, List[Occurrence]] = {}
    for cat, label, ver, clauses, text in per_template:
        for c in clauses:
            body = slice_clause_text(text, c)
            body_no_header = _strip_header_line(body)
            key = eq.find(c["title"].lower())
            by_repr.setdefault(key, []).append(
                (cat, label, ver, c["title"], body, body_no_header)
            )

    # Pass 3: greedy clustering on header-stripped bodies.
    clusters: List[Dict[str, Any]] = []
    for _key, occurrences in by_repr.items():
        if len(occurrences) < 2:
            continue
        used = [False] * len(occurrences)
        for i, ref in enumerate(occurrences):
            if used[i]:
                continue
            ref_cat, ref_label, ref_ver, ref_title, ref_body, ref_body_h = ref
            cluster_members = [(ref_label, ref_ver, ref_title)]
            ratios = [1.0]
            used[i] = True
            for j, other in enumerate(occurrences[i + 1:], start=i + 1):
                if used[j]:
                    continue
                _ocat, olabel, over, otitle, _obody, obody_h = other
                r = difflib.SequenceMatcher(None, ref_body_h, obody_h).ratio()
                if r >= threshold:
                    cluster_members.append((olabel, over, otitle))
                    ratios.append(r)
                    used[j] = True
            if len(cluster_members) >= 2:
                clusters.append({
                    "title": ref_title,
                    "members": cluster_members,
                    "mean_r": sum(ratios) / len(ratios),
                    "ref_body": ref_body,
                    "ref_category": ref_cat,
                })

    clusters.sort(key=lambda c: (-len(c["members"]), -c["mean_r"], c["title"]))
    if clusters:
        for c in clusters:
            print(f"- {c['title']}  (n={len(c['members'])}, mean_similarity={c['mean_r']:.2f})")
            for ref, ver, member_title in c["members"]:
                if member_title.lower() != c["title"].lower():
                    print(f"    - {ref}@{ver}  (as {member_title!r})")
                else:
                    print(f"    - {ref}@{ver}")
    else:
        print(f"(no clusters above threshold {threshold:.2f})")

    if getattr(args, "suggest_aliases", False):
        _suggest_aliases(per_template, eq, threshold)

    if not args.extract:
        return 0
    if not clusters:
        return 0

    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not interactive and not args.yes_extract_all:
        _eprint(
            "\n--extract in a non-interactive context requires --yes-extract-all "
            "to confirm extraction of every cluster shown above."
        )
        return 1

    extracted = 0
    for c in clusters:
        slug = _slug_from_title(c["title"])
        dest = root / "clauses" / c["ref_category"] / f"{slug}.md"
        if dest.exists():
            print(f"  skip: {dest.relative_to(root)} already exists")
            continue
        if not args.yes_extract_all:
            try:
                ans = input(
                    f'\nExtract "{c["title"]}" → '
                    f'{dest.relative_to(root)} ? [y/N] '
                ).strip().lower()
            except EOFError:
                ans = "n"
            if ans != "y":
                continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Body already starts with the H2 header. Add a small provenance note.
        members_str = ", ".join(f"{ref}@{ver}" for ref, ver, _t in c["members"])
        provenance = (
            f"<!-- extracted by template-vault clause-library on {_today_iso()} "
            f"from: {members_str} -->\n\n"
        )
        dest.write_text(provenance + c["ref_body"].rstrip() + "\n")
        extracted += 1
        print(f"  wrote: {dest.relative_to(root)}")

    if extracted == 0:
        print("\n(no clusters extracted)")
    else:
        print(f"\nextracted {extracted} cluster(s) to clauses/")
    return 0


# ---------------------------------------------------------------------------
# Command: ask
# ---------------------------------------------------------------------------


_ASK_SYSTEM = (
    "You are an assistant helping a user select or compose the best-fit legal "
    "template from their organization's library. You will be given a list of "
    "templates with metadata and clause titles, plus a user query. Recommend "
    "the top match and 1-2 alternatives, with brief reasoning that references "
    "each template's metadata. If the query asks for composition, emit a "
    "sequence of `compose` and `swap` commands using only template names and "
    "clause titles that appear in the listing. Do NOT invent templates or "
    "clauses that aren't in the list. Reply in plain text, not JSON."
)


def _ask_build_listing(root: Path, top_k: int, with_content: bool,
                       query: str) -> Tuple[str, List[Tuple[str, str]]]:
    """Build the listing string sent to the LLM and return the candidate set."""
    candidates: List[Tuple[float, str, str, Dict[str, Any], Path]] = []
    q = query.lower()
    for cat, name, path, meta in iter_templates(root):
        haystack = " ".join([
            cat, name,
            meta.get("summary") or "",
            " ".join(meta.get("tags") or []),
            " ".join(meta.get("jurisdiction") or []),
            " ".join(meta.get("deal_type") or []),
        ]).lower()
        score = 2.0 if q in haystack else difflib.SequenceMatcher(None, q, haystack).ratio()
        candidates.append((score, cat, name, meta, path))
    candidates.sort(reverse=True, key=lambda t: t[0])
    chosen = candidates[:top_k]
    parts: List[str] = []
    for score, cat, name, meta, path in chosen:
        try:
            f = resolve_version_file(path, meta, None)
            text = f.read_text()
            clauses = detect_clauses(
                text,
                explicit_map=meta.get("clauses") if isinstance(meta.get("clauses"), list) else None,
                aliases_map=meta.get("clause_aliases") if isinstance(meta.get("clause_aliases"), dict) else None,
            )
        except (VaultError, OSError):
            text, clauses = "", []
        parts.append(f"### {cat}/{name}@{meta.get('latest_version')}")
        parts.append(f"summary: {meta.get('summary') or '(none)'}")
        parts.append(f"jurisdiction: {', '.join(meta.get('jurisdiction') or []) or '-'}")
        parts.append(f"tags: {', '.join(meta.get('tags') or []) or '-'}")
        parts.append(f"clauses: {', '.join(c['title'] for c in clauses) or '(none)'}")
        if with_content and text:
            excerpt = text[:500].replace("\n", " ")
            parts.append(f"excerpt(500): {excerpt}")
        parts.append("")
    listing = "\n".join(parts)
    return listing, [(cat, name) for _s, cat, name, _m, _p in chosen]


def cmd_ask(args: argparse.Namespace) -> int:
    root = find_vault_root()
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    no_confirm = os.environ.get(NO_CONFIRM_ENV) == "1"
    if args.with_content:
        if not (interactive or no_confirm or args.yes_send):
            raise VaultError(
                "--with-content sends template excerpts to the LLM provider. "
                "Refusing in non-interactive mode without explicit consent. "
                f"Pass --yes-send or set {NO_CONFIRM_ENV}=1 to confirm."
            )
        if interactive and not no_confirm and not args.yes_send:
            cfg_preview = _load_llm_config(args)
            provider = cfg_preview.get("provider", "anthropic")
            model = cfg_preview.get("model") or "(default)"
            base = cfg_preview.get("base_url") or "(default)"
            _eprint(
                f"\nWARNING: --with-content will send template excerpts to:\n"
                f"  provider: {provider}\n  model:    {model}\n  base_url: {base}\n"
                f"Only metadata is sent without --with-content.\n"
            )
            try:
                ans = input("Proceed? [y/N] ").strip().lower()
            except EOFError:
                ans = "n"
            if ans != "y":
                _eprint("aborted")
                return 1

    listing, _candidates = _ask_build_listing(root, args.top_k, args.with_content, args.query)
    user_msg = f"Templates:\n\n{listing}\n\nUser query: {args.query}"
    cfg = _load_llm_config(args)
    text = _llm_request(cfg, system=_ASK_SYSTEM, user=user_msg)
    quiet_json = getattr(args, "quiet", False)
    if quiet_json and not args.json:
        raise VaultError("--quiet only makes sense with --json")
    if not quiet_json:
        print(text.strip())
    if args.json:
        # Also emit a structured summary on stdout (callers can parse separately)
        json.dump(
            {"query": args.query, "with_content": args.with_content,
             "candidates": [{"category": c, "name": n} for c, n in _candidates],
             "answer": text.strip()},
            sys.stdout, indent=2,
        )
        sys.stdout.write("\n")
    if args.execute:
        return _execute_llm_commands(text, interactive=interactive,
                                     yes_execute=args.yes_execute)
    return 0


# Only the structural primitives can be auto-executed. Anything that mutates
# the vault destructively (upload, import, publish), reads/writes outside the
# vault, or could exfiltrate content stays manual.
_EXECUTABLE_SUBCOMMANDS = {"compose", "swap"}


def _parse_executable_commands(llm_text: str) -> Tuple[List[List[str]], List[str]]:
    """Scan an LLM response for `template-vault …` lines.

    Returns (allowed_argvs, skipped_reasons). Allowed argvs are stripped of the
    program name (so `["compose", "--base", ...]`). Subcommands not in the
    whitelist are reported via skipped_reasons.
    """
    allowed: List[List[str]] = []
    skipped: List[str] = []
    for raw in llm_text.splitlines():
        line = raw.strip()
        # Strip common shell-prompt and code-fence prefixes.
        for prefix in ("$ ", "> ", "```bash", "```sh", "```", "`"):
            if line.startswith(prefix):
                line = line[len(prefix):].strip()
        line = line.rstrip("`").strip()
        if not line.startswith("template-vault "):
            continue
        try:
            argv = shlex.split(line)
        except ValueError:
            skipped.append(f"unparseable: {line}")
            continue
        if len(argv) < 2 or argv[0] != "template-vault":
            continue
        sub = argv[1]
        if sub not in _EXECUTABLE_SUBCOMMANDS:
            skipped.append(f"subcommand not auto-executable: {sub}")
            continue
        allowed.append(argv[1:])
    return allowed, skipped


def _execute_llm_commands(llm_text: str, *, interactive: bool,
                          yes_execute: bool) -> int:
    cmds, skipped = _parse_executable_commands(llm_text)
    if skipped:
        for s in skipped:
            _eprint(f"  skipped: {s}")
    if not cmds:
        _eprint("(--execute: no compose/swap commands found in the LLM response)")
        return 0
    print("\nProposed commands:")
    for argv in cmds:
        print("  template-vault " + " ".join(shlex.quote(a) for a in argv))
    if not yes_execute:
        if not interactive:
            _eprint(
                "\n--execute in a non-interactive context requires --yes-execute "
                "to confirm running the commands above."
            )
            return 1
        try:
            ans = input("\nRun these? [y/N] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans != "y":
            _eprint("aborted")
            return 0
    for argv in cmds:
        rendered = "template-vault " + " ".join(shlex.quote(a) for a in argv)
        print(f"\n=> {rendered}")
        rc = main(argv)
        if rc != 0:
            _eprint(f"command failed (exit {rc}); stopping the chain")
            return rc
    return 0


# ---------------------------------------------------------------------------
# Command: import / sources
# ---------------------------------------------------------------------------


def cmd_sources(_args: argparse.Namespace) -> int:
    override = _resolve_sources_path(_args)
    reg = load_sources_registry(override)
    label = "custom" if override else "bundled"
    print(f"{label.capitalize()} sources (schema_version={reg.get('schema_version')}):")
    if override:
        print(f"  registry: {override}")
    for src in reg.get("sources", []):
        print(f"  {src['id']}")
        print(f"    category: {src.get('category')}")
        print(f"    license:  {src.get('license')}")
        print(f"    url:      {src.get('url')}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    root = find_vault_root()
    reg = load_sources_registry(_resolve_sources_path(args))
    matches = [s for s in reg.get("sources", []) if s.get("id") == args.source_id]
    if not matches:
        ids = ", ".join(s["id"] for s in reg.get("sources", []))
        raise VaultError(f"Unknown source: {args.source_id!r}. Available: {ids}")
    src = matches[0]
    url = src["url"]
    expected_hash = src.get("sha256")
    print(f"Fetching {url} ...", file=sys.stderr)
    try:
        body = _fetch_url(url)
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        raise VaultError(f"Could not fetch {url}: {e}") from e
    actual_hash = sha256_bytes(body)
    if expected_hash and not args.no_verify:
        if expected_hash != actual_hash:
            raise VaultError(
                f"Hash mismatch for {args.source_id}: expected {expected_hash}, got {actual_hash}. "
                "Refuse import. Re-pin with --pin-hash if you trust the new content."
            )
    elif args.pin_hash:
        # Persist into a writable copy in the vault config
        cfg = read_vault_config(root)
        pinned = cfg.setdefault("pinned_source_hashes", {})
        pinned[args.source_id] = actual_hash
        write_vault_config(root, cfg)
        print(f"Pinned hash for {args.source_id}: {actual_hash}", file=sys.stderr)
    elif not expected_hash:
        print(f"Note: no sha256 in registry for {args.source_id}; observed {actual_hash}. "
              "Use --pin-hash to record it for future verification.", file=sys.stderr)

    # Determine extension by content-type heuristic; default to .md
    ext = ".md"
    if body.lstrip().startswith(b"%PDF"):
        ext = ".pdf"
    elif b"<html" in body[:512].lower():
        ext = ".html"

    cat = src["category"]
    name = src["name"]
    t_dir = template_dir(root, cat, name)
    new = not t_dir.exists()
    t_dir.mkdir(parents=True, exist_ok=True)
    meta = load_meta(t_dir) if (t_dir / META_FILENAME).exists() else {
        "name": name,
        "category": cat,
        "latest_version": None,
        "versions": [],
    }
    meta = fill_meta_defaults(meta)
    vid = auto_increment_version(meta)
    dest = t_dir / f"{vid}{ext}"
    dest.write_bytes(body)
    meta["versions"].append({
        "id": vid,
        "added": _today_iso(),
        "supersedes": meta.get("latest_version"),
        "changelog": f"imported from {args.source_id}",
        "sha256": actual_hash,
    })
    if meta.get("latest_version"):
        for v in meta["versions"]:
            if v.get("id") == meta["latest_version"]:
                v["supersedes_by"] = vid
    meta["latest_version"] = vid
    meta["source"] = url
    if not meta.get("summary"):
        meta["summary"] = src.get("summary") or ""
    meta["license"] = src.get("license") or meta.get("license")
    if src.get("attribution"):
        meta["attribution"] = src["attribution"]
    incoming_tags = set(src.get("tags") or [])
    meta["tags"] = sorted(set(meta.get("tags") or []) | incoming_tags)
    save_meta(t_dir, meta)
    print(f"{_green('Imported:') if new else _green('Updated:')} {cat}/{name}@{vid}  (license: {src.get('license')})")
    if src.get("attribution"):
        print(f"  attribution required: {src['attribution']}")
    _why_print(
        args,
        f"fetched: {url}",
        f"sha256 (observed): {actual_hash}",
        f"sha256 (expected): {expected_hash or '(none -- no pin in registry)'}",
        f"license recorded: {src.get('license')}",
        f"written to: {dest.relative_to(root)}",
    )
    return 0


# ---------------------------------------------------------------------------
# Command: sync / publish
# ---------------------------------------------------------------------------


def cmd_sync(_args: argparse.Namespace) -> int:
    root = find_vault_root()
    try:
        r = _git(["pull"], root, check=False)
        sys.stdout.write(r.stdout)
        if r.stderr:
            sys.stderr.write(r.stderr)
        return r.returncode
    except FileNotFoundError as e:
        raise VaultError("git not found in PATH") from e


def cmd_publish(_args: argparse.Namespace) -> int:
    root = find_vault_root()
    try:
        r = _git(["push"], root, check=False)
        sys.stdout.write(r.stdout)
        if r.stderr:
            sys.stderr.write(r.stderr)
        return r.returncode
    except FileNotFoundError as e:
        raise VaultError("git not found in PATH") from e


# ---------------------------------------------------------------------------
# Command: doctor
# ---------------------------------------------------------------------------


_BASH_COMPLETION = r"""# template-vault bash completion
# Install:
#   template-vault completion bash >> ~/.bashrc
# or for one shell only:
#   eval "$(template-vault completion bash)"

_template_vault_completions() {
    local cur prev cmds
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    cmds="init upload list find get info diff clauses compose swap compare-clauses upgrade clause-library ask sources import sync publish doctor verify history export completion"
    if [ "$COMP_CWORD" -eq 1 ]; then
        # shellcheck disable=SC2207
        COMPREPLY=( $(compgen -W "${cmds}" -- "${cur}") )
        return 0
    fi
}
complete -F _template_vault_completions template-vault
"""

_ZSH_COMPLETION = r"""# template-vault zsh completion
# Install:
#   template-vault completion zsh >> ~/.zshrc
# Make sure compinit is loaded earlier in your zshrc.

_template_vault() {
    local -a cmds
    cmds=(
        'init:Initialize a vault in the current dir'
        'upload:Add a template version to the vault'
        'list:List templates'
        'find:Keyword search across metadata'
        'get:Print a template (or its path with --path-only)'
        'info:Show metadata for a template'
        'diff:Unified diff between two versions'
        'clauses:List clauses detected in a template'
        'compose:Fork a template into a new derived one'
        'swap:Replace one clause from another template'
        'compare-clauses:Compare clauses between two templates'
        'upgrade:Pull parent-template changes into a derived template'
        'clause-library:Find repeated clauses across the vault'
        'ask:LLM-conversational template recommendation'
        'sources:List bundled public-source registry entries'
        'import:Import a template from a configured public source'
        'sync:git pull (thin wrapper)'
        'publish:git push (thin wrapper)'
        'doctor:Vault integrity check'
        'verify:Content-level sha256 integrity check'
        'history:Chronological timeline'
        'export:Export a template to another format'
        'completion:Emit a shell completion script'
    )
    if (( CURRENT == 2 )); then
        _describe 'subcommand' cmds
    fi
}
compdef _template_vault template-vault
"""


def cmd_completion(args: argparse.Namespace) -> int:
    shell = (args.shell or "").lower()
    if shell == "bash":
        sys.stdout.write(_BASH_COMPLETION)
        return 0
    if shell == "zsh":
        sys.stdout.write(_ZSH_COMPLETION)
        return 0
    raise VaultError(
        f"Unsupported shell: {args.shell!r}. Supported: bash, zsh."
    )


def cmd_verify(args: argparse.Namespace) -> int:
    """Content-level integrity check. Walks every template/version, computes
    sha256 of the file on disk, and compares against any `sha256` recorded
    on the version entry. With --update-hashes, populates missing hashes and
    saves meta.json (useful one-shot when adopting verify on an existing
    vault). With --strict, reports missing hashes as failures."""
    root = find_vault_root()
    updated = 0
    mismatched = 0
    missing = 0
    checked = 0
    for cat, name, t_dir, meta in iter_templates(root):
        meta_changed = False
        for v in (meta.get("versions") or []):
            vid = v.get("id")
            if not vid:
                continue
            files = sorted(p for p in t_dir.glob(f"{vid}.*") if p.is_file())
            if not files:
                print(f"  {cat}/{name}@{vid}: file missing on disk")
                mismatched += 1
                continue
            path = files[0]
            actual = sha256_bytes(path.read_bytes())
            recorded = v.get("sha256")
            checked += 1
            if recorded is None:
                if args.update_hashes:
                    v["sha256"] = actual
                    meta_changed = True
                    updated += 1
                    print(f"  {cat}/{name}@{vid}: recorded sha256={actual[:12]}...")
                else:
                    if args.strict:
                        print(f"  {cat}/{name}@{vid}: NO HASH (strict)")
                        mismatched += 1
                    else:
                        missing += 1
                continue
            if recorded != actual:
                print(f"  {cat}/{name}@{vid}: MISMATCH")
                print(f"      recorded: {recorded}")
                print(f"      actual:   {actual}")
                mismatched += 1
        if meta_changed:
            # Save the per-template raw meta, not the resolved one.
            raw = load_meta(t_dir)
            recorded_ids = {v.get("id"): v.get("sha256") for v in (meta.get("versions") or [])}
            for v in (raw.get("versions") or []):
                vid = v.get("id")
                if vid and recorded_ids.get(vid) and not v.get("sha256"):
                    v["sha256"] = recorded_ids[vid]
            save_meta(t_dir, raw)

    summary = (
        f"checked {checked} file(s); "
        f"mismatched {mismatched}; "
        f"missing-hash {missing}"
    )
    if args.update_hashes:
        summary += f"; updated {updated}"
    print(summary)
    return 1 if mismatched else 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Single-screen vault overview: counts, hygiene coverage, last activity."""
    root = find_vault_root()
    cfg = read_vault_config(root)
    created = cfg.get("created") or "?"

    by_cat: Dict[str, int] = {}
    versions = 0
    imports = 0
    imports_hashed = 0
    composed = 0
    with_summary = 0
    with_tags = 0
    with_sha = 0
    total_versions = 0
    last_activity: Optional[str] = None
    last_activity_ref: Optional[str] = None

    sources_set: set = set()
    for cat, name, _path, meta in iter_templates(root):
        by_cat[cat] = by_cat.get(cat, 0) + 1
        vs = meta.get("versions") or []
        versions += 1  # counts templates; rename below
        total_versions += len(vs)
        if (meta.get("summary") or "").strip():
            with_summary += 1
        if meta.get("tags"):
            with_tags += 1
        if meta.get("source"):
            imports += 1
            sources_set.add(meta.get("source") or "")
        if meta.get("derived_from"):
            composed += 1
        for v in vs:
            if isinstance(v, dict) and v.get("sha256"):
                with_sha += 1
        # Track most-recent "added" timestamp across all versions.
        for v in vs:
            if isinstance(v, dict):
                added = v.get("added")
                if added and (last_activity is None or added > last_activity):
                    last_activity = added
                    last_activity_ref = f"{cat}/{name}@{v.get('id')}"
        # Imports with verified hash: source field set AND at least one version
        # has a recorded sha256.
        if meta.get("source") and any(
            isinstance(v, dict) and v.get("sha256") for v in vs
        ):
            imports_hashed += 1

    templates_total = sum(by_cat.values())

    if getattr(args, "json", False):
        payload = {
            "vault_root": str(root),
            "created": created,
            "categories": dict(sorted(by_cat.items())),
            "templates": templates_total,
            "versions_total": total_versions,
            "imports": imports,
            "imports_hashed": imports_hashed,
            "import_sources": sorted(sources_set),
            "compositions": composed,
            "coverage": {
                "with_summary": [with_summary, templates_total],
                "with_tags":    [with_tags, templates_total],
                "versions_with_sha256": [with_sha, total_versions],
            },
            "last_activity": last_activity,
            "last_activity_ref": last_activity_ref,
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"Vault:         {root}  (initialized {created})")
    cat_summary = ", ".join(f"{c}: {n}" for c, n in sorted(by_cat.items())) or "-"
    print(f"Categories:    {len(by_cat)}        ({cat_summary})")
    print(f"Templates:     {templates_total}")
    avg = (total_versions / templates_total) if templates_total else 0
    print(f"Versions:      {total_versions}        (avg {avg:.1f} per template)")
    if imports:
        print(f"Imports:       {imports}        "
              f"(from {len(sources_set)} public source(s), "
              f"{imports_hashed} with verified sha256)")
    if composed:
        print(f"Compositions:  {composed}        (derived templates with parent provenance)")
    if templates_total:
        print(f"Coverage:      {with_summary}/{templates_total}    templates have summaries")
        print(f"               {with_tags}/{templates_total}    templates have at least one tag")
        print(f"               {with_sha}/{total_versions}    versions have recorded sha256")
    if last_activity and last_activity_ref:
        print(f"Last activity: {last_activity} (added {last_activity_ref})")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    root = find_vault_root()
    cfg = read_vault_config(root)
    issues: List[str] = []
    warnings: List[str] = []
    issues.extend(validate_vault_config(cfg))
    seen_categories: List[str] = []
    seen_templates = 0
    for cat_dir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if cat_dir.name in {"config", "tests", ".git", ".github"}:
            continue
        seen_categories.append(cat_dir.name)
        if cat_dir.name not in KNOWN_CATEGORIES:
            issues.append(f"unrecognized category: {cat_dir.name} (allowed but unusual)")
        for t_dir in sorted(p for p in cat_dir.iterdir() if p.is_dir()):
            seen_templates += 1
            mp = t_dir / META_FILENAME
            if not mp.exists():
                issues.append(f"missing meta.json: {cat_dir.name}/{t_dir.name}")
                continue
            try:
                meta = load_meta(t_dir)
            except VaultError as e:
                issues.append(f"meta.json error in {cat_dir.name}/{t_dir.name}: {e}")
                continue
            errs = validate_meta(meta)
            for e in errs:
                issues.append(f"{cat_dir.name}/{t_dir.name}: {e}")
            # Latest pointer must point at a real file
            try:
                resolve_version_file(t_dir, meta, None)
            except VaultError as e:
                issues.append(f"{cat_dir.name}/{t_dir.name}: latest_version unreachable ({e})")
            # Version-numbering gaps (vN sequence)
            ids = [v.get("id") for v in meta.get("versions") or []]
            if all(isinstance(i, str) and re.fullmatch(r"v\d+", i) for i in ids):
                nums = sorted(int(i[1:]) for i in ids)
                if nums and nums != list(range(1, max(nums) + 1)):
                    issues.append(
                        f"{cat_dir.name}/{t_dir.name}: version numbering has gaps: {ids}"
                    )
            # Explicit clauses map: anchors should resolve
            explicit = meta.get("clauses")
            if isinstance(explicit, list) and explicit:
                try:
                    f = resolve_version_file(t_dir, meta, None)
                    text = f.read_text()
                    for entry in explicit:
                        if entry.get("anchor") and entry["anchor"] not in text:
                            issues.append(
                                f"{cat_dir.name}/{t_dir.name}: explicit clause anchor not found: "
                                f"{entry.get('anchor')!r}"
                            )
                except (VaultError, OSError):
                    pass
            # clause_aliases keys must match a real detected clause title.
            aliases_map = meta.get("clause_aliases")
            if isinstance(aliases_map, dict) and aliases_map:
                try:
                    f = resolve_version_file(t_dir, meta, None)
                    text = f.read_text()
                    cs = detect_clauses(
                        text,
                        explicit_map=explicit if isinstance(explicit, list) else None,
                    )
                    detected_titles = {c["title"].lower() for c in cs}
                    for canonical in aliases_map:
                        if _norm_clause_key(canonical) not in detected_titles:
                            issues.append(
                                f"{cat_dir.name}/{t_dir.name}: clause_aliases key "
                                f"{canonical!r} doesn't match any detected clause title"
                            )
                except (VaultError, OSError):
                    pass

            # ---- Quality warnings (not failures by default) ----
            ref = f"{cat_dir.name}/{t_dir.name}"
            # Empty summary degrades `find` recall and weakens `ask`.
            if not (meta.get("summary") or "").strip():
                warnings.append(
                    f"{ref}: empty summary -- `find` and `ask` recall will be weaker. "
                    f"Add via `upload --amend --summary ...` or edit meta.json."
                )
            # Zero detected clauses + no explicit map = unusable for swap/upgrade.
            try:
                f = resolve_version_file(t_dir, meta, None)
                cs = detect_clauses(
                    f.read_text(),
                    explicit_map=explicit if isinstance(explicit, list) else None,
                )
                if not cs and not (isinstance(explicit, list) and explicit):
                    warnings.append(
                        f"{ref}: no clauses detected. Use H2 headings (`## Foo`), "
                        f"the bold/ALL-CAPS fallback, or supply an explicit "
                        f"`clauses` map in meta.json."
                    )
            except (VaultError, OSError):
                pass
            # Versions without recorded sha256 -- run `verify --update-hashes`.
            unhashed = sum(
                1 for v in (meta.get("versions") or [])
                if isinstance(v, dict) and not v.get("sha256")
            )
            if unhashed:
                warnings.append(
                    f"{ref}: {unhashed} version(s) without recorded sha256. "
                    f"Run `template-vault verify --update-hashes` to populate."
                )
            # Never used (no last_used + use_count is 0) -- graveyard candidate.
            if not meta.get("last_used") and not meta.get("use_count"):
                warnings.append(
                    f"{ref}: never used (use_count=0, last_used=null). "
                    f"Consider archiving if it's superseded."
                )

    print(f"Vault root:    {root}")
    print(f"Categories:    {len(seen_categories)} ({', '.join(seen_categories) or '-'})")
    print(f"Templates:     {seen_templates}")

    strict = bool(getattr(args, "strict", False))
    quiet_warnings = bool(getattr(args, "quiet_warnings", False))

    if not issues and (quiet_warnings or not warnings):
        print(_green("Status:") + "        OK")
        return 0
    if issues:
        print(f"{_red('Status:')}        {len(issues)} issue(s)"
              + (f", {len(warnings)} warning(s)" if (warnings and not quiet_warnings) else ""))
        for i in issues:
            print(f"  - {i}")
    else:
        # No hard issues but quality warnings exist.
        label = "Status:        OK"
        if not quiet_warnings:
            label += f"  ({len(warnings)} quality warning(s))"
        print(_green(label[:14]) + label[14:])
    if warnings and not quiet_warnings:
        print(_yellow("\nQuality warnings:"))
        for w in warnings:
            print(f"  - {w}")
    return 1 if issues or (strict and warnings) else 0


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


def _add_why_flag(p: argparse.ArgumentParser) -> None:
    p.add_argument("--why", action="store_true",
                   help="Print a short structured explanation of what this "
                        "command did (and didn't do). Useful for agents and "
                        "for debugging.")


def _add_llm_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--llm", help="LLM provider override (anthropic|openai)")
    p.add_argument("--llm-model", help="LLM model override")
    p.add_argument("--llm-base-url", help="LLM base URL override (for OpenAI-compatible endpoints)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="template-vault",
        description="Git-backed, clause-aware legal-document template manager.",
    )
    p.add_argument("--version", action="version", version=f"template-vault {__version__}")
    sub = p.add_subparsers(dest="cmd")

    p_init = sub.add_parser("init", help="Initialize a vault in the current dir")
    p_init.add_argument("--bare", action="store_true", help="git init --bare")
    p_init.add_argument("--path", help="Target path (default: cwd)")
    p_init.set_defaults(func=cmd_init)

    p_up = sub.add_parser("upload", help="Add a template version to the vault")
    p_up.add_argument("file")
    p_up.add_argument("--category", required=True)
    p_up.add_argument("--name", required=True)
    p_up.add_argument("--version", help="Explicit version id (default: auto v1, v2, ...)")
    p_up.add_argument("--supersedes", help="Prior version id this one replaces")
    p_up.add_argument("--summary")
    p_up.add_argument("--changelog")
    p_up.add_argument("--tags", help="Comma-separated tag list")
    p_up.add_argument("--jurisdiction", help="Comma-separated jurisdictions")
    p_up.add_argument("--party-type")
    p_up.add_argument("--deal-type")
    p_up.add_argument("--license")
    p_up.add_argument("--owner")
    p_up.add_argument("--uploaded-by")
    p_up.add_argument("--source")
    p_up.add_argument("--llm-summarize", action="store_true",
                      help="Opt-in: ask the LLM for a one-paragraph summary")
    p_up.add_argument("--non-interactive", action="store_true",
                      help="Suppress interactive prompts; fail if required fields missing")
    p_up.add_argument("--amend", metavar="VERSION",
                      help="Overwrite an existing version in place (destructive). "
                           "Records the prior content's SHA-256 in the version's "
                           "changelog. Use for typo fixes; bump a new version for "
                           "anything substantive.")
    p_up.add_argument("--yes-amend", action="store_true",
                      help="Skip the destructive-amend confirmation prompt")
    _add_llm_flags(p_up)
    p_up.set_defaults(func=cmd_upload)

    p_list = sub.add_parser("list", help="List templates")
    p_list.add_argument("--category")
    p_list.add_argument("--tag")
    p_list.add_argument("--jurisdiction")
    p_list.add_argument("--verbose", action="store_true",
                        help="Show summary + tags + jurisdiction on dedicated lines")
    p_list.add_argument("--json", action="store_true",
                        help="Emit a structured JSON payload (results[])")
    p_list.set_defaults(func=cmd_list)

    p_find = sub.add_parser("find", help="Keyword search across metadata")
    p_find.add_argument("query")
    p_find.add_argument("--top-k", type=int, default=10)
    p_find.add_argument("--json", action="store_true",
                        help="Emit a structured JSON payload (query, results[])")
    p_find.set_defaults(func=cmd_find)

    p_get = sub.add_parser("get", help="Print a template (or its path with --path-only)")
    p_get.add_argument("ref", help="category/name[@version]")
    p_get.add_argument("--path-only", action="store_true")
    p_get.set_defaults(func=cmd_get)

    p_info = sub.add_parser("info", help="Show metadata for a template")
    p_info.add_argument("ref")
    p_info.add_argument("--json", action="store_true",
                        help="Emit a structured JSON payload (meta + detected clauses + aliases)")
    p_info.set_defaults(func=cmd_info)

    p_diff = sub.add_parser("diff", help="Unified diff between two versions of one template")
    p_diff.add_argument("ref")
    p_diff.add_argument("version_a")
    p_diff.add_argument("version_b")
    p_diff.set_defaults(func=cmd_diff)

    p_hist = sub.add_parser("history", help="Chronological timeline: versions + swaps + amends")
    p_hist.add_argument("ref")
    p_hist.add_argument("--json", action="store_true",
                        help="Emit a structured JSON payload of the timeline")
    p_hist.set_defaults(func=cmd_history)

    p_clauses = sub.add_parser("clauses", help="List clauses detected in a template")
    p_clauses.add_argument("ref")
    p_clauses.set_defaults(func=cmd_clauses)

    p_compose = sub.add_parser("compose", help="Fork a template into a new derived one")
    _add_why_flag(p_compose)
    p_compose.add_argument("--base", required=True, help="category/name[@version]")
    p_compose.add_argument("--as", dest="as_ref", required=True,
                           help="category/new-name for the derived template")
    p_compose.set_defaults(func=cmd_compose)

    p_swap = sub.add_parser("swap", help="Replace one clause from another template")
    _add_why_flag(p_swap)
    p_swap.add_argument("target", help="category/name (the template to mutate)")
    p_swap.add_argument("--clause", required=True, help="Clause title (case-insensitive)")
    p_swap.add_argument("--from", dest="from_ref", required=True,
                        help="category/name[@version] (source of the clause)")
    p_swap.set_defaults(func=cmd_swap)

    p_cmp = sub.add_parser("compare-clauses", help="Compare clauses between two templates")
    p_cmp.add_argument("a")
    p_cmp.add_argument("b")
    p_cmp.add_argument("--clause", help="If set, diff only this clause")
    p_cmp.set_defaults(func=cmd_compare_clauses)

    p_up2 = sub.add_parser("upgrade", help="Pull parent-template changes into a derived template")
    _add_why_flag(p_up2)
    p_up2.add_argument("ref")
    p_up2.add_argument("--accept-all", action="store_true")
    p_up2.add_argument("--dry-run", action="store_true",
                       help="Show what would change without writing a new version")
    p_up2.add_argument("--interactive-explain", action="store_true",
                       help="Adds '?' as a third option at the per-clause prompt; "
                            "typing it sends the diff to the configured LLM and "
                            "prints a one-paragraph plain-English explanation. "
                            "Opt-in only — sends template content off-device.")
    _add_llm_flags(p_up2)
    p_up2.set_defaults(func=cmd_upgrade)

    p_lib = sub.add_parser("clause-library", help="Find repeated clauses across the vault")
    p_lib.add_argument("--threshold", type=float, default=0.85)
    p_lib.add_argument("--extract", action="store_true",
                       help="Prompt to extract clusters into clauses/<category>/<slug>.md")
    p_lib.add_argument("--yes-extract-all", action="store_true",
                       help="With --extract, write every cluster without prompting")
    p_lib.add_argument("--suggest-aliases", action="store_true",
                       help="After clustering, suggest clause_aliases for "
                            "clauses with similar bodies but different titles "
                            "that aren't already aliased.")
    p_lib.set_defaults(func=cmd_clause_library)

    p_ask = sub.add_parser("ask", help="LLM-conversational template recommendation")
    p_ask.add_argument("query")
    p_ask.add_argument("--with-content", action="store_true",
                       help="Opt-in: include short template excerpts in the prompt")
    p_ask.add_argument("--top-k", type=int, default=5)
    p_ask.add_argument("--yes-send", action="store_true",
                       help="Skip the --with-content confirmation prompt")
    p_ask.add_argument("--json", action="store_true",
                       help="Also print a JSON blob of {query, candidates, answer}")
    p_ask.add_argument("--quiet", action="store_true",
                       help="With --json, suppress the human-readable answer "
                            "(stdout becomes JSON only)")
    p_ask.add_argument("--execute", action="store_true",
                       help="Parse the LLM response for `template-vault compose` / "
                            "`swap` lines and run them. Other subcommands are skipped.")
    p_ask.add_argument("--yes-execute", action="store_true",
                       help="Skip the run-confirmation prompt for --execute")
    _add_llm_flags(p_ask)
    p_ask.set_defaults(func=cmd_ask)

    p_imp = sub.add_parser("import", help="Import a template from a configured public source")
    _add_why_flag(p_imp)
    p_imp.add_argument("source_id")
    p_imp.add_argument("--no-verify", action="store_true",
                       help="Skip hash verification (not recommended)")
    p_imp.add_argument("--pin-hash", action="store_true",
                       help="Record the observed hash in vault config for next run")
    p_imp.add_argument("--sources", metavar="PATH",
                       help=f"Path to a custom sources registry JSON. Overrides the "
                            f"bundled registry. Also settable via {SOURCES_ENV}.")
    p_imp.set_defaults(func=cmd_import)

    p_src = sub.add_parser("sources", help="List bundled public-source registry entries")
    p_src.add_argument("--sources", metavar="PATH",
                       help=f"Path to a custom sources registry JSON. Overrides the "
                            f"bundled registry. Also settable via {SOURCES_ENV}.")
    p_src.set_defaults(func=cmd_sources)

    p_sync = sub.add_parser("sync", help="git pull (thin wrapper)")
    p_sync.set_defaults(func=cmd_sync)
    p_pub = sub.add_parser("publish", help="git push (thin wrapper)")
    p_pub.set_defaults(func=cmd_publish)

    p_stats = sub.add_parser("stats", help="Vault dashboard: counts, coverage, last activity")
    p_stats.add_argument("--json", action="store_true",
                         help="Emit a structured JSON payload of vault statistics")
    p_stats.set_defaults(func=cmd_stats)

    p_doc = sub.add_parser("doctor", help="Vault integrity check + quality warnings")
    p_doc.add_argument("--strict", action="store_true",
                       help="Exit non-zero on quality warnings too (default: only on issues)")
    p_doc.add_argument("--quiet-warnings", action="store_true",
                       help="Suppress quality warnings; show only hard issues")
    p_doc.set_defaults(func=cmd_doctor)

    p_comp = sub.add_parser("completion", help="Emit a shell completion script (bash or zsh)")
    p_comp.add_argument("shell", choices=["bash", "zsh"], help="Target shell")
    p_comp.set_defaults(func=cmd_completion)

    p_exp = sub.add_parser("export", help="Export a template to another format (e.g. .docx)")
    p_exp.add_argument("ref")
    p_exp.add_argument("--as", dest="as_", default="docx",
                       help="Output format (currently only 'docx')")
    p_exp.add_argument("--output", help="Output path (default: <name>.docx in cwd)")
    _add_why_flag(p_exp)
    p_exp.set_defaults(func=cmd_export)

    p_ver = sub.add_parser("verify", help="Content-level sha256 integrity check")
    p_ver.add_argument("--update-hashes", action="store_true",
                       help="Populate missing sha256 entries on version objects "
                            "and save meta.json. Useful one-shot when adopting "
                            "verify on an existing vault.")
    p_ver.add_argument("--strict", action="store_true",
                       help="Treat missing sha256 records as failures (exit 1)")
    p_ver.set_defaults(func=cmd_verify)

    return p


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


_FIRST_RUN_HINT = (
    "template-vault — Git-backed, clause-aware legal-template manager.\n"
    "\n"
    "First-run hints:\n"
    "  template-vault init                         create a vault in the current dir\n"
    "  template-vault sources                      list bundled public-source IDs\n"
    "  template-vault import common-paper-mutual-nda     pull in your first template\n"
    "  template-vault upload my.md --category nda --name house-mutual\n"
    "\n"
    "See `template-vault --help` for all commands.\n"
)


def main(argv: Optional[List[str]] = None) -> int:
    # POSIX/C locale (default on some macOS CI runners) leaves stdout/stderr
    # in ASCII mode; printing any non-ASCII char raises UnicodeEncodeError.
    # Force UTF-8 so the CLI works regardless of LANG/LC_ALL.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    argv = sys.argv[1:] if argv is None else argv
    # Global --no-color flag: intercept before argparse so it works on every
    # subcommand without needing a parent-parser hookup. Sets the NO_COLOR
    # env var, which _color_enabled() already honors.
    if "--no-color" in argv:
        os.environ["NO_COLOR"] = "1"
        argv = [a for a in argv if a != "--no-color"]
    if not argv:
        sys.stdout.write(_FIRST_RUN_HINT)
        return 0
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        sys.stdout.write(_FIRST_RUN_HINT)
        return 0
    try:
        return args.func(args) or 0
    except VaultError as e:
        _eprint(_red("error:") + f" {e}")
        return 2
    except KeyboardInterrupt:
        _eprint("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
