"""One JSON error format for the whole API: {"detail": "<text>"}.

The frontend (client.js) reads `detail` and shows it to the student, so it is always plain text.
Validation errors also include an `errors` object with one message per field.
"""
from flask import jsonify
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    def __init__(self, status, detail, errors=None, headers=None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.errors = errors
        self.headers = headers or {}


def error_response(status, detail, errors=None, headers=None):
    body = {"detail": detail}
    if errors:
        body["errors"] = errors
    response = jsonify(body)
    response.status_code = status
    for key, value in (headers or {}).items():
        response.headers[key] = value
    return response


_HTTP_MESSAGES = {
    404: "Not found.",
    405: "Method not allowed.",
    413: "Request body is too large.",
}


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error.status, error.detail, error.errors, error.headers)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return error_response(error.code, _HTTP_MESSAGES.get(error.code, error.description))

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.exception("Unhandled error")
        return error_response(500, "Something went wrong on the server.")
