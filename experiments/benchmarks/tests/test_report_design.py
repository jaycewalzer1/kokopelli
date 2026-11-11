"""DESIGN.md's checklist (section 12), for the parts a machine can check. Screenshots at 375px are checked by eye."""
import re
import tempfile
import unittest
from pathlib import Path

from experiments.benchmarks import report
from experiments.benchmarks.run import main as run_main

# Copied from DESIGN.md sections 1 and 9, including the categorical colors the report uses.
TOKENS = {"#D0CCC5", "#CEC9C0", "#3E191C", "#ABA59F", "#2A1B18", "#5E524A", "#5A2328", "#A65A48", "#B48322", "#9E2A22", "#5E6B4E", "#4F5F6B"}
COLORS = {"ground": "#D0CCC5", "panel": "#CEC9C0", "ink": "#2A1B18", "ink-muted": "#5E524A"}


def luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class Design(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="evals_")
        out = Path(cls.folder.name) / "r"
        run_main(["--arms", "base", "lived", "described", "shuffled", "flipped_lived", "--instruments", "holt_laury", "lotteries", "ifeval", "mmlu", "--samples", "10", "--seeds", "0", "1", "2", "--out", str(out)])
        cls.page = report.to_html(report.collect(out))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_only_design_tokens_for_color(self):
        self.assertLessEqual({c.upper() for c in re.findall(r"#[0-9a-fA-F]{6}\b", self.page)}, {t.upper() for t in TOKENS})
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3}\b", self.page), [])
        self.assertEqual(re.findall(r"\b(?:rgb|hsl)a?\(", self.page), [])

    def test_no_shadows_gradients_or_rounding(self):
        for banned in ("box-shadow", "text-shadow", "gradient", "border-radius", "filter:"):
            self.assertNotIn(banned, self.page)

    def test_one_pigment_series_and_one_gold_line(self):
        body = self.page.split("<body>")[1]
        self.assertEqual(body.count('class="ci key"'), 1)
        self.assertEqual(body.count('class="dot key"'), 1)
        # The norm line repeats on each arm's row of one chart, as one vertical reference line.
        self.assertEqual(len(re.findall(r'class="norm"', body)), 5)

    def test_text_contrast(self):
        for surface in ("ground", "panel"):
            for text in ("ink", "ink-muted"):
                self.assertGreaterEqual(contrast(COLORS[text], COLORS[surface]), 4.5, (text, surface))

    def test_the_page_uses_the_token_values(self):
        for name, value in COLORS.items():
            self.assertIn(f"--{name}: {value};", self.page)

    def test_one_theme_until_dark_is_designed(self):
        self.assertNotIn("prefers-color-scheme", self.page)

    def test_tables_scroll_inside_their_own_box(self):
        self.assertNotIn("<table", self.page.replace('<div class="scroll"><table', ""))

    def test_no_banned_motifs(self):
        for word in ("flute", "petroglyph", "katsina", "zia", "feather", "tribal"):
            self.assertNotIn(word, self.page.lower())


if __name__ == "__main__":
    unittest.main()
