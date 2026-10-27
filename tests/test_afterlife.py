"""Tests for git-afterlife. They build a tiny repository with real births and deaths
and replace the model with a fake medium, so no Ollama is needed."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
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

    def test_seance_is_told_the_true_cause_of_death(self):
        g = afterlife.exhume(self.repo, self.dead()["app/legacy.py"])
        prompt = afterlife.seance_prompt(g, "Spanish")
        self.assertIn("Carlos deleted you", prompt)
        self.assertIn('"out with the old"', prompt)
        self.assertIn("Speak only Spanish", prompt)

    def test_recorded_seance_asks_in_the_chosen_language(self):
        g = afterlife.exhume(self.repo, self.dead()["app/legacy.py"])
        with mock.patch.object(afterlife, "ollama_chat", return_value=" Soy legacy.py. "):
            transcript = afterlife.hold_seance("m", "Spanish", g)
        self.assertEqual(transcript[0], ("¿Quién eres, espíritu?", "Soy legacy.py."))
        self.assertEqual(len(transcript), 3)

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
