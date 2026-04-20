import json
import logging
import sys
from datetime import datetime, timezone

_SKIP_FIELDS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
})

# Fields that must be truncated to prevent sensitive data leaking into logs
_MAX_LOG_VALUE_LEN = 120


def safe_log(value: str, max_len: int = _MAX_LOG_VALUE_LEN) -> str:
    """Truncate user-controlled strings before including in log records."""
    if not isinstance(value, str):
        value = str(value)
    return value[:max_len] + ("…" if len(value) > max_len else "")


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k not in _SKIP_FIELDS:
                payload[k] = v
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Quiet noisy third-party libs
    for noisy in ("sqlalchemy.engine", "httpx", "openai", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
