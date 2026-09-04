from __future__ import annotations

from flask import Flask

from app.db import init_db
from app.routes import api


def create_app(db_path: str = "data/ats.db") -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

    init_db(db_path)
    app.register_blueprint(api)

    # Minimal same-origin-friendly CORS for local dev, where the static
    # frontend is served on a different port than the Flask API. No
    # flask-cors dependency needed for this scope.
    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    return app
