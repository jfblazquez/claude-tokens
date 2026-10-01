import tempfile
import unittest

from fixtures import build_projects, snapshot


class FixturesTest(unittest.TestCase):
    def test_two_builds_are_identical(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            self.assertEqual(snapshot(build_projects(one)), snapshot(build_projects(two)))


if __name__ == "__main__":
    unittest.main()
