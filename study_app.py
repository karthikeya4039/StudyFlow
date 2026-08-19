import io
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional, Dict, cast, Sequence

import ollama
import requests
from docx import Document as DocxDocument
from dotenv import load_dotenv
from flask import Flask, flash, make_response, redirect, render_template, request, send_file, session, url_for
from PIL import Image
from pypdf import PdfReader
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate
from werkzeug.datastructures import FileStorage
from werkzeug.security import check_password_hash, generate_password_hash
from xml.sax.saxutils import escape

from database import get_db_connection, initialize_database

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database" / "study.db"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
SECRET_KEY = os.getenv("SECRET_KEY") or os.urandom(24).hex()
AI_MAX_RETRIES = int(os.getenv("AI_MAX_RETRIES", "3"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("study_assistant")

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

initialize_database()


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def parse_quiz_answer(answer: Any, options: list[str]) -> str:
    normalized_answer = normalize_text(answer)
    if not normalized_answer:
        return ""

    if normalized_answer.isdigit():
        index = int(normalized_answer) - 1
        if 0 <= index < len(options):
            return options[index]

    if normalized_answer.upper() in {"A", "B", "C", "D"}:
        index = ord(normalized_answer.upper()) - ord("A")
        if 0 <= index < len(options):
            return options[index]

    for option in options:
        if normalize_text(option).lower() == normalized_answer.lower():
            return option

    return normalized_answer


def store_generated_quiz(username: str, topic: str, quiz: list[dict[str, Any]]) -> int:
    payload = json.dumps(quiz)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO generated_quizzes (username, topic, payload) VALUES (?, ?, ?)",
            (username, topic, payload),
        )
        conn.commit()
        last_id = cursor.lastrowid
        if last_id is None:
            raise RuntimeError("Failed to store generated quiz and obtain its ID.")
        return cast(int, last_id)


def load_generated_quiz(quiz_id: int, username: str) -> list[dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT payload FROM generated_quizzes WHERE id = ? AND username = ?",
            (quiz_id, username),
        )
        row = cursor.fetchone()
    if row is None:
        return []
    try:
        return cast(list[dict[str, Any]], json.loads(row["payload"]))
    except Exception:
        return []


def delete_generated_quiz(quiz_id: int, username: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "DELETE FROM generated_quizzes WHERE id = ? AND username = ?",
            (quiz_id, username),
        )
        conn.commit()


def cleanup_stale_generated_quizzes(max_age_seconds: int = 86400) -> int:
    """Delete generated quizzes older than max_age_seconds and return the number removed."""
    interval = f"-{max_age_seconds} seconds"
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM generated_quizzes WHERE created_at < datetime('now', ?)",
            (interval,),
        )
        deleted = cursor.rowcount
        conn.commit()
    return deleted


def clean_and_fix_json(json_str: str) -> str:
    """
    Best-effort clean of a noisy JSON-like string coming from the AI.
    - Escape unescaped quotes inside string values
    - Attempt to extract the first JSON array or object found
    - Normalize a couple of common formatting mistakes (missing commas between objects, stray code fences)
    Returns a string that can be retried by json.loads.
    """
    if not json_str:
        return ""

    # strip common markdown/code fences
    candidate = re.sub(r'```(?:json)?', '', json_str).strip()

    # try to extract a JSON array first
    m = re.search(r'(\[\s*[\s\S]*\])', candidate)
    if m:
        candidate = m.group(1)

    # basic fixes: ensure objects are comma-separated, escape stray unescaped quotes inside values
    def escape_unquoted_quotes(s: str) -> str:
        parts = s.splitlines()
        out = []
        for line in parts:
            # naive: when a line looks like "key": "some text" we escape internal raw quotes
            if re.match(r"^\s*\".+\"\s*:\s*\".*\"\s*,?\s*$", line):
                key, rest = line.split(':', 1)
                val = rest.strip().rstrip(',')
                # remove surrounding quotes then re-escape
                inner = val[1:-1] if val.startswith('"') and val.endswith('"') else val
                inner_escaped = inner.replace('"', '\\"')
                comma = ',' if line.strip().endswith(',') else ''
                out.append(f"{key}: \"{inner_escaped}\"{comma}")
            else:
                out.append(line)
        return "\n".join(out)

    candidate = escape_unquoted_quotes(candidate)
    candidate = re.sub(r'\}\s*\{', '},\n{', candidate)
    # if options or answers get stuck next to closing brackets, add separator
    candidate = re.sub(r'\]\s*\"(answer|question|options)\"', r'],\n"\1"', candidate)

    return candidate


