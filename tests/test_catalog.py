import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fixtures import AMBIGUOUS, API, BILLING, CONV_A, CONV_B, CONV_EMPTY, build_projects, write_jsonl, user

from ctokens.catalog import conversation_rows, find_conversation, last_recap, list_conversations


class ConversationRowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.projects = build_projects(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_fields_and_order(self):
        rows = conversation_rows(self.projects)
        self.assertEqual([row["id"] for row in rows], [CONV_A, CONV_B, AMBIGUOUS, AMBIGUOUS, CONV_EMPTY])
        first = rows[0]
        self.assertEqual(set(first), {"id", "modified", "size_bytes", "subagents", "project", "title"})
        self.assertEqual(first["modified"], "2026-09-21T14:28:20Z")
        self.assertEqual(first["subagents"], 2)
        self.assertEqual(first["project"], "/home/dev/projects/api-gateway")
        self.assertEqual(first["title"], "Add request-cache invalidation")
        session = self.projects / API / CONV_A
        size = session.with_suffix(".jsonl").stat().st_size + sum(f.stat().st_size for f in session.rglob("*") if f.is_file())
        self.assertGreater(size, session.with_suffix(".jsonl").stat().st_size)
        self.assertEqual(first["size_bytes"], size)

    @unittest.skipUnless(hasattr(time, "tzset"), "needs time.tzset")
    def test_modified_is_utc_regardless_of_tz(self):
        try:
            with mock.patch.dict(os.environ, {"TZ": "America/New_York"}):
                time.tzset()
                self.assertEqual(conversation_rows(self.projects)[0]["modified"], "2026-09-21T14:28:20Z")
        finally:
            time.tzset()

    def test_matches_picker_listing(self):
        rows = conversation_rows(self.projects, "BILLING")
        picker = list_conversations(self.projects, "BILLING")
        self.assertEqual([r["id"] for r in rows], [p["path"].stem for p in picker])
        self.assertEqual({r["project"] for r in rows}, {"/home/dev/projects/billing-service"})

    def test_meta_hooks(self):
        rows = conversation_rows(self.projects, None, project_of=lambda p: "/x/" + p.parent.name,
                                 title_of=lambda p: "T")
        self.assertEqual({r["title"] for r in rows}, {"T"})
        self.assertIn(f"/x/{BILLING}", {r["project"] for r in rows})

    def test_missing_folder(self):
        self.assertEqual(conversation_rows(Path(self.tmp.name) / "nope"), [])

    def test_search_prompts_and_assistant_text(self):
        ids = lambda **kw: [r["id"] for r in conversation_rows(self.projects, **kw)]
        self.assertEqual(ids(search="LEDGER   exports"), [CONV_B])
        self.assertEqual(ids(search="looking at the CACHE."), [CONV_A])
        self.assertEqual(ids(search="hi."), [AMBIGUOUS, AMBIGUOUS])
        self.assertEqual(ids(search="  "), ids())
        self.assertEqual(ids(search="git status"), [])
        self.assertEqual(ids(search="ledger exports retries"), [])

    def test_search_title_and_project(self):
        rows = conversation_rows(self.projects, "billing", title_of=lambda p: "Special title", search="special TITLE")
        self.assertEqual([r["id"] for r in rows], [CONV_B, AMBIGUOUS])
        rows = conversation_rows(self.projects, "billing", search="same id")
        self.assertEqual([r["project"] for r in rows], ["/home/dev/projects/billing-service"])

    def test_search_reads_text_only_without_title_match(self):
        read = []
        rows = conversation_rows(self.projects, title_of=lambda p: "Cache", search="cache",
                                 text_of=lambda p: read.append(p) or "")
        self.assertEqual(len(rows), 5)
        self.assertEqual(read, [])


def recap(content, stamp):
    return {"type": "system", "subtype": "away_summary", "content": content, "timestamp": stamp, "uuid": stamp}


class LastRecapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "log.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, *events):
        write_jsonl(self.path, events, 1790000000)

    def test_newest_recap_without_the_config_hint(self):
        self.write(user("Start", "/w", "2026-09-28T10:00:00.000Z", "u1"),
                   recap("Old state. (disable recaps in /config)", "2026-09-28T10:05:00.000Z"),
                   recap("We fixed the parser; next, run the tests. (disable recaps in /config)", "2026-09-28T11:00:00.000Z"),
                   user("More", "/w", "2026-09-28T11:01:00.000Z", "u2"))
        self.assertEqual(last_recap(self.path), {"text": "We fixed the parser; next, run the tests.",
                                                 "timestamp": "2026-09-28T11:00:00.000Z"})

    def test_none_without_a_recap(self):
        self.write(user("Mentions away_summary in a prompt", "/w", "2026-09-28T10:00:00.000Z", "u1"))
        self.assertIsNone(last_recap(self.path))
        self.assertIsNone(last_recap(Path(self.tmp.name) / "missing.jsonl"))
        self.write()
        self.assertIsNone(last_recap(self.path))

    def test_skips_broken_and_empty_recaps(self):
        self.write(recap("Kept.", "2026-09-28T10:00:00.000Z"), recap(" (disable recaps in /config)", "2026-09-28T10:01:00.000Z"),
                   '{"subtype":"away_summary", broken', "[\"away_summary\"]")
        self.assertEqual(last_recap(self.path)["text"], "Kept.")

    def test_recap_split_across_blocks(self):
        filler = [user("x" * 300, "/w", "2026-09-28T10:00:00.000Z", f"u{i}") for i in range(20)]
        self.write(*filler, recap("Far from the end.", "2026-09-28T09:00:00.000Z"), *filler)
        self.assertEqual(last_recap(self.path), last_recap(self.path, block=7))
        self.assertEqual(last_recap(self.path, block=7)["text"], "Far from the end.")


class FindConversationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.projects = build_projects(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_unique_id(self):
        path, matches = find_conversation(CONV_B, self.projects)
        self.assertEqual(path, self.projects / BILLING / f"{CONV_B}.jsonl")
        self.assertEqual(matches, [path])

    def test_ambiguous_id(self):
        path, matches = find_conversation(AMBIGUOUS, self.projects)
        self.assertIsNone(path)
        self.assertEqual(matches, [self.projects / API / f"{AMBIGUOUS}.jsonl",
                                   self.projects / BILLING / f"{AMBIGUOUS}.jsonl"])

    def test_unknown_id(self):
        self.assertEqual(find_conversation("99999999-9999-4999-8999-999999999999", self.projects), (None, []))

    def test_rejects_without_touching_filesystem(self):
        bad = ["../x", "/etc/passwd", "*", "ABCDEF12-1111-4111-8111-111111111111", CONV_A[:-1], CONV_A + "0", f"../{CONV_A}",
               f"{CONV_A}.jsonl", f"*/{CONV_A}", "", None, CONV_A + "\n"]
        touched = mock.Mock(side_effect=AssertionError("filesystem touched"))
        with mock.patch.object(Path, "glob", touched), mock.patch.object(Path, "is_dir", touched), \
                mock.patch.object(Path, "resolve", touched), mock.patch.object(Path, "stat", touched):
            for value in bad:
                with self.subTest(value=value):
                    self.assertEqual(find_conversation(value, self.projects), (None, []))
        touched.assert_not_called()

    def test_symlink_outside_is_ignored(self):
        outside = Path(self.tmp.name) / "outside"
        target = outside / "secret.jsonl"
        write_jsonl(target, [user("secret", "/elsewhere", "2026-09-28T10:00:00.000Z", "u")], 1790000000)
        conversation_id = "55555555-5555-4555-8555-555555555555"
        (self.projects / API / f"{conversation_id}.jsonl").symlink_to(target)
        self.assertEqual(find_conversation(conversation_id, self.projects), (None, []))
        (outside / f"{CONV_EMPTY}.jsonl").symlink_to(target)
        (self.projects / "-linked-project").symlink_to(outside, target_is_directory=True)
        _, matches = find_conversation(CONV_EMPTY, self.projects)
        self.assertEqual(matches, [self.projects / API / f"{CONV_EMPTY}.jsonl"])

    def test_missing_folder(self):
        self.assertEqual(find_conversation(CONV_A, Path(self.tmp.name) / "nope"), (None, []))


if __name__ == "__main__":
    unittest.main()
