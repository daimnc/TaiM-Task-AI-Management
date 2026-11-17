from flask import Flask, jsonify
from flask_cors import CORS

from config import Config
from errors import register_error_handlers
from firebase import initialize_firebase
from routes import api
from security import firebase_token_verifier


def create_app(db=None, token_verifier=None, enable_v2=None):
    """`db`, `token_verifier` and `enable_v2` are only passed in by the tests. Normal startup uses Firebase and
    reads the TAIM_ENABLE_V2 setting (default: off)."""
    app = Flask(__name__)

    app.config.from_object(Config)
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
