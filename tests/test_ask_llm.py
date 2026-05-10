"""ask command — LLM request shape, privacy gating."""

import json
import os
import unittest
from unittest import mock

from tests._helpers import (
    CliCase, add_template, run_cli, temp_vault, tvc,
    SAMPLE_NDA_MUTUAL, SAMPLE_NDA_STARTUP_FRIENDLY, SAMPLE_LICENSING,
)


class _AskHarness:
    """Captures the user message sent to the LLM, returns a canned response."""

    def __init__(self, response: str = "use nda/house-mutual"):
        self.calls = []
        self.response = response

    def __call__(self, cfg, system, user, timeout=60):
        self.calls.append({"cfg": cfg, "system": system, "user": user})
        return self.response


def _seed_vault(v):
    add_template(v, "nda", "house-mutual", SAMPLE_NDA_MUTUAL,
                 jurisdiction=["California"], tags=["mutual"],
                 summary="house-style mutual NDA, default for US deals")
    add_template(v, "nda", "yc-friendly", SAMPLE_NDA_STARTUP_FRIENDLY,
                 jurisdiction=["Delaware"], tags=["yc"],
                 summary="YC-flavor short NDA, startup-friendly")
    add_template(v, "licensing", "saas", SAMPLE_LICENSING,
                 tags=["saas"], summary="SaaS licensing, enterprise terms")


class AskMetadataOnlyTests(CliCase):
    def test_default_sends_metadata_only_no_excerpts(self):
        with temp_vault() as v:
            _seed_vault(v)
            harness = _AskHarness("use nda/house-mutual")
            with mock.patch.dict(os.environ, {"NDA_VAULT_LLM_API_KEY": "k"}), \
                 mock.patch.object(tvc, "_llm_request", harness):
                code, _out, _err = run_cli("ask", "which mutual NDA for california?")
                self.assertEqual(code, 0)
            user_msg = harness.calls[0]["user"]
            # Must not contain template body content
            self.assertNotIn("two years after the last disclosure", user_msg)
            self.assertNotIn("Limited to the evaluation period", user_msg)
            self.assertNotIn("excerpt(500)", user_msg)
            # But metadata fields ARE present
            self.assertIn("jurisdiction:", user_msg)
            self.assertIn("clauses:", user_msg)
            self.assertIn("California", user_msg)


class AskWithContentTests(CliCase):
    def test_with_content_includes_excerpts(self):
        with temp_vault() as v:
            _seed_vault(v)
            harness = _AskHarness()
            with mock.patch.dict(os.environ, {
                "NDA_VAULT_LLM_API_KEY": "k",
                tvc.NO_CONFIRM_ENV: "1",
            }), mock.patch.object(tvc, "_llm_request", harness):
                code, _out, _err = run_cli("ask", "term and survival options",
                                           "--with-content")
                self.assertEqual(code, 0)
            self.assertIn("excerpt(500)", harness.calls[0]["user"])

    def test_with_content_refused_in_non_interactive_without_consent(self):
        with temp_vault() as v:
            _seed_vault(v)
            harness = _AskHarness()
            # No NDA_VAULT_NO_CONFIRM, no --yes-send. stdin is not a tty in tests.
            with mock.patch.dict(os.environ, {"NDA_VAULT_LLM_API_KEY": "k"},
                                 clear=False), \
                 mock.patch.object(tvc, "_llm_request", harness):
                # Ensure NO_CONFIRM not present
                os.environ.pop(tvc.NO_CONFIRM_ENV, None)
                code, _out, err = run_cli("ask", "x", "--with-content")
                self.assertNotEqual(code, 0)
                self.assertIn("non-interactive", err.lower())
            self.assertEqual(harness.calls, [])

    def test_yes_send_bypasses_confirmation(self):
        with temp_vault() as v:
            _seed_vault(v)
            harness = _AskHarness()
            os.environ.pop(tvc.NO_CONFIRM_ENV, None)
            with mock.patch.dict(os.environ, {"NDA_VAULT_LLM_API_KEY": "k"},
                                 clear=False), \
                 mock.patch.object(tvc, "_llm_request", harness):
                code, _out, _err = run_cli(
                    "ask", "x", "--with-content", "--yes-send")
                self.assertEqual(code, 0)


class AskMissingApiKeyTests(CliCase):
    def test_friendly_error_when_no_api_key(self):
        with temp_vault() as v:
            _seed_vault(v)
            # Clear all LLM env vars and patch config loaders to return empty
            env_clear = {k: "" for k in os.environ if k.startswith(tvc.LLM_ENV_PREFIX)}
            with mock.patch.dict(os.environ, env_clear, clear=False), \
                 mock.patch.object(tvc, "_load_llm_config", return_value={}):
                # remove the env entirely
                for k in list(os.environ):
                    if k.startswith(tvc.LLM_ENV_PREFIX):
                        del os.environ[k]
                code, _out, err = run_cli("ask", "anything")
                self.assertNotEqual(code, 0)
                self.assertIn("API key", err)


class AskClauseAwareCompositionTests(CliCase):
    def test_ask_can_emit_swap_recommendation_text(self):
        """The LLM emits a literal command string the user copies (or runs via
        --execute). Verify the system prompt instructs the model to reference
        only listed templates."""
        with temp_vault() as v:
            _seed_vault(v)
            harness = _AskHarness(
                "Run:\n  template-vault swap nda/house-mutual "
                "--clause 'Term and Survival' --from nda/yc-friendly"
            )
            with mock.patch.dict(os.environ, {
                "NDA_VAULT_LLM_API_KEY": "k",
            }), mock.patch.object(tvc, "_llm_request", harness):
                code, out, _err = run_cli(
                    "ask", "compose a startup-friendly mutual NDA with YC term clause")
                self.assertEqual(code, 0)
            self.assertIn("template-vault swap", out)
            sys_prompt = harness.calls[0]["system"]
            self.assertIn("Do NOT invent templates", sys_prompt)


