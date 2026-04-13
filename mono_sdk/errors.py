"""
Structured error types for the mono API.

Each error maps 1:1 to an HTTP error code from the settle/nodes endpoints.
Catch specific errors for granular handling, or catch MonoError for all.
"""


class MonoError(Exception):
    """Base error for all mono SDK exceptions."""

    def __init__(self, message: str, code: str = "UNKNOWN", status_code: int = 0, detail: str | None = None):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"[{code}] {message}" + (f" — {detail}" if detail else ""))


class AuthenticationError(MonoError):
    """API key is missing, invalid, or revoked. (HTTP 401)"""
    def __init__(self, message: str = "Invalid or missing API key", **kwargs):
        super().__init__(message, code="INVALID_API_KEY", status_code=401, **kwargs)


class NodeLockedError(MonoError):
    """Node has been killed/locked. No transfers allowed. (HTTP 423)"""
    def __init__(self, message: str = "Node is locked", **kwargs):
        super().__init__(message, code="NODE_LOCKED", status_code=423, **kwargs)


class InsufficientBalanceError(MonoError):
    """Sender balance too low for the requested transfer. (HTTP 422)"""
    def __init__(self, message: str = "Insufficient balance", **kwargs):
        super().__init__(message, code="INSUFFICIENT_BALANCE", status_code=422, **kwargs)


class SpendingLimitExceededError(MonoError):
    """Transfer amount exceeds the node's per-transaction spending limit. (HTTP 422)"""
    def __init__(self, message: str = "Spending limit exceeded", **kwargs):
        super().__init__(message, code="SPENDING_LIMIT_EXCEEDED", status_code=422, **kwargs)


class RecipientNotFoundError(MonoError):
    """The target node_id does not exist. (HTTP 404)"""
    def __init__(self, message: str = "Recipient node not found", **kwargs):
        super().__init__(message, code="RECIPIENT_NOT_FOUND", status_code=404, **kwargs)


class SystemHaltedError(MonoError):
    """Circuit breaker is active. All payments paused. (HTTP 503)

    The SDK will automatically retry with exponential backoff when this
    error is encountered, up to `max_retries` attempts.
    """
    def __init__(self, message: str = "System halted — circuit breaker active", **kwargs):
        super().__init__(message, code="SYSTEM_HALTED", status_code=503, **kwargs)


class DailyBudgetExceededError(MonoError):
    """Transfer would exceed the node's daily budget. (HTTP 422)"""
    def __init__(self, message: str = "Daily budget exceeded", **kwargs):
        super().__init__(message, code="DAILY_BUDGET_EXCEEDED", status_code=422, **kwargs)


class RateLimitError(MonoError):
    """Too many requests. Back off and retry. (HTTP 429)"""
    def __init__(self, message: str = "Rate limit exceeded", **kwargs):
        super().__init__(message, code="RATE_LIMIT", status_code=429, **kwargs)


class NetworkError(MonoError):
    """Connection failed, timeout, DNS resolution error, etc."""
    def __init__(self, message: str = "Network error", **kwargs):
        super().__init__(message, code="NETWORK_ERROR", status_code=0, **kwargs)


ERROR_MAP: dict[str, type[MonoError]] = {
    "INVALID_API_KEY":        AuthenticationError,
    "MISSING_API_KEY":        AuthenticationError,
    "AUTH_REQUIRED":          AuthenticationError,
    "NODE_LOCKED":            NodeLockedError,
    "SENDER_NODE_LOCKED":     NodeLockedError,
    "INSUFFICIENT_BALANCE":   InsufficientBalanceError,
    "SPENDING_LIMIT_EXCEEDED":SpendingLimitExceededError,
    "DAILY_BUDGET_EXCEEDED":  DailyBudgetExceededError,
    "RECIPIENT_NOT_FOUND":    RecipientNotFoundError,
    "SYSTEM_HALTED":          SystemHaltedError,
    "RATE_LIMIT":             RateLimitError,
}


def raise_for_error(status_code: int, body: dict) -> None:
    """Parse an API error response and raise the appropriate exception."""
    # FastAPI wraps HTTPException dicts in {"detail": {...}}
    detail_val = body.get("detail")
    if isinstance(detail_val, dict):
        body = detail_val
    code    = body.get("code") or body.get("error") or body.get("message") or "UNKNOWN"
    message = body.get("message", str(body))
    detail  = body.get("detail") if isinstance(body.get("detail"), str) else None
    exc_class = ERROR_MAP.get(code, MonoError)
    raise exc_class(message=message, detail=detail)
