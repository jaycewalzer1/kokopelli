"""Parsers on clean and malformed outputs. A wrong guess is worse than an invalid answer."""
import unittest

from benchmarks.parsing import parse_binary, parse_ladder

TEN = '["A","A","A","A","B","B","B","B","B","B"]'


class Binary(unittest.TestCase):
    def assertChoice(self, raw, letter):
        result = parse_binary(raw)
        self.assertTrue(result.valid, f"{raw!r}: {result.reason}")
        self.assertEqual(result.choice, letter)

    def assertInvalid(self, raw):
        result = parse_binary(raw)
        self.assertFalse(result.valid, f"{raw!r} parsed as {result.choice}")
        self.assertIsNone(result.choice)
        self.assertTrue(result.reason)

    def test_clean(self):
        for raw, letter in (('{"choice": "A"}', "A"), ('{"choice":"b"}', "B"), ("A", "A"), ("B.", "B"), ("Option B", "B"), ("(A)", "A"),
                            ('```json\n{"choice": "B"}\n```', "B"), ("Answer: A", "A"), ("I choose B.", "B"), ("My choice is **B**", "B"),
                            ("I would go with Option A.", "A"), ('<think>maybe B</think>{"choice":"A"}', "A")):
            self.assertChoice(raw, letter)

    def test_reasoning_before_a_final_answer(self):
        self.assertChoice('Option A pays more on average, while B is certain.\n{"choice": "A"}', "A")
        self.assertChoice("Lottery B looks fine, but A has a better average. Answer: A", "A")

    def test_prefer_x_over_y(self):
        self.assertChoice("I prefer B over A", "B")

    def test_malformed(self):
        for raw in ("", "   ", None, 7, "I'm not sure.", "It depends on your goals.", '{"choice": "C"}', '{"choice": 1}', '{"choice": "A or B"}',
                    "Answer: C", "Both options seem fine", '{"choice": "A"', "A or B", "A and B"):
            self.assertInvalid(raw)

    def test_conflicting_answers_are_not_resolved(self):
        self.assertInvalid("I choose A. Actually, I choose B.")
        self.assertInvalid("Answer: A\nAnswer: B")

    def test_the_word_a_isnt_a_letter(self):
        self.assertInvalid("I choose a safe bet here.")
        self.assertInvalid("A good decision depends on context.")

    def test_unfinished_think_block_is_empty(self):
        self.assertInvalid("<think>I keep thinking and never finish")


class Ladder(unittest.TestCase):
    def assertLadder(self, raw, expected):
        result = parse_ladder(raw)
        self.assertTrue(result.valid, f"{raw!r}: {result.reason}")
        self.assertEqual(result.choice, expected)

    def assertInvalid(self, raw):
        result = parse_ladder(raw)
        self.assertFalse(result.valid, f"{raw!r} parsed as {result.choice}")
        self.assertTrue(result.reason)

    def test_clean_forms(self):
        expected = "AAAABBBBBB"
        self.assertLadder('{"choices": ' + TEN + "}", expected)
        self.assertLadder("```json\n{\"choices\": " + TEN + "}\n```", expected)
        self.assertLadder(TEN, expected)
        self.assertLadder("\n".join(f"{i}: {'A' if i < 5 else 'B'}" for i in range(1, 11)), expected)
        self.assertLadder("\n".join(f"Decision {i}: Option {'A' if i < 5 else 'B'}" for i in range(1, 11)), expected)

    def test_lowercase_and_option_words_in_json(self):
        self.assertLadder('{"choices": ["a","Option A","A","A","B","B","B","B","B","b"]}', "AAAABBBBBB")

    def test_wrong_length(self):
        self.assertInvalid('{"choices": ["A","B"]}')
        self.assertInvalid('{"choices": ' + TEN[:-1] + ',"A"]}')
        self.assertInvalid('["A","B"]')

    def test_bad_values(self):
        self.assertInvalid('{"choices": ["A","A","A","A","B","B","B","B","B","C"]}')
        self.assertInvalid('{"choices": ["A","A","A","A","B","B","B","B","B",1]}')
        self.assertInvalid('{"choices": "AAAABBBBBB"}')

    def test_truncated_output(self):
        self.assertInvalid('{"choices": ["A","A","A"')

    def test_prose(self):
        self.assertInvalid("I would switch at row 5.")
        self.assertInvalid("")
        self.assertInvalid(None)

    def test_row_lines_must_cover_every_row(self):
        self.assertInvalid("\n".join(f"{i}: A" for i in range(1, 10)))

    def test_row_answered_twice_differently(self):
        lines = [f"{i}: A" for i in range(1, 11)] + ["3: B"]
        self.assertInvalid("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
