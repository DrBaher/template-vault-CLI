import json
import subprocess
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "template_vault_cli.py"


class CatalogTests(unittest.TestCase):
    def test_catalog_json(self):
        res = subprocess.run(
            ["python3", str(CLI), "--catalog", "json"],
            cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self.assertEqual(res.returncode, 0)
        d = json.loads(res.stdout)
        self.assertEqual(d["name"], "template-vault-cli")
        self.assertEqual(d["bin"], "template-vault")
        names = {c["name"] for c in d["commands"]}
        for expected in ("demo", "init", "upload", "list", "find", "get",
                         "info", "compose", "swap", "ask"):
            self.assertIn(expected, names)
        # Flags are structured (name + the rest of the contract).
        find = next(c for c in d["commands"] if c["name"] == "find")
        self.assertTrue(any(f["name"] == "--json" for f in find["flags"]))


if __name__ == "__main__":
    unittest.main()