def ollama_health_check() -> bool:
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return response.status_code == 200
    except requests.RequestException as exc:
        logger.warning("Ollama health check failed: %s", exc)
        return False


def call_ollama(prompt: str, system_prompt: Optional[str] = None, retries: int = AI_MAX_RETRIES) -> str:
    if not ollama_health_check():
        raise RuntimeError("Ollama service is unavailable")

    for attempt in range(1, retries + 1):
        try:
            messages = [{"role": "user", "content": prompt}]
            if system_prompt:
                messages.insert(0, {"role": "system", "content": system_prompt})

            response = ollama.chat(model=OLLAMA_MODEL, messages=messages, options={"num_predict": 2048})
            # Response shape can vary depending on ollama client version: try several fallbacks
            content = None
            try:
                # preferred object shape
                content = getattr(response, "message", None)
                if content is not None and hasattr(content, "content"):
                    content = content.content
            except Exception:
                content = None

            if not content and isinstance(response, dict):
                # try common dict shapes
                resp_dict = cast(Dict[str, Any], response)
                if "message" in resp_dict and isinstance(resp_dict["message"], dict):
                    content = cast(Dict[str, Any], resp_dict["message"]).get("content")
                elif "choices" in resp_dict and isinstance(resp_dict["choices"], list) and resp_dict["choices"]:
                    # e.g. {choices: [{message: {content: ...}}]}
                    first = resp_dict["choices"][0]
                    if isinstance(first, dict):
                        # Safely handle possible shapes where "message" may be a dict or missing
                        first_dict = cast(Dict[str, Any], first)
                        msg = first_dict.get("message")
                        if isinstance(msg, dict):
                            content = cast(Dict[str, Any], msg).get("content")
                        else:
                            content = first_dict.get("content")
                    else:
                        content = None

            if not content and isinstance(response, (list, tuple)) and response:
                # try first element (cast to Sequence for typing)
                resp_seq = cast(Sequence[Any], response)
                first = resp_seq[0]
                # if it's an object-like with .message.content
                if hasattr(first, "message") and hasattr(first.message, "content"):
                    content = first.message.content
                elif isinstance(first, dict):
                    first_dict = cast(Dict[str, Any], first)
                    # prefer nested message content when present
                    msg = first_dict.get("message")
                    if isinstance(msg, dict):
                        content = cast(Dict[str, Any], msg).get("content") or first_dict.get("content")
                    else:
                        content = first_dict.get("content")

            # last resort: stringify response
            if not content:
                try:
                    content = str(response)
                except Exception:
                    content = ""

            content = (content or "").strip()
            if content:
                return content
            raise RuntimeError("AI returned an empty response")
        except Exception as exc:
            logger.warning("Ollama request failed on attempt %s/%s: %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(2)

    raise RuntimeError("Unable to reach the AI service after multiple attempts")


def extract_text_from_file(file_storage: FileStorage) -> tuple[str, Optional[str]]:
    if file_storage is None:
        return "", "No file was provided."

    filename = (file_storage.filename or "").lower()
    allowed_extensions = {
        ".pdf": "PDF",
        ".docx": "DOCX",
        ".txt": "TXT",
        ".png": "PNG",
        ".jpg": "JPG",
        ".jpeg": "JPEG",
        ".gif": "GIF",
    }
    extension = Path(filename).suffix.lower()
    if extension not in allowed_extensions:
        return "", f"Unsupported file type: {extension or 'none'}. Please upload a PDF, DOCX, TXT, or image file (PNG/JPG/GIF)."

    max_bytes = 5 * 1024 * 1024
    file_storage.stream.seek(0, os.SEEK_END)
    file_size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if file_size > max_bytes:
        return "", "The uploaded file is too large. Please keep it under 5MB."

    try:
        if extension == ".pdf":
            reader = PdfReader(file_storage.stream)
            if not reader.pages:
                return "", "No extractable text was found in the PDF."
            text_parts = []
            for page in reader.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
            text = "\n".join(part for part in text_parts if part).strip()
            if not text:
                return "", "No extractable text was found in the PDF."

        elif extension == ".docx":
            document = DocxDocument(file_storage.stream)
            text = "\n".join(paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip())
            if not text:
                return "", "No extractable text was found in the DOCX file."

        elif extension in {".png", ".jpg", ".jpeg", ".gif"}:
            # Ensure stream is at the beginning before opening
            try:
                file_storage.stream.seek(0)
            except Exception:
                # some streams may not support seek; continue and attempt to open
                pass

            try:
                image = Image.open(file_storage.stream)
                width, height = image.size
                format_name = image.format or allowed_extensions[extension]
                mode = image.mode
            except Exception as exc:
                logger.exception("Failed to open image file: %s", exc)
                return "", "The image file could not be processed. Please try another image."
            text_parts = [
                f"Image file detected: {format_name}, {width}x{height}, mode {mode}."
            ]
            extracted_text = ""
            try:
                import pytesseract
                file_storage.stream.seek(0)
                image = Image.open(file_storage.stream)
                extracted_text = pytesseract.image_to_string(image).strip()
            except ImportError:
                extracted_text = ""
            except Exception:
                extracted_text = ""

            if extracted_text:
                text_parts.append("Extracted text from the image:")
                text_parts.append(extracted_text)
            else:
                text_parts.append(
                    "No text could be extracted from the image. "
                    "Answer based on the available metadata and any visible text."
                )
            text = "\n\n".join(text_parts).strip()

        else:
            raw_bytes = file_storage.read()
            try:
                text = raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                text = raw_bytes.decode("latin-1")
            if not text.strip():
                return "", "The text file is empty."

        max_chars = 12000
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[Truncated: content exceeded the maximum length for analysis.]"
        return text, None
    except Exception as exc:
        logger.exception("Failed to extract text from %s: %s", filename, exc)
        return "", "The file could not be read. Please try another file."


def strip_label(text: str) -> str:
    return re.sub(r"^[A-Da-d1-4][.)]\s*", "", text).strip()


def extract_quiz_payload(raw_content: str) -> Optional[list[dict[str, Any]]]:
    """
    Extract a list of question dicts from raw AI output.
    Strategy:
    1. Remove code fences and try to json.loads the first full JSON array seen.
    2. Try to locate a JSON object that contains a "questions" list.
    3. Fallback: scan for individual JSON objects and decode each; return the list of successfully parsed objects (best-effort repair).
    """
    if not raw_content:
        return None

    cleaned_content = re.sub(r"```(?:json)?", "", raw_content).strip()
    if cleaned_content.endswith("```"):
        cleaned_content = cleaned_content[:-3].strip()

    # Primary attempts: array or single object with questions
    for candidate in [cleaned_content, clean_and_fix_json(cleaned_content)]:
        try:
            match = re.search(r"\[[\s\S]*\]", candidate)
            if match:
                parsed = json.loads(match.group())
                if isinstance(parsed, list):
                    return parsed

            match_object = re.search(r"\{[\s\S]*\}", candidate)
            if match_object:
                parsed_object = json.loads(match_object.group())
                if isinstance(parsed_object, dict) and isinstance(parsed_object.get("questions"), list):
                    return parsed_object["questions"]
        except json.JSONDecodeError as exc:
            logger.warning("Quiz payload parsing failed: %s", exc)

    # Fallback heuristic: attempt to find and parse individual JSON objects inside the text.
    # This helps recover when the model truncated the array or returned extra text.
    objects = re.findall(r"\{[\s\S]*?\}", cleaned_content)
    recovered = []
    for o in objects:
        try:
            j = json.loads(o)
            if isinstance(j, dict) and all(k in j for k in ("question", "options", "answer")):
                recovered.append(j)
        except Exception:
            # ignore objects that aren't valid JSON
            continue

    if recovered:
        return recovered

    return None


def login_required(view_func):
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    wrapped.__name__ = view_func.__name__
    return wrapped


@app.before_request
def log_request():
    logger.info("%s %s", request.method, request.path)


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    logger.info("%s %s -> %s", request.method, request.path, response.status_code)
    return response


@app.errorhandler(404)
def page_not_found(_):
    return render_template("quiz_error.html", message="The requested page could not be found."), 404


@app.errorhandler(500)
def server_error(_):
    return render_template("quiz_error.html", message="A server error occurred. Please try again later."), 500


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = normalize_text(request.form.get("username", ""))
        password = request.form.get("password", "")

        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("register.html")

        if len(username) < 3 or len(password) < 6:
            flash("Username must be at least 3 characters and password at least 6 characters.", "error")
            return render_template("register.html")

        hashed_password = generate_password_hash(password)
        try:
            with get_db_connection() as conn:
                conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
                conn.commit()
            flash("Account created! Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already taken. Please choose another.", "error")
        except Exception as exc:
            logger.exception("Registration failed: %s", exc)
            flash("Registration failed. Please try again.", "error")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = normalize_text(request.form.get("username", ""))
        password = request.form.get("password", "")

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()

        if user and check_password_hash(user[2], password):
            session.clear()
            session["username"] = username
            return redirect(url_for("home"))

        flash("Invalid username or password. Please try again.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return render_template("logout.html")


@app.route("/")
def home():
    if "username" not in session:
        return redirect(url_for("login"))
    return render_template("index.html", username=session["username"])


@app.route("/chat", methods=["GET", "POST"])
@login_required
def chat():
    answer = ""

    if request.method == "POST":
        question = normalize_text(request.form.get("question", ""))
        attachment = request.files.get("attachment")
        attachment_name = None
        extracted_text = ""
        error_message = None

        if attachment and attachment.filename:
            attachment_name = attachment.filename
            extracted_text, error_message = extract_text_from_file(attachment)
            if error_message:
                answer = error_message
            else:
                if question:
                    prompt = (
                        "Here is the content of an uploaded document:\n\n"
                        f"{extracted_text}\n\n"
                        f"User question: {question}"
                    )
                else:
                    prompt = extracted_text

        if not answer and (question or extracted_text):
            try:
                if attachment_name and not question:
                    system_prompt = (
                        "You are an expert assistant that can read documents and describe images. "
                        "If the attached file contains text, summarize the content clearly and concisely. "
                        "If it is an image, describe the visible content, any detected text, and the overall meaning. "
                        "Keep the answer helpful and easy to understand."
                    )
                else:
                    system_prompt = (
                        "You are an expert AI tutor and programming instructor. "
                        "Always answer educational questions clearly and accurately. "
                        "Use simple English and provide examples where helpful."
                    )
                answer = call_ollama(prompt if attachment_name else question, system_prompt=system_prompt)
                with get_db_connection() as conn:
                    history_question = question or f"[Uploaded file: {attachment_name}]"
                    conn.execute(
                        "INSERT INTO chat_history (username, question, answer) VALUES (?, ?, ?)",
                        (session["username"], history_question, answer),
                    )
                    conn.commit()
            except Exception as exc:
                logger.exception("Chat generation failed: %s", exc)
                answer = (
                    "⚠️ The AI service is currently unavailable. "
                    "Please try again in a moment."
                )
        elif not answer:
            answer = "Please enter a question or attach a file."

    response = make_response(render_template("chat.html", answer=answer))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/notes", methods=["GET", "POST"])
@login_required
def notes():
    if request.method == "POST":
        title = normalize_text(request.form.get("title", ""))
        content = request.form.get("content", "").strip()

        if not title or not content:
            flash("Title and content are required.", "error")
        else:
            with get_db_connection() as conn:
                conn.execute(
                    "INSERT INTO notes (title, content, username) VALUES (?, ?, ?)",
                    (title, content, session["username"]),
                )
                conn.commit()
            flash("Note saved successfully.", "success")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM notes WHERE username = ? ORDER BY id DESC", (session["username"],))
        all_notes = cursor.fetchall()

    return render_template("notes.html", notes=all_notes)


@app.route("/download_note/<int:note_id>")
@login_required
def download_note(note_id: int):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT title, content FROM notes WHERE id = ? AND username = ?",
            (note_id, session["username"]),
        )
        note = cursor.fetchone()

    if note is None:
        flash("Note not found.", "error")
        return redirect(url_for("notes"))

    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(note[0]), styles["Title"]), Preformatted(note[1], styles["Code"])]
    pdf.build(story)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name=f"{note[0]}.pdf", mimetype="application/pdf")


