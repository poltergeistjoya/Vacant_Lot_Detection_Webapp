"""Local dev server: the production app plus the color-tuning playground routes.

    uv run --env-file .env uvicorn server.dev:app --reload
"""

from server.app import create_app

app = create_app(playground=True)
