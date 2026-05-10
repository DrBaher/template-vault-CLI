"""Vault-level template_defaults and clause_aliases overlaid by load_meta_resolved."""

import json
import unittest

from tests._helpers import (
    CliCase, add_template, run_cli, temp_vault, tvc,
    SAMPLE_NDA_MUTUAL,
)


def _set_vault_cfg(vault, **fields):
    cfg = json.loads((vault / ".vault.json").read_text())
    cfg.update(fields)
    (vault / ".vault.json").write_text(json.dumps(cfg, indent=2) + "\n")


class TemplateDefaultsTests(CliCase):
    def test_vault_default_license_fills_missing_per_template(self):
        with temp_vault() as v:
            _set_vault_cfg(v, template_defaults={"license": "internal-only",
                                                  "owner": "legal-team"})
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            # Scrub per-template license/owner so the vault default surfaces.
            mp = v / "nda" / "x" / "meta.json"
            meta = json.loads(mp.read_text())
            meta["license"] = "private"  # original default
            meta["owner"] = None
            mp.write_text(json.dumps(meta, indent=2) + "\n")
            # info shows the per-template "private" because that key is set.
            code, out, _err = run_cli("info", "nda/x")
            self.assertEqual(code, 0)
            # owner was None → vault default fills it.
            self.assertIn("legal-team", out)

    def test_per_template_value_wins_over_vault_default(self):
        with temp_vault() as v:
            _set_vault_cfg(v, template_defaults={"owner": "vault-default-owner"})
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            mp = v / "nda" / "x" / "meta.json"
            meta = json.loads(mp.read_text())
            meta["owner"] = "per-template-owner"
            mp.write_text(json.dumps(meta, indent=2) + "\n")
            code, out, _err = run_cli("info", "nda/x")
            self.assertEqual(code, 0)
            self.assertIn("per-template-owner", out)
            self.assertNotIn("vault-default-owner", out)

    def test_save_meta_does_not_persist_overlaid_values(self):
        # If a mutating command (e.g. swap) round-trips through load_meta /
        # save_meta, the overlaid vault defaults must NOT be written back into
        # the per-template file.
        with temp_vault() as v:
            _set_vault_cfg(v, template_defaults={"owner": "vault-default-owner"})
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            mp = v / "nda" / "x" / "meta.json"
            meta = json.loads(mp.read_text())
            meta["owner"] = None
            mp.write_text(json.dumps(meta, indent=2) + "\n")
            # Mutating round-trip via raw load_meta + save_meta:
            raw = tvc.load_meta(v / "nda" / "x")
            tvc.save_meta(v / "nda" / "x", raw)
            after = json.loads(mp.read_text())
            self.assertIsNone(after["owner"])  # NOT 'vault-default-owner'


class VaultLevelClauseAliasesTests(CliCase):
    def test_vault_aliases_resolve_in_swap(self):
        with temp_vault() as v:
            _set_vault_cfg(v, clause_aliases={
                "Term and Survival": ["Termination", "Duration"],
            })
            add_template(v, "nda", "house", SAMPLE_NDA_MUTUAL)
            add_template(v, "nda", "yc",
                         "## Purpose\np\n## Term and Survival\nOne year.\n")
            run_cli("compose", "--base", "nda/house",
                    "--as", "nda/house-startup")
            # Use the alias name; vault-level aliases apply to both source
            # and target lookups.
            code, _out, _err = run_cli(
                "swap", "nda/house-startup",
                "--clause", "Termination",
                "--from", "nda/yc",
            )
            self.assertEqual(code, 0)
            after = (v / "nda" / "house-startup" / "v1.md").read_text()
            self.assertIn("One year.", after)

    def test_per_template_aliases_union_with_vault(self):
        with temp_vault() as v:
            _set_vault_cfg(v, clause_aliases={
                "Term and Survival": ["Termination"],
            })
            add_template(v, "nda", "house", SAMPLE_NDA_MUTUAL)
            mp = v / "nda" / "house" / "meta.json"
            meta = json.loads(mp.read_text())
            meta["clause_aliases"] = {
                "Term and Survival": ["Duration"],
            }
            mp.write_text(json.dumps(meta, indent=2) + "\n")
            # Both aliases must work for cmd_clauses output (resolved).
            code, out, _err = run_cli("clauses", "nda/house")
            self.assertEqual(code, 0)
            # Term and Survival's aliases should include both Termination
            # (from vault) and Duration (from per-template).
            self.assertIn("termination", out.lower())
            self.assertIn("duration", out.lower())


if __name__ == "__main__":
    unittest.main()
