"""CI dependency refresh keeps one commit and refuses unrelated or dirty trees."""

import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("ci-clone.sh").resolve()


class CloneTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.destination = self.root / "checkout"
        self.git("init", "-b", "main", str(self.source))
        self.git("-C", str(self.source), "config", "user.name", "CI fixture")
        self.git("-C", str(self.source), "config", "user.email", "ci@example.invalid")
        self.git("-C", str(self.source), "config", "commit.gpgsign", "false")
        self.commit("first")

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-c", "core.hooksPath=/dev/null", *args],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()

    def commit(self, text):
        (self.source / "fixture.txt").write_text(text)
        self.git("-C", str(self.source), "add", "fixture.txt")
        self.git("-C", str(self.source), "commit", "-m", text)

    def refresh(self, url=None):
        return subprocess.run(
            ["bash", str(SCRIPT), url or self.source.as_uri(), str(self.destination)],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_refresh_tracks_remote_head_with_one_commit(self):
        self.assertEqual(self.refresh().returncode, 0)
        self.commit("second")
        self.assertEqual(self.refresh().returncode, 0)
        self.assertEqual((self.destination / "fixture.txt").read_text(), "second")
        self.assertEqual(
            self.git("-C", str(self.destination), "rev-list", "--count", "HEAD"), "1"
        )

    def test_dirty_checkout_is_preserved(self):
        self.assertEqual(self.refresh().returncode, 0)
        (self.destination / "fixture.txt").write_text("local edit")
        self.commit("upstream edit")
        result = self.refresh()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local changes", result.stderr)
        self.assertEqual((self.destination / "fixture.txt").read_text(), "local edit")

    def test_unrelated_checkout_is_preserved(self):
        self.assertEqual(self.refresh().returncode, 0)
        head = self.git("-C", str(self.destination), "rev-parse", "HEAD")
        result = self.refresh((self.root / "unrelated").as_uri())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("different repository", result.stderr)
        self.assertEqual(
            self.git("-C", str(self.destination), "rev-parse", "HEAD"), head
        )


if __name__ == "__main__":
    unittest.main()
