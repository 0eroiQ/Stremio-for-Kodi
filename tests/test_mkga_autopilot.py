import importlib.util
import os
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "mkga-autopilot.py"
os.environ.setdefault("MKGA_LAB_AUTOPILOT_TOKEN", "test-token")

spec = importlib.util.spec_from_file_location("mkga_autopilot", SCRIPT)
autopilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(autopilot)


class MkgaAutopilotTests(unittest.TestCase):
    def test_extracts_bash_fence(self):
        answer = "Do this:\n\n```bash\nprintf 'ok' > /tmp/x\n```"
        self.assertEqual(autopilot._extract_command(answer), "printf 'ok' > /tmp/x")

    def test_extracts_command_tag(self):
        self.assertEqual(
            autopilot._extract_command("<command>python3 -m unittest</command>"),
            "python3 -m unittest",
        )

    def test_blocks_git_push_and_secret_reads(self):
        self.assertFalse(autopilot._safe_coder_command("git push origin main"))
        self.assertFalse(autopilot._safe_coder_command("echo $GITHUB_TOKEN"))
        self.assertFalse(autopilot._safe_coder_command("env | grep MKGA_LAB_"))

    def test_allows_repository_edits_and_tests(self):
        self.assertTrue(
            autopilot._safe_coder_command(
                "python3 - <<'PY'\nfrom pathlib import Path\nPath('x.txt').write_text('ok')\nPY"
            )
        )
        self.assertTrue(autopilot._safe_coder_command("python3 -m unittest discover -s tests"))

    def test_repo_context_prioritizes_current_repository_tooling(self):
        context = autopilot.repo_context(
            "Kodi repository update notifications not appearing; investigate repository publishing."
        )
        likely = context.split("MATCHES:", 1)[0]
        self.assertIn(".github/workflows/repository.yml", likely)
        self.assertIn("tests/test_kodi_repository.py", likely)
        self.assertIn("tools/build-kodi-repository.py", likely)
        self.assertIn("--- .github/workflows/repository.yml ---", context)
        self.assertNotIn(".github/workflows/release-v1.0.34.yml:", context.split("FILE SNIPPETS:", 1)[0])
        self.assertLess(len(context), 18000)

    def test_extracts_and_bounds_patch(self):
        answer = """```diff
diff --git a/tests/example.py b/tests/example.py
--- a/tests/example.py
+++ b/tests/example.py
@@ -1 +1 @@
-old
+new
```"""
        patch = autopilot._extract_patch(answer)
        self.assertIn("diff --git", patch)
        self.assertTrue(autopilot._safe_patch_paths(patch))
        blocked = patch.replace("tests/example.py", "tools/mkga-autopilot.py")
        self.assertFalse(autopilot._safe_patch_paths(blocked))


if __name__ == "__main__":
    unittest.main()
