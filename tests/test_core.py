import copy
import io
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from fixtures import (API, BILLING, CONV_A, CONV_B, LAST_RESPONSE, SUB_EXPLORE, SUB_REVIEW, assistant, build_projects,
                      text, tool, usage, write_jsonl)

from ctokens.cli import show_bash_commands
from ctokens.content import CLIP, bash_commands, conversation_messages, last_response, touched_files, transcript
from ctokens.logs import conversation_sources, discover, file_stats, parse_log
from ctokens.pricing import load_prices
from ctokens.reports import report, scan_totals, totals_report
from ctokens.text import messages_text


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

    def write(self, name, events):
        path = Path(self.tmp.name) / name
        write_jsonl(path, events, 0)
        return path

    def test_tool_calls_split_over_events_count_once_each(self):
        use, stamp = usage(1, 1), "2026-09-28T10:00:00.000Z"
        path = self.write("split.jsonl", [
            assistant("m1", "claude-opus-5-5", stamp, "e1", [text("Two calls.")], use),
            assistant("m1", "claude-opus-5-5", stamp, "e2", [tool("t1", "Bash", command="ls")], use),
            assistant("m1", "claude-opus-5-5", stamp, "e3", [tool("t2", "Read", file_path="/x")], use),
            assistant("m1", "claude-opus-5-5", stamp, "e4", [tool("t2", "Read", file_path="/x")], use),
        ])
        stats = file_stats(path)
        self.assertEqual(stats["tools"], Counter({"Bash": 1, "Read": 1}))
        self.assertEqual(stats["models"]["claude-opus-5-5"]["input"], 1)
        self.assertEqual(stats["responses"], Counter({"2026-09-28": 1}))

    def test_skills_follow_the_same_rule(self):
        use = usage(1, 1)
        path = self.write("skills.jsonl", [
            assistant("m1", "claude-opus-5-5", None, "e1", [text("Loading.")], use),
            assistant("m1", "claude-opus-5-5", None, "e2", [tool("t1", "Skill", skill="tdd")], use),
            assistant("m1", "claude-opus-5-5", None, "e3", [tool("t1", "Skill", skill="tdd")], use),
            assistant("m2", "claude-opus-5-5", None, "e4", [tool("t2", "Skill", skill="tdd")], use),
        ])
        stats = file_stats(path)
        self.assertEqual(stats["tools"], Counter({"Skill": 2}))
        self.assertEqual(stats["skills"], Counter({"tdd": 2}))

    def test_tool_use_without_id_always_counts(self):
        block = {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}
        path = self.write("no-id.jsonl", [assistant("m1", "claude-opus-5-5", None, "e1", [block], usage(1, 1)),
                                          assistant("m1", "claude-opus-5-5", None, "e2", [block], usage(1, 1))])
        self.assertEqual(file_stats(path)["tools"], Counter({"Bash": 2}))

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


