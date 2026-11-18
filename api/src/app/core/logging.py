import logging
import logging.config
import traceback
from pathlib import Path
from types import TracebackType

from pythonjsonlogger import json

from app.core.context import get_request_id


def safe_exception_details(
    exception_type: type[BaseException] | None, exception_traceback: TracebackType | None
) -> dict[str, object]:
    """Keep diagnostic locations without exception messages, source, or locals."""
    return {
        "exception_type": exception_type.__name__ if exception_type else "Exception",
        "exception_frames": [
            {"filename": Path(frame.filename).name, "function": frame.name, "lineno": frame.lineno}
            for frame in traceback.extract_tb(exception_traceback)
        ],
    }


class RequestContextFilter(logging.Filter):
    """Attach request identifiers to every emitted log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Enrich a record without suppressing it."""
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id() or "-"

        if record.exc_info is not None:
            exception_type, _, exception_traceback = record.exc_info
            record.__dict__.update(safe_exception_details(exception_type, exception_traceback))
            record.exc_info = None
        record.exc_text = None
        return True


def configure_logging(level: str = "INFO") -> None:
    """Configure structured application and server logging on standard output."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_context": {"()": RequestContextFilter}},
            "formatters": {
                "json": {
                    "()": json.JsonFormatter,
                    "format": (
                        "%(asctime)s %(name)s %(levelname)s %(message)s %(module)s %(request_id)s"
                    ),
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "filters": ["request_context"],
                    "formatter": "json",
                    "level": level,
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"handlers": ["console"], "level": level},
            "loggers": {
                "httpx": {"level": "WARNING"},
                "neo4j": {"level": "WARNING"},
                "langgraph": {"level": "WARNING"},
                "langchain": {"level": "WARNING"},
                "langsmith": {"level": "WARNING"},
                "httpcore": {"level": "WARNING"},
                "sqlalchemy.engine": {"level": "WARNING"},
                "uvicorn": {
                    "handlers": ["console"],
                    "level": level,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": [],
                    "level": level,
                    "propagate": True,
                },
                "uvicorn.access": {
                    "handlers": [],
                    "level": level,
                    "propagate": False,
                },
            },
        }
    )