@app.route("/delete/<int:note_id>")
@login_required
def delete_note(note_id: int):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM notes WHERE id = ? AND username = ?", (note_id, session["username"]))
        conn.commit()
    return redirect(url_for("notes"))


@app.route("/edit/<int:note_id>", methods=["GET", "POST"])
@login_required
def edit_note(note_id: int):
    if request.method == "POST":
        title = normalize_text(request.form.get("title", ""))
        content = request.form.get("content", "").strip()

        if not title or not content:
            flash("Title and content are required.", "error")
        else:
            with get_db_connection() as conn:
                conn.execute(
                    "UPDATE notes SET title = ?, content = ? WHERE id = ? AND username = ?",
                    (title, content, note_id, session["username"]),
                )
                conn.commit()
            return redirect(url_for("notes"))

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM notes WHERE id = ? AND username = ?", (note_id, session["username"]))
        note = cursor.fetchone()

    if note is None:
        flash("Note not found.", "error")
        return redirect(url_for("notes"))

    return render_template("edit.html", note=note)


@app.route("/quiz")
@login_required
def quiz():
    return render_template("quiz.html")


@app.route("/generate_quiz", methods=["POST"])
@login_required
def generate_quiz():
    topic = normalize_text(request.form.get("topic", "Python")) or "Python"
    difficulty = normalize_text(request.form.get("difficulty", "Easy")) or "Easy"

    try:
        count = int(request.form.get("count", "5"))
        count = max(1, min(count, 20))
    except (TypeError, ValueError):
        count = 5

    if not ollama_health_check():
        return render_template(
            "quiz_error.html",
            message="AI service is offline. Please ensure Ollama is running and the model is installed, then try again.",
        )

    prompt = f"""Generate EXACTLY {count} multiple-choice questions.

Topic: {topic}
Difficulty: {difficulty}

Return ONLY valid JSON — no markdown, no code fences, no explanations.

Format:
[
  {{
    "question": "Question text here",
    "options": [
      "First option",
      "Second option",
      "Third option",
      "Fourth option"
    ],
    "answer": "Correct option text (must exactly match one of the options)"
  }}
]

Rules:
- Exactly {count} questions.
- Exactly 4 options per question.
- The answer field must exactly match one of the 4 options.
- No labels like A. B. C. D. or a) b) c) d) — just the plain option text.
- No markdown. No code fences. No comments. No extra text outside the JSON."""

    system_prompt = "You are a helpful quiz generation assistant. Return only valid JSON in the requested format."

    try:
        raw_content = call_ollama(prompt, system_prompt=system_prompt)
    except Exception as exc:
        logger.exception("Quiz generation failed: %s", exc)
        # If the underlying exception indicates Ollama, surface that specifically
        msg = str(exc) or "AI service error"
        return render_template("quiz_error.html", message=f"AI service error: {msg}")

    # attempt to parse the AI output (with repair)
    quiz_payload = extract_quiz_payload(raw_content)
    if not quiz_payload:
        snippet = (raw_content or "").strip()[:800]
        return render_template(
            "quiz_error.html",
            message=(
                f"The AI returned output that could not be parsed as valid quiz JSON for '{topic}'.\n"
                f"Raw response (truncated): {snippet}"
            ),
        )

    collected = []
    for question in quiz_payload:
        if not isinstance(question, dict):
            continue
        if not all(key in question for key in ("question", "options", "answer")):
            continue
        if not isinstance(question["options"], list) or len(question["options"]) != 4:
            continue

        options = [strip_label(str(option).strip()) for option in question["options"]]
        answer = parse_quiz_answer(question.get("answer", ""), options)
        if not answer:
            continue

        collected.append(
            {
                "question": str(question["question"]).strip(),
                "options": options,
                "answer": answer,
                "topic": topic,
            }
        )
        if len(collected) >= count:
            break

    if not collected:
        return render_template(
            "quiz_error.html",
            message=f"Could not extract any valid questions for '{topic}'. Try a different topic or try again later.",
        )

    if len(collected) < count:
        # If the AI produced fewer valid questions than requested, allow the quiz
        # to proceed with what we have and notify the user rather than failing.
        flash(
            f"The AI produced only {len(collected)} valid questions out of the {count} requested for '{topic}'. Using the {len(collected)} valid questions.",
            "warning",
        )

    cleanup_stale_generated_quizzes()
    quiz_data = collected[:count]
    quiz_id = store_generated_quiz(session["username"], topic, quiz_data)
    session["quiz_id"] = quiz_id
    session["quiz_topic"] = topic
    session["quiz"] = quiz_data
    return redirect(url_for("generated_quiz"))


