# Zip.AiStudy

A Flask-based study assistant with note-taking, quiz generation, and AI chat powered by Ollama.

## Features
- User authentication and session-based access
- Personal notes with PDF export
- AI chat for study questions
- Quiz generation and quiz history

## Setup
1. Create and activate a virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy .env.example to .env and adjust the values.
4. Start Ollama and ensure the configured model is available.
5. Run the app:
   ```bash
   python app.py
   ```

## Environment variables
- SECRET_KEY: Flask session secret key
- OLLAMA_URL: Ollama server URL
- OLLAMA_MODEL: Model name used for chat and quiz generation
- AI_MAX_RETRIES: Number of AI retries before failing

## Testing
Run:
```bash
python -m unittest discover -s tests
```
