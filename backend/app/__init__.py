"""Flask app factory."""
from __future__ import annotations

import os

from dotenv import load_dotenv
from flask import Flask, render_template

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.config["JSON_SORT_KEYS"] = False

    from .routes.calculator import bp as calc_bp
    app.register_blueprint(calc_bp)

    @app.route("/")
    def index() -> str:
        return render_template("index.html")

    @app.route("/demo")
    def demo() -> str:
        return render_template("demo.html")

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
