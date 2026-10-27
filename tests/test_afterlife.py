"""Tests for git-afterlife. They build a tiny repository with real births and deaths
and replace the model with a fake medium, so no Ollama is needed."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import afterlife  # noqa: E402


def sh(repo, *args, author="Ana"):
    env = dict(os.environ, GIT_AUTHOR_NAME=author, GIT_AUTHOR_EMAIL="a@x",
               GIT_COMMITTER_NAME=author, GIT_COMMITTER_EMAIL="a@x")
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)


def write(repo, path, text):
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(text)


class Graveyard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        r = cls.repo = cls.tmp.name
        sh(r, "init", "-q")
        write(r, "app/legacy.py", "def parse_date(s):\n    return s\n\nclass Clock:\n    pass\n")
        write(r, "notes.md", "# Old plans\n\nnothing\n")
        write(r, "requirements.txt", "flask\n")
        write(r, "logo.bin", "\x00\x01binary")
        write(r, "phoenix.py", "x = 1\n")
        sh(r, "add", "-A")
        sh(r, "commit", "-qm", "first light")
        write(r, "app/legacy.py", "def parse_date(s):\n    return s.strip()\n\nclass Clock:\n    pass\n")
        sh(r, "commit", "-qam", "tweak parse_date", author="Bea")
        sh(r, "rm", "-q", "app/legacy.py", "notes.md", "requirements.txt", "logo.bin", "phoenix.py")
        sh(r, "commit", "-qm", "out with the old", author="Carlos")
        write(r, "phoenix.py", "x = 2\n")
        sh(r, "add", "-A")
        sh(r, "commit", "-qm", "phoenix rises")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def dead(self):
        return {g["path"]: g for g in afterlife.find_the_dead(self.repo)}

    def test_resurrected_files_are_not_dead(self):
        self.assertNotIn("phoenix.py", self.dead())

    def test_longest_lived_source_first_configs_last(self):
        order = [g["path"] for g in afterlife.find_the_dead(self.repo)]
        self.assertEqual(order[0], "app/legacy.py")
        self.assertEqual(order[-1], "requirements.txt")

    def test_exhume_recovers_the_whole_life(self):
        g = afterlife.exhume(self.repo, self.dead()["app/legacy.py"])
        self.assertEqual(g["commits"], 2)
        self.assertEqual(g["birth"]["subject"], "first light")
        self.assertEqual(g["death"]["subject"], "out with the old")
        self.assertEqual(g["death"]["author"], "Carlos")
        self.assertEqual(g["mourners"], ["Ana", "Bea"])
        self.assertIn("s.strip()", g["code"])
        self.assertEqual(g["names"], ["parse_date", "Clock"])

    def test_binaries_stay_buried(self):
        self.assertIsNone(afterlife.exhume(self.repo, self.dead()["logo.bin"]))

    def test_markdown_headings_are_remembered(self):
        self.assertEqual(afterlife.remembered_names("notes.md", "# Old plans\n## Ideas\n"),
                         ["Old plans", "Ideas"])
        self.assertEqual(afterlife.remembered_names("x.py", "# a comment\nx = 1\n"), [])

    def test_epitaph_survives_a_rambling_medium(self):
        g = afterlife.exhume(self.repo, self.dead()["app/legacy.py"])
        replies = iter(["not json at all", json.dumps({"epitaph": "Parsed all but its own.",
                                                        "last_words": "I was. Then Carlos."})])
        with mock.patch.object(afterlife, "ollama_chat", side_effect=lambda *a, **k: next(replies)):
            self.assertEqual(afterlife.write_epitaph("m", "English", g),
                             ("Parsed all but its own.", "I was. Then Carlos."))

    def test_garbled_epitaphs_are_asked_again(self):
        g = afterlife.exhume(self.repo, self.dead()["app/legacy.py"])
        garbage = "I ran the tests.”} } 2023-10-27 7318812198279155914 4451412024718967676"
        replies = iter([json.dumps({"epitaph": "Tidy.", "last_words": garbage}),
                        json.dumps({"epitaph": "x" * 200, "last_words": "Fine."}),
                        json.dumps({"epitaph": "Tidy to the end.", "last_words": "Carlos swept me away."})])
        with mock.patch.object(afterlife, "ollama_chat", side_effect=lambda *a, **k: next(replies)):
            self.assertEqual(afterlife.write_epitaph("m", "English", g),
                             ("Tidy to the end.", "Carlos swept me away."))

    def test_seance_is_told_the_true_cause_of_death(self):
        g = afterlife.exhume(self.repo, self.dead()["app/legacy.py"])
        prompt = afterlife.seance_prompt(g, "French")
        self.assertIn("Carlos deleted you", prompt)
        self.assertIn('"out with the old"', prompt)
        self.assertIn("Speak only French", prompt)

    def test_recorded_seance_keeps_the_whole_conversation(self):
        g = afterlife.exhume(self.repo, self.dead()["app/legacy.py"])
        seen = []

        def medium(model, messages, **kwargs):
            seen.append(len(messages))
            return " I am legacy.py. "

        with mock.patch.object(afterlife, "ollama_chat", side_effect=medium):
            transcript = afterlife.hold_seance("m", "English", g)
        self.assertEqual(transcript[0], ("Who are you, spirit?", "I am legacy.py."))
        self.assertEqual(len(transcript), 3)
        self.assertEqual(seen, [2, 4, 6])  # each question carries the séance so far

    def test_the_project_is_named_after_its_origin(self):
        self.assertEqual(afterlife.repo_name(self.repo), os.path.basename(self.repo))
        sh(self.repo, "remote", "add", "origin", "https://github.com/pallets/flask.git")
        try:
            self.assertEqual(afterlife.repo_name(self.repo), "flask")
        finally:
            sh(self.repo, "remote", "remove", "origin")

    def test_spirits_keep_their_code_as_code(self):
        self.assertEqual(afterlife.spoken("I held `Request` & <b>"),
                         "I held <code>Request</code> &amp; &lt;b&gt;")

    def test_seance_answers_wrap_without_splitting_words(self):
        out = io.StringIO()
        with redirect_stdout(out):
            text = afterlife.stream_wrapped(["I held Req", "uest and Response ", "for years"], 4, 20)
        self.assertEqual(text, "I held Request and Response for years")
        lines = out.getvalue().split("\n")
        self.assertEqual([l.strip() for l in lines], ["I held Request", "and Response for", "years"])
        self.assertTrue(all(len(l) <= 20 for l in lines))

    def test_line_count_is_exact(self):
        g = afterlife.exhume(self.repo, self.dead()["app/legacy.py"])
        self.assertEqual(g["lines"], 5)

    def test_altar_escapes_everything_it_is_told(self):
        g = afterlife.exhume(self.repo, self.dead()["app/legacy.py"])
        g.update(epitaph="<script>alert(1)</script>", last_words="a & b",
                 seance=[("<q>", "<a>")])
        page = afterlife.build_altar("repo", "gemma3:4b", [g])
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("a &amp; b", page)
        self.assertIn('<div class="q">&lt;q&gt;</div>', page)

    def test_summon_dry_run_writes_an_altar(self):
        out = os.path.join(self.tmp.name, "altar.html")
        args = mock.Mock(repo=self.repo, limit=10, seances=3, dry_run=True, out=out,
                         model="m", lang="English")
        with mock.patch.object(afterlife, "ollama_chat", side_effect=AssertionError("model called")):
            afterlife.summon(args)
        with open(out) as f:
            page = f.read()
        self.assertIn("app/legacy.py", page)
        self.assertIn("notes.md", page)
        self.assertNotIn("logo.bin", page)


if __name__ == "__main__":
    unittest.main()
