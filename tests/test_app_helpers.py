import unittest

from flask import render_template

from app import app, normalize_text, parse_quiz_answer


class AppHelperTests(unittest.TestCase):
    def test_normalize_text_trims_and_cleans_whitespace(self):
        self.assertEqual(normalize_text("  Hello there  "), "Hello there")
        self.assertEqual(normalize_text("\n\t"), "")

    def test_parse_quiz_answer_respects_letter_and_index_inputs(self):
        options = ["Python", "Java", "C++", "Go"]
        self.assertEqual(parse_quiz_answer("2", options), "Java")
        self.assertEqual(parse_quiz_answer("C", options), "C++")
        self.assertEqual(parse_quiz_answer("  go  ", options), "Go")

    def test_notes_template_renders_note_action_links(self):
        with app.test_request_context():
            rendered = render_template("notes.html", notes=[(1, "Title", "Body")])

        self.assertIn("/download_note/1", rendered)
        self.assertIn("/edit/1", rendered)
        self.assertIn("/delete/1", rendered)


if __name__ == "__main__":
    unittest.main()
