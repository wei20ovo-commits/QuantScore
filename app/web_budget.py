"""Request-wide remaining-time budget propagated through cached loaders."""
from contextvars import ContextVar

from app.web_diagnostics import WebDataError


_remaining = ContextVar('web_request_remaining_budget', default=None)


def bind_remaining(callback):
    return _remaining.set(callback)


def reset_remaining(token):
    _remaining.reset(token)


def remaining_seconds(default):
    callback = _remaining.get()
    if callback is None:
        return default
    return min(default, max(0.0, float(callback())))


def require_remaining(default=240):
    remaining = remaining_seconds(default)
    if remaining <= 0:
        raise WebDataError(
            '本次分析已达到请求时限，不展示迟到的新评分。',
            {'reason_code': 'WEB_REQUEST_DEADLINE_EXCEEDED'},
        )
    return remaining
