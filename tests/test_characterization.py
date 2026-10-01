import tempfile
import unittest
from pathlib import Path

from characterization import CASES, golden_path, run
from fixtures import build_projects


class CharacterizationTest(unittest.TestCase):
    """Pins the CLI output; refresh deliberately with tests/golden/refresh.py."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = cls.tmp.name
        cls.projects = build_projects(cls.base)
        cls.empty = Path(cls.base) / "empty"
        cls.empty.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_cases(self):
        for name in CASES:
            with self.subTest(case=name):
                expected = golden_path(name).read_text(encoding="utf-8")
                self.assertEqual(run(name, self.base, self.projects, self.empty), expected)


if __name__ == "__main__":
    unittest.main()
