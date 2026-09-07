"""Structured logging.

Emits one JSON object per record in production and a readable line in
development. A ``request_id`` is bound for the duration of each request so a
prediction can be traced end to end across services.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

from app.core.config import settings

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

# Never let these reach the logs, whatever a caller passes in.
_REDACTED_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "token",
    "auth_token",
    "secret",
    "password",
    "credentials",
    "private_key",
    "ngrok_auth_token",
    "gemini_api_key",
    "openai_api_key",
    "anthropic_api_key",
}

_STD_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
    "message",
    "asctime",
}


def new_request_id() -> str:
    """Generate and bind a fresh request id to the current context."""
    rid = uuid.uuid4().hex[:16]
    _request_id.set(rid)
    return rid


def get_request_id() -> str | None:
    """Return the request id bound to the current context, if any."""
    return _request_id.get()


def set_request_id(rid: str | None) -> None:
    """Bind an existing request id (for example from an inbound header)."""
    _request_id.set(rid)


def _redact(value: Any) -> Any:
    """Recursively replace credential-shaped values with a placeholder."""
    if isinstance(value, dict):
        return {
            k: ("***REDACTED***" if k.lower() in _REDACTED_KEYS else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON with redacted extras."""

    def format(self, record: logging.LogRecord) -> str:
        """Render one record as a JSON line."""
        payload: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = get_request_id()
        if rid:
            payload["request_id"] = rid
        for key, val in record.__dict__.items():
            if key not in _STD_ATTRS and not key.startswith("_"):
                payload[key] = _redact(val)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-readable formatter used during development."""

    def format(self, record: logging.LogRecord) -> str:
        """Render one record as a readable line."""
        rid = get_request_id()
        prefix = "[" + rid + "] " if rid else ""
        base = "{ts} {lvl:<7} {pfx}{name}: {msg}".format(
            ts=self.formatTime(record, "%H:%M:%S"),
            lvl=record.levelname,
            pfx=prefix,
            name=record.name,
            msg=record.getMessage(),
        )
        extras = {
            k: _redact(v)
            for k, v in record.__dict__.items()
            if k not in _STD_ATTRS and not k.startswith("_")
        }
        if extras:
            base += "  " + " ".join(f"{k}={v}" for k, v in extras.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging() -> None:
    """Install the root log handler. Idempotent."""
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if settings.log_format == "json" else ConsoleFormatter()
    )
    root.addHandler(handler)
    root.setLevel(settings.log_level)
    # Uvicorn emits access logs through its own handler; avoid duplicates.
    logging.getLogger("uvicorn.access").propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger."""
    return logging.getLogger(name)