class CommandParseTests(unittest.TestCase):
    def test_parses_plain_lines(self):
        text = (
            "Here's the plan:\n"
            "  template-vault compose --base nda/a --as nda/b\n"
            "  template-vault swap nda/b --clause \"Term and Survival\" --from nda/c\n"
        )
        cmds, skipped = tvc._parse_executable_commands(text)
        self.assertEqual(len(cmds), 2)
        self.assertEqual(cmds[0][0], "compose")
        self.assertEqual(cmds[1][0], "swap")
        self.assertEqual(cmds[1][3], "Term and Survival")
        self.assertEqual(skipped, [])

    def test_strips_shell_prompts_and_fences(self):
        text = (
            "```bash\n"
            "$ template-vault compose --base nda/a --as nda/b\n"
            "> template-vault swap nda/b --clause Foo --from nda/c\n"
            "```\n"
        )
        cmds, _ = tvc._parse_executable_commands(text)
        self.assertEqual(len(cmds), 2)

    def test_skips_disallowed_subcommands(self):
        text = (
            "template-vault upload x.md --category nda --name x --summary s\n"
            "template-vault import common-paper-mutual-nda\n"
            "template-vault compose --base nda/a --as nda/b\n"
        )
        cmds, skipped = tvc._parse_executable_commands(text)
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0][0], "compose")
        self.assertEqual(len(skipped), 2)
        self.assertTrue(any("upload" in s for s in skipped))
        self.assertTrue(any("import" in s for s in skipped))

    def test_no_commands_returns_empty(self):
        cmds, skipped = tvc._parse_executable_commands("Just prose, no commands.")
        self.assertEqual(cmds, [])
        self.assertEqual(skipped, [])


class AskExecuteTests(CliCase):
    def test_execute_runs_compose_and_swap(self):
        with temp_vault() as v:
            _seed_vault(v)
            harness = _AskHarness(
                "Recommendation:\n"
                "  template-vault compose --base nda/house-mutual "
                "--as nda/house-mutual-startup\n"
                "  template-vault swap nda/house-mutual-startup "
                "--clause \"Term and Survival\" --from nda/yc-friendly\n"
            )
            with mock.patch.dict(os.environ, {"NDA_VAULT_LLM_API_KEY": "k"}), \
                 mock.patch.object(tvc, "_llm_request", harness):
                code, _out, _err = run_cli(
                    "ask", "make me a startup-friendly mutual NDA",
                    "--execute", "--yes-execute",
                )
                self.assertEqual(code, 0)
            # compose result on disk
            derived = v / "nda" / "house-mutual-startup"
            self.assertTrue(derived.exists())
            # swap result: clause_overrides recorded
            import json as _json
            meta = _json.loads((derived / "meta.json").read_text())
            self.assertEqual(len(meta["clause_overrides"]), 1)
            self.assertEqual(meta["clause_overrides"][0]["clause_title"],
                             "Term and Survival")

    def test_execute_non_interactive_without_yes_refuses(self):
        with temp_vault() as v:
            _seed_vault(v)
            harness = _AskHarness(
                "  template-vault compose --base nda/house-mutual "
                "--as nda/x"
            )
            with mock.patch.dict(os.environ, {"NDA_VAULT_LLM_API_KEY": "k"}), \
                 mock.patch.object(tvc, "_llm_request", harness):
                code, _out, err = run_cli(
                    "ask", "x", "--execute")
                self.assertNotEqual(code, 0)
                self.assertIn("non-interactive", err.lower())
            # nothing was written
            self.assertFalse((v / "nda" / "x").exists())

    def test_execute_with_no_commands_in_response(self):
        with temp_vault() as v:
            _seed_vault(v)
            harness = _AskHarness("I recommend nda/house-mutual. No swap needed.")
            with mock.patch.dict(os.environ, {"NDA_VAULT_LLM_API_KEY": "k"}), \
                 mock.patch.object(tvc, "_llm_request", harness):
                code, _out, err = run_cli(
                    "ask", "x", "--execute", "--yes-execute")
                self.assertEqual(code, 0)
                self.assertIn("no compose/swap commands", err.lower())

    def test_execute_stops_chain_on_failure(self):
        with temp_vault() as v:
            _seed_vault(v)
            # Second command targets a nonexistent clause → swap fails
            harness = _AskHarness(
                "  template-vault compose --base nda/house-mutual "
                "--as nda/will-exist\n"
                "  template-vault swap nda/will-exist "
                "--clause \"NoSuchClause\" --from nda/yc-friendly\n"
                "  template-vault compose --base nda/house-mutual "
                "--as nda/should-not-exist\n"
            )
            with mock.patch.dict(os.environ, {"NDA_VAULT_LLM_API_KEY": "k"}), \
                 mock.patch.object(tvc, "_llm_request", harness):
                code, _out, err = run_cli(
                    "ask", "x", "--execute", "--yes-execute")
                self.assertNotEqual(code, 0)
                self.assertIn("stopping the chain", err.lower())
            # First compose ran; third never did
            self.assertTrue((v / "nda" / "will-exist").exists())
            self.assertFalse((v / "nda" / "should-not-exist").exists())


if __name__ == "__main__":
    unittest.main()