@app.route("/generated_quiz")
@login_required
def generated_quiz():
    """Render the generated quiz via GET so the browser can land on a safe GET URL.
    This lets client-side JS replace the POST URL after generation (avoids 405 on reload).
    """
    topic = session.get("quiz_topic", "AI Quiz")
    quiz_id = None
    try:
        quiz_id = int(session.get("quiz_id", 0))
    except (TypeError, ValueError):
        quiz_id = None

    quiz = []
    if quiz_id is not None:
        quiz = load_generated_quiz(quiz_id, session["username"])

    if not quiz:
        quiz = session.get("quiz", [])

    if not quiz:
        flash("No quiz found. Please generate a new quiz.", "error")
        return redirect(url_for("quiz"))

    return render_template("generated_quiz.html", quiz=quiz)


@app.route("/submit_quiz", methods=["POST"])
@login_required
def submit_quiz():
    topic = session.get("quiz_topic", "AI Quiz")
    quiz_id = None
    try:
        quiz_id = int(session.get("quiz_id", 0))
    except (TypeError, ValueError):
        quiz_id = None

    quiz = []
    if quiz_id is not None:
        quiz = load_generated_quiz(quiz_id, session["username"])

    if not quiz:
        quiz = session.get("quiz", [])
        if quiz and isinstance(quiz, list):
            flash(
                "Using fallback quiz data from session. Please generate a new quiz soon.",
                "warning",
            )

    if not quiz:
        flash("No quiz found. Please generate a new quiz.", "error")
        return redirect(url_for("quiz"))

    score = 0
    results = []

    for index, question in enumerate(quiz):
        user_answer = normalize_text(request.form.get(f"q{index + 1}", ""))
        correct_answer = normalize_text(question.get("answer", ""))
        is_correct = user_answer.lower() == correct_answer.lower()
        if is_correct:
            score += 1

        results.append(
            {
                "question": question["question"],
                "user_answer": user_answer if user_answer else "(Not answered)",
                "correct_answer": correct_answer,
                "is_correct": is_correct,
            }
        )

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO quiz_history (username, topic, score, total) VALUES (?, ?, ?, ?)",
            (session["username"], topic, score, len(quiz)),
        )
        conn.commit()

    if quiz_id is not None:
        delete_generated_quiz(quiz_id, session["username"])

    session.pop("quiz_id", None)
    session.pop("quiz", None)
    session.pop("quiz_topic", None)

    return render_template("quiz_result.html", score=score, total=len(quiz), results=results)


