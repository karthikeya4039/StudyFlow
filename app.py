from study_app import (
    app,
    clean_and_fix_json,
    normalize_text,
    parse_quiz_answer,
)
from database import initialize_database

init_db = initialize_database

__all__ = ["app", "clean_and_fix_json", "normalize_text", "parse_quiz_answer", "init_db"]

if __name__ == "__main__":
    app.run(debug=True)
