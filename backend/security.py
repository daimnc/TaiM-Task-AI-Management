"""Authentication. Every protected route uses @require_auth.

The student's identity comes ONLY from the verified Firebase ID token (g.uid).
Nothing the client sends in the URL, query string, headers or body is ever used as the user ID.
"""
from functools import wraps

from firebase_admin import auth as firebase_auth
from flask import current_app, g, request

from errors import ApiError

_BEARER = {"WWW-Authenticate": "Bearer"}


def firebase_token_verifier(token):
    """Verify a Firebase ID token with the Admin SDK. Returns the decoded claims (includes 'uid')."""
    return firebase_auth.verify_id_token(token, clock_skew_seconds=10)


def _bearer_token():
    parts = request.headers.get("Authorization", "").split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def require_auth(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        token = _bearer_token()
        if not token:
            raise ApiError(401, "Missing or malformed Authorization header. Use: Bearer <token>.", headers=_BEARER)

        if current_app.extensions.get("taim_db") is None:
            raise ApiError(503, "The server is not connected to Firebase. Check FIREBASE_PROJECT_ID and keys/serviceAccount.json.")

        verifier = current_app.extensions["taim_token_verifier"]
        try:
            claims = verifier(token)
        except firebase_auth.CertificateFetchError:
            raise ApiError(503, "Could not reach Firebase to verify your sign-in. Please try again.")
        except Exception as error:  # invalid, expired, revoked, wrong project, malformed...
            current_app.logger.info("Token rejected: %s", type(error).__name__)
            raise ApiError(401, "Invalid or expired token. Please sign in again.", headers=_BEARER)

        uid = claims.get("uid") if isinstance(claims, dict) else None
        if not isinstance(uid, str) or not uid:
            raise ApiError(401, "Invalid or expired token. Please sign in again.", headers=_BEARER)

        g.uid = uid
        g.user_claims = claims
        return view(*args, **kwargs)

    return wrapper
