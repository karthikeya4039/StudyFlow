import json
import subprocess
import sys
import traceback
from study_app import app
from database import get_db_connection

SAMPLE_AI_RESPONSE = json.dumps([
    {"question": "What is Python?", "options": ["A snake", "A programming language", "A movie", "A car"], "answer": "A programming language"},
    {"question": "Which keyword defines a function in Python?", "options": ["func", "def", "function", "lambda"], "answer": "def"},
    {"question": "What is the output of 1+1?", "options": ["1", "2", "11", "Error"], "answer": "2"},
])

routes_to_check = [
    '/',
    '/login',
    '/register',
    '/quiz',
    '/notes',
    '/dashboard',
    '/chat',
    '/logout',
]

results = {
    'routes': [],
    'generate_quiz': None,
    'submit_quiz': None,
    'tests': None,
}

print('Starting automated health check...')

# Monkeypatch AI call to deterministic sample
import study_app as sa
original_call = getattr(sa, 'call_ollama', None)
sa.call_ollama = lambda prompt, system_prompt=None: SAMPLE_AI_RESPONSE

try:
    with app.test_client() as client:
        # set a logged in user for protected routes
        with client.session_transaction() as sess:
            sess['username'] = 'tester'

        # Check main routes
        for r in routes_to_check:
            try:
                resp = client.get(r)
                status = resp.status_code
                content = resp.get_data(as_text=True) or ''
                error_markers = ('Traceback', 'Exception', 'Error', 'TemplateNotFound')
                contains_error = any(m in content for m in error_markers)
                snippet = content[:800] if contains_error else ''
                results['routes'].append({'route': r, 'status': status, 'error_in_content': contains_error, 'snippet': snippet})
                print(f'GET {r} -> {status}, error_in_content={contains_error}')
                if contains_error:
                    print('--- snippet ---')
                    print(snippet)
                    print('--- end snippet ---')
            except Exception as e:
                print(f'GET {r} -> EXCEPTION: {e}')
                results['routes'].append({'route': r, 'status': 'EXCEPTION', 'error': str(e)})

        # Generate quiz
        try:
            # Diagnostic: print cookies and session before POST
            try:
                cj = list(client.cookie_jar)
                print('Client cookie_jar before generate_quiz:', cj)
            except Exception:
                print('Could not read client.cookie_jar')
            try:
                with client.session_transaction() as sess_diag:
                    print('Session before generate_quiz:', {k: sess_diag.get(k) for k in sess_diag.keys()})
            except Exception:
                print('Could not read session before generate_quiz')

            gen = client.post('/generate_quiz', data={'topic':'Python','difficulty':'Easy','count':'3'}, follow_redirects=False)
            print('/generate_quiz ->', gen.status_code)
            results['generate_quiz'] = gen.status_code
            # capture redirect target and headers when generation returns a redirect
            if gen.status_code in (301, 302, 303, 307, 308):
                loc = gen.headers.get('Location')
                results['generate_quiz_location'] = loc
                results['generate_quiz_headers'] = dict(gen.headers)
                print('/generate_quiz redirected to:', loc)
                # Diagnostic: print cookies and session after redirect
                try:
                    cj2 = list(client.cookie_jar)
                    print('Client cookie_jar after generate_quiz redirect:', cj2)
                except Exception:
                    print('Could not read client.cookie_jar after redirect')
                try:
                    with client.session_transaction() as sess_diag2:
                        print('Session after generate_quiz redirect:', {k: sess_diag2.get(k) for k in sess_diag2.keys()})
                except Exception:
                    print('Could not read session after generate_quiz redirect')

                # Retry with explicit session set to emulate logged-in state
                try:
                    with client.session_transaction() as sess_set:
                        sess_set['username'] = 'tester'
                    print('Manually set session.username and retrying /generate_quiz')
                    gen2 = client.post('/generate_quiz', data={'topic':'Python','difficulty':'Easy','count':'3'}, follow_redirects=False)
                    print('Retry /generate_quiz ->', gen2.status_code)
                    results['generate_quiz_retry_status'] = gen2.status_code
                    if gen2.status_code in (301,302,303,307,308):
                        results['generate_quiz_retry_location'] = gen2.headers.get('Location')
                        print('Retry redirected to:', gen2.headers.get('Location'))
                except Exception as e:
                    print('Retry with explicit session failed:', e)
            # get quiz
            with client.session_transaction() as sess:
                quiz_id = sess.get('quiz_id')
                quiz = sess.get('quiz')
            if not quiz and quiz_id:
                with get_db_connection() as conn:
                    c = conn.cursor()
                    c.execute('SELECT payload FROM generated_quizzes WHERE id = ?', (quiz_id,))
                    row = c.fetchone()
                    if row:
                        quiz = json.loads(row[0])
            if not quiz:
                print('No quiz produced')
            else:
                print('Quiz length:', len(quiz))
                # submit answers
                data = {f'q{i+1}': quiz[i].get('answer') for i in range(len(quiz))}
                sub = client.post('/submit_quiz', data=data)
                print('/submit_quiz ->', sub.status_code)
                results['submit_quiz'] = sub.status_code
                body = sub.get_data(as_text=True)
                ok = ('Retake Quiz' in body) or ('Completed' in body) or ('Score' in body)
                print('Result page markers present:', ok)
        except Exception as e:
            print('generate/submit exception:', e)
            traceback.print_exc()
            results['generate_quiz'] = 'EXCEPTION'

    # Run unit tests
    print('\nRunning unit tests (unittest discover)...')
    try:
        # Run targeted test module first
        p1 = subprocess.run([sys.executable, '-m', 'unittest', 'tests.test_quiz_flow'], capture_output=True, text=True, timeout=120)
        print('Targeted tests exit code:', p1.returncode)
        print(p1.stdout)
        if p1.stderr:
            print('TARGETED TESTS STDERR:\n', p1.stderr)
        results['targeted_tests'] = {'returncode': p1.returncode, 'output': p1.stdout, 'errors': p1.stderr}

        # Then fallback to full discovery (may be environment-dependent)
        p2 = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-v'], capture_output=True, text=True, timeout=120)
        print('Discover tests exit code:', p2.returncode)
        print(p2.stdout)
        if p2.stderr:
            print('DISCOVER TESTS STDERR:\n', p2.stderr)
        results['tests'] = {'discover_returncode': p2.returncode, 'discover_output': p2.stdout, 'discover_errors': p2.stderr}
    except Exception as e:
        print('Running tests failed:', e)
        results['tests'] = {'error': str(e)}

except Exception as e:
    print('Health check failed:', e)
    traceback.print_exc()
finally:
    if original_call is not None:
        sa.call_ollama = original_call

print('\nHealth check summary:')
print(json.dumps(results, indent=2))
print('Health check complete.')