class DailySeriesTest(CoreTest):
    def totals(self, project=None):
        return totals_report(scan_totals(self.projects, project), load_prices(None))

    def test_daily_costs_add_up_to_the_total(self):
        data = self.totals()
        self.assertAlmostEqual(sum(d["estimated_cost_usd"] for d in data["daily"]),
                               data["estimated_total_cost_usd"], places=4)
        self.assertEqual(sum(d["total_tokens"] for d in data["daily"]), data["total_tokens"])
        for day in data["daily"]:
            self.assertAlmostEqual(sum(m["estimated_cost_usd"] or 0 for m in day["models"].values()),
                                   day["estimated_cost_usd"], places=10)

    def test_days_ascending_in_utc_with_undated_last(self):
        days = [d["day"] for d in self.totals()["daily"]]
        self.assertEqual(days, ["2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30", None])
        by_day = {d["day"]: d for d in self.totals()["daily"]}
        # msg_A2 is stamped 23:59:50Z and msg_A3 00:00:10Z the next Day.
        self.assertEqual(by_day["2026-09-29"]["models"]["claude-opus-5-5"]["output"], 1400)
        self.assertEqual(by_day["2026-09-30"]["models"]["claude-opus-5-5"]["output"], 2100)
        self.assertEqual(by_day[None]["models"]["claude-sonnet-5-5"]["output"], 700)
        self.assertEqual(by_day[None]["responses"], 0)

    def test_undated_bucket_only_when_non_empty(self):
        self.assertNotIn(None, [d["day"] for d in self.totals("billing")["daily"]])

    def test_unpriced_model_has_null_cost(self):
        day = next(d for d in self.totals()["daily"] if d["day"] == "2026-09-30")
        self.assertIsNone(day["models"]["acme-model-1"]["estimated_cost_usd"])
        self.assertEqual(day["models"]["acme-model-1"]["total_tokens"], 700)
        self.assertEqual(day["estimated_cost_usd"], day["models"]["claude-opus-5-5"]["estimated_cost_usd"])

    def test_responses_per_day_match_the_window(self):
        data = self.totals()
        self.assertEqual(sum(d["responses"] for d in data["daily"]), 8)
        self.assertEqual(len([d for d in data["daily"] if d["responses"]]), data["window"]["active_days"])

    def test_empty_projects_folder(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir(exist_ok=True)
        self.assertEqual(totals_report(scan_totals(empty), load_prices(None))["daily"], [])


class ContentTest(CoreTest):
    def conversation(self, name, main, subagents):
        path = Path(self.tmp.name) / "content" / f"{name}.jsonl"
        write_jsonl(path, main, 0)
        for identifier, events in subagents.items():
            write_jsonl(path.parent / name / "subagents" / f"agent-{identifier}.jsonl", events, 0)
        return path

    def test_bash_interleaves_sources_chronologically_with_undated_last(self):
        commands = bash_commands(self.conv_a)
        self.assertEqual([(c["source"], c["command"]) for c in commands], [
            ("main", "git status --short"),
            (SUB_EXPLORE, "grep -rn 'invalidate(' src/"),
            ("main", "python3 -m unittest -v"),
            (SUB_REVIEW, "python3 -m unittest tests.test_cache"),
        ])
        self.assertEqual(commands[0], {"command": "git status --short", "description": "Show working tree status",
                                       "source": "main", "timestamp": "2026-09-28T10:00:05.100Z"})
        self.assertIsNone(commands[-1]["timestamp"])

    def test_bash_orders_within_the_same_second_and_keeps_log_order_when_undated(self):
        use = usage(1, 1)
        path = self.conversation("order", [
            assistant("m1", "claude-opus-5-5", None, "e1", [tool("t1", "Bash", command="undated main")], use),
            assistant("m2", "claude-opus-5-5", "2026-09-28T10:00:00.900Z", "e2", [tool("t2", "Bash", command="late")], use),
            assistant("m3", "claude-opus-5-5", None, "e3", [tool("t3", "Bash", command="undated main 2")], use),
        ], {"zz": [
            assistant("s1", "claude-haiku-4-5", "2026-09-28T10:00:00.200Z", "s1", [tool("t4", "Bash", command="early")], use),
            assistant("s2", "claude-haiku-4-5", None, "s2", [tool("t5", "Bash", command="undated sub")], use),
        ]})
        self.assertEqual([c["command"] for c in bash_commands(path)],
                         ["early", "late", "undated main", "undated main 2", "undated sub"])

    def test_repeated_block_is_listed_and_counted_once(self):
        use, stamp = usage(1, 1), "2026-09-28T10:00:00.000Z"
        bash = tool("t1", "Bash", command="make", description="Build")
        edit = tool("t2", "Edit", file_path="/src/a.py", old_string="a", new_string="b")
        path = self.conversation("repeated", [
            assistant("m1", "claude-opus-5-5", stamp, "e1", [bash], use),
            assistant("m1", "claude-opus-5-5", stamp, "e2", [bash, edit], use),
            assistant("m1", "claude-opus-5-5", stamp, "e3", [edit], use),
        ], {})
        self.assertEqual([c["command"] for c in bash_commands(path)], ["make"])
        self.assertEqual(touched_files(path), {"/src/a.py": {"Read": 0, "Write": 0, "Edit": 1, "sources": ["main"]}})

    def test_touched_files_one_row_per_file_with_summed_counts_and_sources(self):
        self.assertEqual(touched_files(self.conv_a), {
            "/home/dev/projects/api-gateway/src/cache.py": {"Read": 2, "Write": 0, "Edit": 1,
                                                            "sources": ["main", SUB_EXPLORE]},
            "/home/dev/projects/api-gateway/tests/test_reload.py": {"Read": 0, "Write": 1, "Edit": 0,
                                                                    "sources": [SUB_REVIEW]},
        })

    def test_bash_text_names_the_subagent_even_without_description(self):
        use = usage(1, 1)
        path = self.conversation("nodesc", [
            assistant("m1", "claude-opus-5-5", None, "e1", [tool("t1", "Bash", command="ls")], use),
        ], {"zz": [assistant("s1", "claude-haiku-4-5", None, "s1", [tool("t2", "Bash", command="pwd")], use)]})
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            show_bash_commands(path, as_json=False)
        self.assertEqual(out.getvalue(), "$ ls\n\n# [subagent zz]\n$ pwd\n\n2 Bash command(s).\n")

    def test_last_response_reads_the_main_log_only(self):
        use = usage(1, 1)
        path = self.conversation("last", [
            assistant("m1", "claude-opus-5-5", "2026-09-28T10:00:00.000Z", "e1", [text("From main.")], use),
        ], {"zz": [assistant("s1", "claude-haiku-4-5", "2026-09-28T11:00:00.000Z", "s1", [text("From sub.")], use)]})
        self.assertEqual(last_response(path), "From main.")
        self.assertEqual(last_response(self.conv_a), LAST_RESPONSE)



def tool_result(tool_id, content, is_error=False, stamp=None):
    event = {"type": "user", "uuid": f"r-{tool_id}", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": content, "is_error": is_error}]}}
    if stamp:
        event["timestamp"] = stamp
    return event


class MessagesTest(ContentTest):
    prices = load_prices(None)

    def test_one_message_per_response_with_its_usage_and_cost(self):
        messages = transcript(self.conv_a, self.prices)
        self.assertEqual([(m["role"], m["kind"]) for m in messages],
                         [("user", "prompt")] + [("assistant", "response")] * 3)
        first = messages[1]
        self.assertEqual([b["type"] for b in first["blocks"]], ["text", "tool_use"])
        self.assertEqual(first["blocks"][1], {"type": "tool_use", "id": "toolu_A1", "name": "Bash",
                                              "summary": "git status --short", "input": [
                                                  {"name": "command", "text": "git status --short", "size": 18},
                                                  {"name": "description", "text": "Show working tree status", "size": 24}]})
        self.assertEqual(first["usage"], {"input": 120, "output": 900, "cache_read": 40000, "cache_write_5m": 0,
                                          "cache_write_1h": 3000, "thinking": None, "context": 43120,
                                          "web_search_requests": None, "web_fetch_requests": None,
                                          "service_tier": None, "speed": None})
        self.assertEqual((first["model"], first["timestamp"]), ("claude-opus-5-5", "2026-09-28T10:00:05.000Z"))
        # The repeated Read block of msg_A2 is listed once.
        self.assertEqual([b["id"] for b in messages[2]["blocks"]], ["toolu_A2", "toolu_A3"])

    def test_costs_add_up_to_the_usage_report(self):
        total = 0
        for source, _ in conversation_sources(self.conv_a):
            data = conversation_messages(self.conv_a, source, self.prices)
            total += sum(m["estimated_cost_usd"] for m in data["messages"] if m["role"] == "assistant")
        expected = report(discover(self.conv_a), self.prices, 2000)["estimated_total_cost_usd"]
        self.assertAlmostEqual(total, expected, places=12)

    def test_repeated_stream_events_do_not_repeat_blocks(self):
        messages = transcript(self.conv_b, self.prices)
        self.assertEqual([b["text"] for b in messages[-1]["blocks"]], ["Done."])
        self.assertIsNone(messages[-1]["estimated_cost_usd"])
        self.assertEqual(messages[1]["usage"]["cache_write_5m"], 1500)

    def test_sources_and_unknown_source(self):
        data = conversation_messages(self.conv_a, SUB_EXPLORE, self.prices)
        self.assertEqual([s["id"] for s in data["sources"]], ["main", SUB_EXPLORE, SUB_REVIEW])
        self.assertEqual(data["sources"][1]["task"], "Explore cache invalidation call sites")
        self.assertEqual(data["messages"][1]["model"], "claude-haiku-4-5")
        self.assertIsNone(conversation_messages(self.conv_a, "nope", self.prices))

    def test_kinds_results_thinking_and_clipping(self):
        use, big = usage(1, 1), "x" * (CLIP + 10)
        error = dict(assistant("m2", "<synthetic>", None, "e3", [text("API Error: overloaded")], usage()), isApiErrorMessage=True)
        path = self.conversation("kinds", [
            {"type": "user", "uuid": "u1", "message": {"role": "user", "content": "Fix it"}},
            {"type": "user", "uuid": "u2", "isMeta": True, "message": {"role": "user", "content": [text("Skill body")]}},
            {"type": "summary", "summary": "not a message"},
            assistant("m1", "claude-opus-5-5", None, "e1", [{"type": "thinking", "thinking": "", "signature": "s"}], use),
            assistant("m1", "claude-opus-5-5", None, "e2", [{"type": "thinking", "thinking": "Plan"},
                                                            tool("t1", "Read", file_path="/a.py", limit=3)], use),
            tool_result("t1", [{"type": "text", "text": big}, {"type": "image"}], is_error=True),
            {"type": "user", "uuid": "u3", "isCompactSummary": True, "message": {"role": "user", "content": "Summary"}},
            error,
        ], {})
        messages = transcript(path, self.prices)
        self.assertEqual([m["kind"] for m in messages], ["prompt", "meta", "response", "tool_result", "summary", "error"])
        self.assertEqual([b["type"] for b in messages[2]["blocks"]], ["thinking", "tool_use"])
        self.assertEqual(messages[2]["blocks"][1]["input"][1], {"name": "limit", "text": "3", "size": 1})
        self.assertEqual(messages[2]["blocks"][1]["summary"], "/a.py")
        result = messages[3]["blocks"][0]
        self.assertEqual((result["tool_use_id"], result["is_error"], result["size"]), ("t1", True, CLIP + 18))
        self.assertEqual(len(result["text"]), CLIP)
        self.assertIsNone(messages[5]["estimated_cost_usd"])

    def test_tool_summary_falls_back_to_the_first_text(self):
        use = usage(1, 1)
        ask = tool("t1", "AskUserQuestion", questions=[{"header": "", "question": "Which port?", "options": []}])
        path = self.conversation("summary", [
            assistant("m1", "claude-opus-5-5", None, "e1", [ask, tool("t2", "Glob", pattern="*.py", path="src")], use),
            assistant("m2", "claude-opus-5-5", None, "e2", [tool("t3", "TodoWrite", todos=[])], use),
        ], {})
        blocks = [b for m in transcript(path, self.prices) for b in m["blocks"]]
        self.assertEqual([b["summary"] for b in blocks], ["Which port?", "src", ""])

    def test_text_numbers_only_the_messages_the_web_ui_shows(self):
        use = usage(1, 1)
        path = self.conversation("numbers", [
            {"type": "user", "uuid": "u1", "message": {"role": "user", "content": "Go"}},
            assistant("m1", "claude-opus-5-5", None, "e1", [tool("t1", "Bash", command="ls")], use),
            tool_result("t1", "a.py"),
            assistant("m2", "claude-opus-5-5", None, "e2", [text("Done.")], use),
        ], {})
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            messages_text(conversation_messages(path, "main", self.prices))
        rows = [line.split("|") for line in out.getvalue().splitlines()[3:6]]
        self.assertEqual([(r[0].strip(), r[2].strip()) for r in rows], [("1", "user"), ("2", "assistant"), ("3", "assistant")])
        self.assertIn("3 message(s), 2 response(s)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
