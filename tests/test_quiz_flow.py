import io
import unittest
import json

from PIL import Image
from study_app import app


SAMPLE_AI_RESPONSE = json.dumps([
    {
        "question": "What is Python?",
        "options": ["A snake", "A programming language", "A movie", "A car"],
        "answer": "A programming language",
    },
    {
        "question": "Which keyword defines a function in Python?",
        "options": ["func", "def", "function", "lambda"],
        "answer": "def",
    },
    {
        "question": "What is the output of 1+1?",
        "options": ["1", "2", "11", "Error"],
        "answer": "2",
    },
])


class QuizFlowTests(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_store_generated_quiz_helper(self):
        from study_app import delete_generated_quiz, load_generated_quiz, store_generated_quiz

        quiz_payload = [
            {
                "question": "Sample question?",
                "options": ["A", "B", "C", "D"],
                "answer": "A",
            }
        ]
        quiz_id = store_generated_quiz("tester", "Python", quiz_payload)
        self.assertIsInstance(quiz_id, int)

        loaded_quiz = load_generated_quiz(quiz_id, "tester")
        self.assertEqual(len(loaded_quiz), 1)
        self.assertEqual(loaded_quiz[0]["question"], "Sample question?")
        self.assertEqual(loaded_quiz[0]["answer"], "A")

        delete_generated_quiz(quiz_id, "tester")
        self.assertEqual(load_generated_quiz(quiz_id, "tester"), [])

    def test_generated_quiz_form_uses_native_submit(self):
        with self.app.session_transaction() as sess:
            sess["username"] = "tester"

        import study_app as sa
        original = sa.call_ollama

        try:
            sa.call_ollama = lambda prompt, system_prompt=None: SAMPLE_AI_RESPONSE

            resp = self.app.post("/generate_quiz", data={"topic": "Python", "difficulty": "Easy", "count": "3"}, follow_redirects=True)
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertIn('id="submit-form"', html)
            self.assertIn('action="/submit_quiz"', html)
            self.assertIn('method="post"', html.lower())
            self.assertIn('type="submit"', html)
            self.assertIn('id="submit-btn"', html)
        finally:
            sa.call_ollama = original

    def test_generate_and_submit_quiz_flow(self):
        # set a logged-in user in session
        with self.app.session_transaction() as sess:
            sess["username"] = "tester"

        # monkeypatch call_ollama by injecting into the module globals
        import study_app as sa

        original = sa.call_ollama

        try:
            sa.call_ollama = lambda prompt, system_prompt=None: SAMPLE_AI_RESPONSE

            # generate quiz
            resp = self.app.post("/generate_quiz", data={"topic": "Python", "difficulty": "Easy", "count": "3"}, follow_redirects=True)
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertIn('id="submit-form"', html)
            self.assertIn('action="/submit_quiz"', html)
            # server should have stored quiz_id in session for server-side quiz storage
            with self.app.session_transaction() as sess:
                self.assertIn("quiz_id", sess)
                self.assertIn("quiz_topic", sess)
                quiz_id = sess["quiz_id"]
                self.assertIsInstance(quiz_id, int)
                quiz = sess.get("quiz")
                self.assertIsNotNone(quiz)
                self.assertEqual(len(quiz), 3)

            # load the stored quiz from the generated_quizzes table
            from database import get_db_connection

            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT payload FROM generated_quizzes WHERE id = ?", (quiz_id,))
                row = cursor.fetchone()
            self.assertIsNotNone(row)
            quiz = json.loads(row[0])
            self.assertEqual(len(quiz), 3)

            # submit quiz with correct answers using the server-side stored quiz payload
            data = {f"q{i+1}": quiz[i]["answer"] for i in range(3)}
            resp2 = self.app.post("/submit_quiz", data=data)
            self.assertEqual(resp2.status_code, 200)
            self.assertIn(b"<em>Completed</em>", resp2.data or b"")
            self.assertIn(b"Retake Quiz", resp2.data or b"")

        finally:
            sa.call_ollama = original

    def test_chat_image_attachment_upload(self):
        with self.app.session_transaction() as sess:
            sess["username"] = "tester"

        import study_app as sa
        original = sa.call_ollama

        try:
            sa.call_ollama = lambda prompt, system_prompt=None: "Image attachment handled successfully."

            image_buffer = io.BytesIO()
            image = Image.new("RGB", (32, 32), color="white")
            image.save(image_buffer, format="PNG")
            image_buffer.seek(0)

            response = self.app.post(
                "/chat",
                data={
                    "question": "",
                    "attachment": (image_buffer, "sample.png"),
                },
                content_type="multipart/form-data",
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Image attachment handled successfully.", response.data)
            self.assertIn(b"id=\"fallback-answer\"", response.data)
        finally:
            sa.call_ollama = original


if __name__ == "__main__":
    unittest.main()
