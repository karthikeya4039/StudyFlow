import json
from study_app import app
from database import get_db_connection

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

print('Starting automated verification...')

# Monkeypatch call_ollama inside study_app module
import study_app as sa
original = sa.call_ollama
sa.call_ollama = lambda prompt, system_prompt=None: SAMPLE_AI_RESPONSE

try:
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['username'] = 'tester'

        # Generate quiz
        resp = client.post('/generate_quiz', data={'topic':'Python','difficulty':'Easy','count':'3'})
        print('generate_quiz status:', resp.status_code)
        html = resp.get_data(as_text=True)
        print('submit button found in HTML:', 'Submit Test' in html or '/submit_quiz' in html)

        # get quiz_id from session
        with client.session_transaction() as sess:
            quiz_id = sess.get('quiz_id')
            print('session quiz_id:', quiz_id)

        # load stored quiz from DB if present
        quiz = None
        if quiz_id:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT payload FROM generated_quizzes WHERE id = ?', (quiz_id,))
                row = cursor.fetchone()
                if row:
                    quiz = json.loads(row[0])
                    print('loaded quiz from DB, length:', len(quiz))

        if not quiz:
            with client.session_transaction() as sess:
                quiz = sess.get('quiz')
                print('loaded quiz from session, length:', len(quiz) if quiz else None)

        # prepare submission data
        data = {}
        for i, q in enumerate(quiz):
            data[f'q{i+1}'] = q.get('answer')

        # Submit quiz
        resp2 = client.post('/submit_quiz', data=data)
        print('submit_quiz status:', resp2.status_code)
        body = resp2.get_data(as_text=True)
        ok = ('Retake Quiz' in body) or ('Completed' in body) or ('Score' in body)
        print('result page contains expected markers:', ok)
        if not ok:
            print('Result page snippet:\n', body[:400])

finally:
    sa.call_ollama = original

print('Verification complete.')
