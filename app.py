"""Entry point for Vercel and `python app.py` (local dev on :5001)."""
import os

if os.path.exists(os.path.join(os.path.dirname(__file__), ".env")):
    from dotenv import load_dotenv

    load_dotenv()

from countjar import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5001)
