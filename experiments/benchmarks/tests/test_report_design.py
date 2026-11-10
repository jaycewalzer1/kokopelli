"""DESIGN.md section 8, for the parts a machine can check. Screenshots at 375px in both themes are checked by eye."""
import re
import tempfile
import unittest
from pathlib import Path

from experiments.benchmarks import report
from experiments.benchmarks.run import main as run_main

# Copied from DESIGN.md section 1, including the categorical colors the report uses.
TOKENS = {
    "#F3EEE6", "#EAE3D8", "#3B2A22", "#CFC4B4", "#2B1E18", "#6E6056", "#8F4739", "#9A7B40", "#9E2A22", "#5E6B4E", "#4F5F6B",
    "#14100D", "#1E1814", "#33271F", "#3A302A", "#EDE5DA", "#A89A8C", "#C07A62", "#C4A66B", "#E8877C", "#9AA88A", "#8E9EAA",
}
LIGHT = {"surface-100": "#F3EEE6", "surface-200": "#EAE3D8", "ink": "#2B1E18", "ink-muted": "#6E6056"}
DARK = {"surface-100": "#14100D", "surface-200": "#1E1814", "ink": "#EDE5DA", "ink-muted": "#A89A8C"}


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

    def test_one_clay_series_and_one_gold_line(self):
        body = self.page.split("<body>")[1]
        self.assertEqual(body.count('class="ci key"'), 1)
        self.assertEqual(body.count('class="dot key"'), 1)
        # The norm line repeats on each arm's row of one chart, as one vertical reference line.
        self.assertEqual(len(re.findall(r'class="norm"', body)), 5)

    def test_contrast_in_both_themes(self):
        for theme in (LIGHT, DARK):
            for surface in ("surface-100", "surface-200"):
                for text in ("ink", "ink-muted"):
                    self.assertGreaterEqual(contrast(theme[text], theme[surface]), 4.5, (text, surface))

    def test_both_themes_are_defined(self):
        self.assertIn("prefers-color-scheme: dark", self.page)
        self.assertIn(':root[data-theme="dark"]', self.page)

    def test_tables_scroll_inside_their_own_box(self):
        self.assertNotIn("<table", self.page.replace('<div class="scroll"><table', ""))

    def test_no_section_7_motifs(self):
        for word in ("flute", "petroglyph", "katsina", "zia", "feather", "tribal"):
            self.assertNotIn(word, self.page.lower())


if __name__ == "__main__":
    unittest.main()
