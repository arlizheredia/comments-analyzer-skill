#!/usr/bin/env python3
"""End-to-end tests for the skill scripts: python3 -m unittest discover -s tests -v"""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "social-comments-analyzer", "scripts")
EX = os.path.join(ROOT, "examples")


def run(script, *args):
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, script), *args],
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise AssertionError("%s failed (%d):\n%s\n%s" % (script, p.returncode, p.stdout, p.stderr))
    return p.stdout


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.d = cls.tmp.name
        run("normalize.py",
            os.path.join(EX, "instagram-agensi.json"),
            os.path.join(EX, "tiktok-agensi.json") + "::https://www.tiktok.com/@brand/video/7299999999999999999",
            os.path.join(EX, "facebook-agensi.json") + "::https://www.facebook.com/brand/posts/456",
            os.path.join(EX, "app-export.csv"),
            "-o", os.path.join(d, "comments.json"))
        with open(os.path.join(d, "labels.json"), "w", encoding="utf-8") as fh:
            json.dump({"17900000000000003": {"sentiment": "neutral", "focus": True, "topic": "shipping"},
                       "7300000000000000003": {"focus": True, "topic": "refunds"}}, fh)
        cls.summary = run("analyze.py", os.path.join(d, "comments.json"), "-o", os.path.join(d, "analysis.json"),
                          "--enriched", os.path.join(d, "enriched.json"), "--digest", os.path.join(d, "digest.jsonl"),
                          "--labels", os.path.join(d, "labels.json"), "--team", "@kanasta24", "--focus-name", "Service")
        with open(os.path.join(d, "summary.md"), "w", encoding="utf-8") as fh:
            fh.write("Overall **positive** tone.\n\n- Refund complaints\n- <script>alert(1)</script>\n")
        cls.exported = run("export.py", os.path.join(d, "enriched.json"), "--analysis", os.path.join(d, "analysis.json"),
                           "--summary", os.path.join(d, "summary.md"), "--formats", "html,xlsx,csv,md,json",
                           "--out-dir", os.path.join(d, "out"), "--lang", "es", "--name", "test")
        with open(os.path.join(d, "comments.json"), encoding="utf-8") as fh:
            cls.comments = {c["id"]: c for c in json.load(fh)["comments"]}
        with open(os.path.join(d, "analysis.json"), encoding="utf-8") as fh:
            cls.an = json.load(fh)
        with open(os.path.join(d, "enriched.json"), encoding="utf-8") as fh:
            cls.enriched = {c["id"]: c for c in json.load(fh)["comments"]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # normalize ---------------------------------------------------------------
    def test_counts_and_platforms(self):
        self.assertEqual(len(self.comments), 13)
        plats = {c["platform"] for c in self.comments.values()}
        self.assertEqual(plats, {"instagram", "tiktok", "facebook"})

    def test_nested_replies_linked(self):
        self.assertEqual(self.comments["17900000000000002"]["parentId"], "17900000000000001")
        self.assertEqual(self.comments["7300000000000000002"]["parentId"], "7300000000000000001")

    def test_fields_mapped(self):
        tt = self.comments["7300000000000000001"]
        self.assertEqual((tt["authorName"], tt["likes"]), ("foodie_jen", 310))
        self.assertEqual(tt["createdAt"], "2024-11-24T15:00:00Z")
        fb = self.comments["123_457"]
        self.assertEqual((fb["authorName"], fb["likes"], fb["createdAt"]), ("Jorge Pérez", 21, "2024-11-23T09:30:00Z"))
        self.assertEqual(fb["postUrl"], "https://www.facebook.com/brand/posts/456")
        ig = self.comments["17900000000000001"]
        self.assertEqual(ig["postUrl"], "https://www.instagram.com/p/DEMO123abc/")
        self.assertEqual(self.comments["fb_1"]["authorName"], "Rosa Martín")

    def test_dedup_and_renormalize(self):
        out = os.path.join(self.d, "again.json")
        run("normalize.py", os.path.join(self.d, "comments.json"), os.path.join(EX, "instagram-agensi.json"), "-o", out)
        with open(out, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["count"], 13)

    # analyze -----------------------------------------------------------------
    def test_labels_override_and_focus(self):
        self.assertEqual(self.enriched["17900000000000003"]["sentiment"], "neutral")
        self.assertEqual(self.enriched["17900000000000003"]["sentimentSource"], "agent")
        self.assertEqual(self.an["focus"]["count"], 2)
        self.assertEqual(self.an["focusName"], "Service")
        self.assertIn(["refunds", 1], self.an["overall"]["topics"])

    def test_sentiment_lexicon(self):
        e = self.enriched
        self.assertEqual(e["17900000000000004"]["sentiment"], "negative")   # pésimo ... 😡
        self.assertEqual(e["17900000000000005"]["sentiment"], "negative")   # no es malo, pero ... lenta
        self.assertEqual(e["7300000000000000001"]["sentiment"], "positive")  # amazing 🔥
        self.assertEqual(e["7300000000000000003"]["sentiment"], "negative")  # scam, never

    def test_team_and_unanswered(self):
        self.assertTrue(self.enriched["17900000000000002"]["isTeam"])
        unanswered = {c["id"] for c in self.an["unansweredQuestions"]}
        self.assertIn("7300000000000000004", unanswered)
        self.assertNotIn("17900000000000002", unanswered)

    def test_words_exclude_mentions_and_stopwords(self):
        words = [w for w, _ in self.an["overall"]["topWords"]]
        self.assertNotIn("lopez", words)
        self.assertNotIn("the", words)

    def test_digest(self):
        with open(os.path.join(self.d, "digest.jsonl"), encoding="utf-8") as fh:
            rows = [json.loads(l) for l in fh]
        self.assertEqual(len(rows), 13)
        self.assertEqual(rows[0]["id"], "7300000000000000001")  # most liked first

    def test_stdout_summary(self):
        self.assertIn("Comments: **13**", self.summary)

    # export ------------------------------------------------------------------
    def test_html_escapes_and_contains_summary(self):
        with open(os.path.join(self.d, "out", "test.html"), encoding="utf-8") as fh:
            h = fh.read()
        self.assertIn("<strong>positive</strong>", h)
        self.assertNotIn("<script>", h)
        self.assertIn("Informe de comentarios", h)
        self.assertNotRegex(h, r"<(script|link|img|iframe)\b")  # self-contained: no scripts or external assets

    def test_xlsx_valid(self):
        path = os.path.join(self.d, "out", "test.xlsx")
        with zipfile.ZipFile(path) as z:
            self.assertIsNone(z.testzip())
            names = z.namelist()
            self.assertIn("xl/worksheets/sheet1.xml", names)
            self.assertIn("xl/worksheets/sheet2.xml", names)
            sheet = z.read("xl/worksheets/sheet1.xml").decode()
            self.assertIn("foodie_jen", sheet)

    def test_csv_formula_injection_neutralized(self):
        with open(os.path.join(self.d, "out", "test.csv"), encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0][0], "Red")
        texts = [r[10] for r in rows[1:]]
        self.assertTrue(any(t.startswith("'=HYPERLINK") for t in texts))
        self.assertFalse(any(t.startswith("=") for t in texts))

    def test_md_and_json(self):
        self.assertTrue(os.path.getsize(os.path.join(self.d, "out", "test.md")) > 200)
        with open(os.path.join(self.d, "out", "test.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["count"], 13)


class EdgeCases(unittest.TestCase):
    def test_empty_input_fails_clearly(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "empty.json")
            with open(src, "w") as fh:
                fh.write('{"comments": []}')
            p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "normalize.py"), src, "-o",
                                os.path.join(d, "o.json")], capture_output=True, text=True)
            self.assertEqual(p.returncode, 1)
            self.assertIn("no comments", p.stderr)

    def test_jsonl_and_epoch_ms(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "c.jsonl")
            with open(src, "w") as fh:
                fh.write('{"id":"a","text":"hola","username":"x","timestamp":1732460400000,"likes":"1.2K"}\n')
                fh.write('{"id":"b","text":"adios","username":"y"}\n')
            out = os.path.join(d, "o.json")
            run("normalize.py", src, "-o", out, "--platform", "ig")
            with open(out) as fh:
                cs = json.load(fh)["comments"]
            self.assertEqual(cs[0]["createdAt"], "2024-11-24T15:00:00Z")
            self.assertEqual(cs[0]["likes"], 1200)
            self.assertEqual(cs[0]["platform"], "instagram")


if __name__ == "__main__":
    unittest.main()
