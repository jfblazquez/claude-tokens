import copy
import io
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from fixtures import API, BILLING, CONV_A, CONV_B, SUB_EXPLORE, SUB_REVIEW, build_projects

from ctokens.logs import conversation_sources, discover, file_stats, parse_log
from ctokens.reports import scan_totals


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

    def setUp(self):
        # The fixtures' malformed line makes lines() warn on stderr.
        stderr = mock.patch("sys.stderr", new_callable=io.StringIO)
        stderr.start()
        self.addCleanup(stderr.stop)


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


class FileStatsTest(CoreTest):
    def test_pure(self):
        first, second = file_stats(self.conv_a), file_stats(self.conv_a)
        self.assertEqual(first, second)
        first["tools"]["Bash"] += 100
        first["models"]["claude-opus-5-5"]["input"] += 100
        first["daily_models"]["2026-09-28"]["claude-opus-5-5"]["input"] += 100
        self.assertEqual(file_stats(self.conv_a), second)

    def test_shape(self):
        stats = file_stats(self.conv_a)
        self.assertEqual(set(stats), {"models", "tools", "skills", "window", "responses", "daily_models"})
        for key in ("tools", "skills", "responses"):
            self.assertIsInstance(stats[key], Counter)
        self.assertEqual(stats["responses"], Counter({"2026-09-28": 1, "2026-09-29": 1, "2026-09-30": 1}))
        self.assertEqual([x.isoformat() for x in stats["window"]], ["2026-09-28T10:00:00", "2026-09-30T00:00:10"])
        self.assertEqual(sorted(stats["daily_models"]), ["2026-09-28", "2026-09-29", "2026-09-30"])

    def test_undated_records_go_under_none(self):
        stats = file_stats(self.conv_a.parent / CONV_A / "subagents" / f"agent-{SUB_REVIEW}.jsonl")
        self.assertEqual(list(stats["daily_models"]), [None])
        self.assertEqual(stats["daily_models"][None]["claude-sonnet-5-5"]["output"], 700)
        self.assertEqual(stats["responses"], Counter())

    def test_no_timestamps_means_no_window(self):
        path = Path(self.tmp.name) / "no-stamps.jsonl"
        path.write_text('{"type": "summary"}\n', encoding="utf-8")
        self.assertIsNone(file_stats(path)["window"])


class ScanTotalsTest(CoreTest):
    def test_stats_hook_called_once_per_log(self):
        calls = []

        def stats(path):
            calls.append(path)
            return file_stats(path)

        self.assertEqual(scan_totals(self.projects, stats=stats), scan_totals(self.projects))
        self.assertEqual(sorted(calls), sorted(self.projects.rglob("*.jsonl")))

    def test_does_not_mutate_stats_results(self):
        cache = {}

        def stats(path):
            cache[path] = file_stats(path)
            return cache[path]

        scan_totals(self.projects, stats=stats)
        snapshot = copy.deepcopy(cache)
        scan_totals(self.projects, stats=cache.__getitem__)
        self.assertEqual(cache, snapshot)
        self.assertEqual(cache, {path: file_stats(path) for path in cache})


if __name__ == "__main__":
    unittest.main()
