import tempfile
import unittest
from pathlib import Path

from fixtures import API, BILLING, CONV_A, CONV_B, SUB_EXPLORE, SUB_REVIEW, build_projects

from ctokens.logs import conversation_sources, discover, parse_log


class CoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.projects = build_projects(cls.tmp.name)
        cls.conv_a = cls.projects / API / f"{CONV_A}.jsonl"
        cls.conv_b = cls.projects / BILLING / f"{CONV_B}.jsonl"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()


class SourcesTest(CoreTest):
    def test_main_first_then_sorted_subagents_without_prefix(self):
        sources = conversation_sources(self.conv_a)
        subagents = self.conv_a.parent / CONV_A / "subagents"
        self.assertEqual(sources, [("main", self.conv_a),
                                   (SUB_EXPLORE, subagents / f"agent-{SUB_EXPLORE}.jsonl"),
                                   (SUB_REVIEW, subagents / f"agent-{SUB_REVIEW}.jsonl")])

    def test_no_subagents_folder(self):
        self.assertEqual(conversation_sources(self.conv_b), [("main", self.conv_b)])

    def test_discover_uses_the_injected_parser(self):
        calls = []

        def parse(path, kind, identifier, task):
            calls.append((path.name, kind, identifier, task))
            return parse_log(path, kind, identifier, task)

        self.assertEqual(discover(self.conv_a, parse=parse), discover(self.conv_a))
        self.assertEqual(calls, [
            (self.conv_a.name, "main", "main", "Add request-cache invalidation when the config is reloaded"),
            (f"agent-{SUB_EXPLORE}.jsonl", "subagent", SUB_EXPLORE, "Explore cache invalidation call sites"),
            (f"agent-{SUB_REVIEW}.jsonl", "subagent", SUB_REVIEW, "Review cache tests"),
        ])

    def test_discover_lists_subagents_before_main(self):
        self.assertEqual([row["id"] for row in discover(self.conv_a)], [SUB_EXPLORE, SUB_REVIEW, "main"])


if __name__ == "__main__":
    unittest.main()
