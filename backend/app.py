from flask import Flask, jsonify
from flask_cors import CORS

from ai_provider import RateLimiter, provider_from_config
from config import Config
from errors import register_error_handlers
from firebase import initialize_firebase
from routes import api
from security import firebase_token_verifier


_FROM_CONFIG = object()


def create_app(db=None, token_verifier=None, enable_v2=None, ai_provider=_FROM_CONFIG):
    """`db`, `token_verifier`, `enable_v2` and `ai_provider` are only passed in by the tests. Normal startup uses
    Firebase, reads the TAIM_ENABLE_V2 setting (default: off) and builds the Groq -> Gemini provider chain from backend/.env
    (None = AI off, so the built-in template is always used)."""
    app = Flask(__name__)

    app.config.from_object(Config)
    app.config.pop("GEMINI_API_KEY", None)  # API keys live only inside provider objects, never in app.config
    app.config.pop("GROQ_API_KEY", None)
    if enable_v2 is not None:
        app.config["ENABLE_V2"] = bool(enable_v2)

    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": Config.CORS_ORIGINS,
                "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                "allow_headers": ["Authorization", "Content-Type"],
                "max_age": 600
            }
        }
    )

    # Firebase is initialized once, inside firebase.py. Routes get Firestore from here.
    app.extensions["taim_db"] = db if db is not None else initialize_firebase()
    app.extensions["taim_token_verifier"] = token_verifier or firebase_token_verifier
    app.extensions["taim_ai"] = provider_from_config(Config) if ai_provider is _FROM_CONFIG else ai_provider
    app.extensions["taim_ai_limiter"] = RateLimiter(Config.AI_RATE_PER_MINUTE, Config.AI_RATE_PER_DAY)
    app.extensions["taim_insights_limiter"] = RateLimiter(Config.INSIGHTS_RATE_PER_MINUTE, Config.INSIGHTS_RATE_PER_DAY)
    app.extensions["taim_planner_limiter"] = RateLimiter(Config.PLANNER_ASSIST_RATE_PER_MINUTE, Config.PLANNER_ASSIST_RATE_PER_DAY)

    register_error_handlers(app)

    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({
            "status": "success",
            "message": "TAiM backend is running."
        }), 200

    app.register_blueprint(api)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=app.config["DEBUG"]
    )