@app.route("/dashboard")
@login_required
def dashboard():
    username = session["username"]

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM notes WHERE username = ?", (username,))
        notes_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM quiz_history WHERE username = ?", (username,))
        quiz_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM chat_history WHERE username = ?", (username,))
        ai_count = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(DISTINCT day) FROM (
                SELECT DATE(quiz_date) AS day FROM quiz_history WHERE username = ?
                UNION ALL
                SELECT DATE(chat_date) AS day FROM chat_history WHERE username = ?
            )
            """,
            (username, username),
        )
        streak = cursor.fetchone()[0]
    india_time = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    hour = india_time.hour
    if hour < 12:
        greeting = "Good Morning ☀️"
    elif hour < 18:
        greeting = "Good Afternoon 🌤️"
    else:
        greeting = "Good Evening 🌙"

    return render_template(
        "dashboard.html",
        total_notes=notes_count,
        total_quiz=quiz_count,
        ai_count=ai_count,
        streak=streak,
        greeting=greeting,
    )


@app.route("/chat_history")
@login_required
def chat_history():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT question, answer, chat_date FROM chat_history WHERE username = ? ORDER BY id DESC",
            (session["username"],),
        )
        chats = cursor.fetchall()

    return render_template("chat_history.html", chats=chats)


if __name__ == "__main__":
    app.run(debug=True)
