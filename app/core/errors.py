"""Structured errors. Services raise these; Telegram shows `user_message`, never a traceback."""
from __future__ import annotations


class HubError(Exception):
    code = "error"
    recoverable = False

    def __init__(self, user_message: str, *, detail: str = "", code: str | None = None) -> None:
        super().__init__(detail or user_message)
        self.user_message = user_message
        self.detail = detail
        if code:
            self.code = code


class NotFound(HubError):
    code = "not_found"


class Forbidden(HubError):
    code = "forbidden"


class ApprovalRequired(HubError):
    code = "approval_required"


class InvalidInput(HubError):
    code = "invalid_input"


class Conflict(HubError):
    code = "conflict"


class Recoverable(HubError):
    """Temporary failure (network, rate limit). The scheduler may retry it."""
    code = "recoverable"
    recoverable = True


class ProviderUnavailable(Recoverable):
    code = "provider_unavailable"
