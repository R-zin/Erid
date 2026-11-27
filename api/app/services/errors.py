"""Domain errors raised by services.

Services don't know about HTTP; the REST layer maps these to status codes in
``app.main`` and the MCP endpoint turns them into tool errors.
"""


class ServiceError(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFound(ServiceError):
    status_code = 404


class Conflict(ServiceError):
    status_code = 409


class Forbidden(ServiceError):
    status_code = 403


class Unprocessable(ServiceError):
    status_code = 422
