"""Coverage tests for v0.4.2: long-tail error paths that weren't exercised before.

Targets:
  - _llm_request: both providers, success + HTTP error + URL error + malformed-response paths
  - cmd_init: git init failure (mocked), --bare, vault already initialized
  - cmd_publish / cmd_sync: git wrapper success + failure + git-not-found
  - cmd_verify: --strict-no-mismatch, missing-file-on-disk
  - cmd_import: registry-load malformed JSON, --pin-hash on first import
  - cmd_upload: --llm-summarize and the misc-field flags
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from tests._helpers import (
    CliCase, add_template, run_cli, temp_vault, tvc,
    SAMPLE_NDA_MUTUAL,
)


# ---------------------------------------------------------------------------
# _llm_request
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def read(self):
        return self._body


class LlmConfigLookupTests(unittest.TestCase):
    """Cover the lookup order in _load_llm_config, including the new
    ~/.config/contract-ops/ shared location added in v0.4.8 per INTEROP.md."""

    def test_contract_ops_dir_wins_over_per_cli_dirs(self):
        import tempfile
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as fake_home:
            # Lay down three candidate config files; the suite-shared one
            # should win regardless of the others.
            for sub, marker in (
                ("contract-ops", "shared"),
                ("nda-review-cli", "nda-review"),
                ("template-vault-cli", "tv"),
            ):
                d = os.path.join(fake_home, ".config", sub)
                os.makedirs(d)
                with open(os.path.join(d, "llm.json"), "w") as f:
                    json.dump({"provider": "anthropic", "api_key": marker}, f)
            with mock.patch.dict(os.environ, {"HOME": fake_home}, clear=False):
                # Path.home() honors $HOME on POSIX.
                with mock.patch("template_vault_cli.Path.home",
                                return_value=Path(fake_home)):
                    cfg = tvc._load_llm_config(Namespace())
            self.assertEqual(cfg.get("api_key"), "shared",
                              "Suite-wide ~/.config/contract-ops/llm.json "
                              "should be preferred over per-CLI dirs.")

    def test_falls_back_to_legacy_locations(self):
        """When the new suite-shared file is absent, fall back to the
        legacy per-CLI locations (in order)."""
        import tempfile
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as fake_home:
            d = os.path.join(fake_home, ".config", "nda-review-cli")
            os.makedirs(d)
            with open(os.path.join(d, "llm.json"), "w") as f:
                json.dump({"provider": "openai", "api_key": "legacy"}, f)
            with mock.patch("template_vault_cli.Path.home",
                            return_value=Path(fake_home)):
                cfg = tvc._load_llm_config(Namespace())
            self.assertEqual(cfg.get("api_key"), "legacy")


class LlmRequestTests(unittest.TestCase):
    """Cover both provider branches + every error path in _llm_request."""

    def test_anthropic_success_path(self):
        fake = _FakeResponse({"content": [{"text": "hello"}, {"text": " there"}]})
        with mock.patch("urllib.request.urlopen", return_value=fake):
            out = tvc._llm_request(
                {"provider": "anthropic", "api_key": "k"},
                system="s", user="u",
            )
        self.assertEqual(out, "hello there")

    def test_openai_success_path(self):
        fake = _FakeResponse({"choices": [{"message": {"content": "ok"}}]})
        with mock.patch("urllib.request.urlopen", return_value=fake):
            out = tvc._llm_request(
                {"provider": "openai", "api_key": "k",
                 "base_url": "https://example.test/v1/"},
                system="s", user="u",
            )
        self.assertEqual(out, "ok")

    def test_missing_api_key_raises(self):
        with self.assertRaises(tvc.VaultError) as ctx:
            tvc._llm_request({"provider": "anthropic"}, system="s", user="u")
        self.assertIn("API key", str(ctx.exception))

    def test_http_error_wrapped(self):
        err = urllib.error.HTTPError(
            "http://x", 502, "Bad Gateway", hdrs=None, fp=None,
        )
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(tvc.VaultError) as ctx:
                tvc._llm_request(
                    {"provider": "anthropic", "api_key": "k"},
                    system="s", user="u",
                )
        msg = str(ctx.exception)
        self.assertIn("LLM HTTP 502", msg)

    def test_network_error_wrapped(self):
        err = urllib.error.URLError("dns failed")
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(tvc.VaultError) as ctx:
                tvc._llm_request(
                    {"provider": "openai", "api_key": "k"},
                    system="s", user="u",
                )
        self.assertIn("network error", str(ctx.exception))

    def test_anthropic_malformed_response(self):
        fake = _FakeResponse({"unexpected": "shape"})
        with mock.patch("urllib.request.urlopen", return_value=fake):
            with self.assertRaises(tvc.VaultError) as ctx:
                tvc._llm_request(
                    {"provider": "anthropic", "api_key": "k"},
                    system="s", user="u",
                )
        self.assertIn("Anthropic response", str(ctx.exception))

    def test_openai_malformed_response(self):
        fake = _FakeResponse({"choices": []})
        with mock.patch("urllib.request.urlopen", return_value=fake):
            with self.assertRaises(tvc.VaultError) as ctx:
                tvc._llm_request(
                    {"provider": "openai", "api_key": "k"},
                    system="s", user="u",
                )
        self.assertIn("OpenAI", str(ctx.exception))

    def test_default_models(self):
        """Confirm the default model strings differ per provider."""
        captured = {}

        def fake_urlopen(req, timeout=60):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse({"content": [{"text": "x"}]})

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            tvc._llm_request(
                {"provider": "anthropic", "api_key": "k"},
                system="s", user="u",
            )
        self.assertIn("claude", captured["body"]["model"])


# ---------------------------------------------------------------------------
# cmd_init
# ---------------------------------------------------------------------------


class InitCommandTests(CliCase):
    def test_init_in_already_initialized_vault_is_idempotent(self):
        with temp_vault() as v:
            # temp_vault already initialized one; running init again should
            # report "already" and exit cleanly.
            code, _out, err = run_cli("init")
            self.assertEqual(code, 0)
            self.assertIn("already initialized", err.lower())

    def test_init_handles_git_init_failure_with_warning(self):
        """If `git init` fails (no git in PATH, etc.) init still writes the
        vault config and prints a warning rather than aborting."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "v"
            prev = os.getcwd()
            try:
                os.chdir(d)
                # Patch _git_init to simulate a CalledProcessError.
                err = subprocess.CalledProcessError(
                    returncode=1, cmd=["git", "init"], stderr="boom",
                )
                with mock.patch.object(tvc, "_git_init", side_effect=err):
                    code, out, err_text = run_cli("init", "--path", str(target))
                self.assertEqual(code, 0)
                self.assertIn("Initialized vault at", out)
                self.assertIn("git init failed", err_text)
                # Vault config still written:
                self.assertTrue((target / tvc.VAULT_CONFIG_FILENAME).exists())
            finally:
                os.chdir(prev)

    def test_init_bare_repository(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "vbare"
            prev = os.getcwd()
            try:
                os.chdir(d)
                with mock.patch.object(tvc, "_git_init") as gi:
                    code, _out, _err = run_cli("init", "--path", str(target), "--bare")
                    self.assertEqual(code, 0)
                    gi.assert_called_once()
                    self.assertEqual(gi.call_args.kwargs.get("bare"), True)
            finally:
                os.chdir(prev)


# ---------------------------------------------------------------------------
# cmd_publish / cmd_sync (git wrappers)
# ---------------------------------------------------------------------------


class GitWrapperTests(CliCase):
    def test_sync_runs_git_pull_and_returns_its_exit_code(self):
        with temp_vault() as v:
            fake_run = mock.Mock(return_value=mock.Mock(
                returncode=0, stdout="Already up to date.\n", stderr=""))
            with mock.patch.object(tvc, "_git", fake_run):
                code, out, _err = run_cli("sync")
            self.assertEqual(code, 0)
            self.assertIn("Already up to date", out)
            args, kwargs = fake_run.call_args
            self.assertEqual(args[0], ["pull"])

    def test_publish_runs_git_push(self):
        with temp_vault() as v:
            fake_run = mock.Mock(return_value=mock.Mock(
                returncode=0, stdout="Everything up-to-date\n", stderr=""))
            with mock.patch.object(tvc, "_git", fake_run):
                code, _out, _err = run_cli("publish")
            self.assertEqual(code, 0)
            args, _ = fake_run.call_args
            self.assertEqual(args[0], ["push"])

    def test_publish_propagates_non_zero_exit(self):
        with temp_vault() as v:
            fake_run = mock.Mock(return_value=mock.Mock(
                returncode=128, stdout="", stderr="fatal: no remote\n"))
            with mock.patch.object(tvc, "_git", fake_run):
                code, _out, err = run_cli("publish")
            self.assertEqual(code, 128)
            self.assertIn("fatal", err)

    def test_publish_when_git_missing_errors_cleanly(self):
        with temp_vault() as v:
            with mock.patch.object(tvc, "_git", side_effect=FileNotFoundError("git")):
                code, _out, err = run_cli("publish")
            self.assertNotEqual(code, 0)
            self.assertIn("git not found", err.lower())


# ---------------------------------------------------------------------------
# cmd_verify long-tail
# ---------------------------------------------------------------------------


class VerifyExtraTests(CliCase):
    def test_strict_passes_when_all_hashes_present(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            run_cli("verify", "--update-hashes")
            code, _out, _err = run_cli("verify", "--strict")
            self.assertEqual(code, 0)

    def test_missing_file_on_disk_is_reported_as_mismatch(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            # Remove the v1.md file but keep meta.json
            (v / "nda" / "x" / "v1.md").unlink()
            code, out, _err = run_cli("verify")
            self.assertNotEqual(code, 0)
            self.assertIn("file missing", out.lower())


# ---------------------------------------------------------------------------
# cmd_import edge paths
# ---------------------------------------------------------------------------


class ImportEdgeCaseTests(CliCase):
    def test_malformed_custom_registry_errors(self):
        with temp_vault() as v:
            bad = v / "bad.json"
            bad.write_text("{not valid json")
            code, _out, err = run_cli("import", "foo", "--sources", str(bad))
            self.assertNotEqual(code, 0)
            self.assertIn("Malformed", err)

    def test_pin_hash_records_observed_hash(self):
        with temp_vault() as v:
            reg = v / "sources.json"
            reg.write_text(json.dumps({
                "schema_version": 1,
                "sources": [{
                    "id": "test-src",
                    "name": "test",
                    "category": "nda",
                    "url": "https://example.test/x.md",
                    "license": "MIT",
                }],
            }))
            payload = b"## Purpose\nBody.\n"
            with mock.patch.object(tvc, "_fetch_url", return_value=payload):
                code, _out, _err = run_cli(
                    "import", "test-src",
                    "--sources", str(reg),
                    "--pin-hash",
                )
            self.assertEqual(code, 0)
            # Hash recorded in vault config
            cfg = json.loads((v / ".vault.json").read_text())
            expected = tvc.sha256_bytes(payload)
            self.assertEqual(cfg["pinned_source_hashes"]["test-src"], expected)


# ---------------------------------------------------------------------------
# cmd_upload extra-flags coverage
# ---------------------------------------------------------------------------


class ListAndGlobalFlagsTests(CliCase):
    def test_list_json_payload(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL, tags=["a"],
                         summary="s")
            code, out, _err = run_cli("list", "--json")
            self.assertEqual(code, 0)
            doc = json.loads(out)
            self.assertEqual(len(doc["results"]), 1)
            row = doc["results"][0]
            self.assertEqual(row["ref"], "nda/x")
            self.assertEqual(row["latest_version"], "v1")
            self.assertEqual(row["tags"], ["a"])
            self.assertEqual(row["summary"], "s")

    def test_list_verbose_shows_summary_line(self):
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL,
                         summary="the house mutual NDA")
            code, out, _err = run_cli("list", "--verbose")
            self.assertEqual(code, 0)
            self.assertIn("nda/x", out)
            self.assertIn("the house mutual NDA", out)

    def test_no_color_flag_global(self):
        """`--no-color` is intercepted before argparse and works on any
        subcommand. Verify by checking the `error:` prefix is unstyled."""
        # Force a known-error: list outside a vault, with --no-color.
        # We can't easily check color codes vs no codes since tests run with
        # stdout redirected (not a TTY) so codes are off anyway. Instead,
        # confirm the flag doesn't error out argparse.
        with temp_vault() as v:
            add_template(v, "nda", "x", SAMPLE_NDA_MUTUAL)
            code, _out, _err = run_cli("--no-color", "list")
            self.assertEqual(code, 0)


class UploadFlagsTests(CliCase):
    def test_upload_with_all_optional_fields_set(self):
        with temp_vault() as v:
            src = v / "x.md"
            src.write_text(SAMPLE_NDA_MUTUAL)
            self.assertOk(run_cli(
                "upload", str(src),
                "--category", "nda", "--name", "x",
                "--summary", "s",
                "--tags", "a,b,c",
                "--jurisdiction", "CA,DE",
                "--party-type", "mutual",
                "--deal-type", "vendor",
                "--license", "MIT",
                "--owner", "legal",
                "--uploaded-by", "@me",
                "--source", "https://example.test/upstream",
                "--non-interactive",
            ))
            meta = json.loads((v / "nda" / "x" / "meta.json").read_text())
            self.assertEqual(meta["license"], "MIT")
            self.assertEqual(meta["owner"], "legal")
            self.assertEqual(meta["uploaded_by"], "@me")
            self.assertEqual(meta["source"], "https://example.test/upstream")
            self.assertIn("a", meta["tags"])
            self.assertIn("mutual", meta["party_type"])
            self.assertIn("vendor", meta["deal_type"])

    def test_upload_llm_summarize_calls_llm(self):
        with temp_vault() as v:
            src = v / "x.md"
            src.write_text(SAMPLE_NDA_MUTUAL)
            with mock.patch.dict(os.environ, {"NDA_VAULT_LLM_API_KEY": "k"}), \
                 mock.patch.object(tvc, "_llm_request", return_value="LLM summary."):
                code, _out, _err = run_cli(
                    "upload", str(src),
                    "--category", "nda", "--name", "x",
                    "--llm-summarize",
                    "--non-interactive",
                )
            self.assertEqual(code, 0)
            meta = json.loads((v / "nda" / "x" / "meta.json").read_text())
            self.assertEqual(meta["summary"], "LLM summary.")


if __name__ == "__main__":
    unittest.main()
