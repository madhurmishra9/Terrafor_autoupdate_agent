"""Structured logging with credential masking.

Never log Authorization headers, tokens, or passwords. The mask_secrets filter
redacts common credential patterns before any record is emitted.
"""
from __future__ import annotations

import logging
import os
import re
import sys

_SECRET_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"(Basic\s+)[A-Za-z0-9+/=]+", re.IGNORECASE),
    re.compile(r"(ghp_|ghs_|github_pat_)[A-Za-z0-9_]+"),
    re.compile(r"(token=)[^&\s]+", re.IGNORECASE),
    re.compile(r"(password=)\S+", re.IGNORECASE),
    re.compile(r"(api[_-]?token[\"'=:\s]+)[A-Za-z0-9._\-]+", re.IGNORECASE),
]

_REDACTED = "***REDACTED***"


class _MaskSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._mask(record.msg)
        if record.args:
            record.args = tuple(
                self._mask(a) if isinstance(a, str) else a for a in record.args
            )
        return True

    @staticmethod
    def _mask(text: str) -> str:
        for pat in _SECRET_PATTERNS:
            text = pat.sub(lambda m: m.group(1) + _REDACTED, text)
        return text


def configure_logging() -> None:
    """Configure root logging once. Idempotent."""
    root = logging.getLogger()
    if getattr(root, "_tf_code_updater_configured", False):
        return

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    handler.addFilter(_MaskSecretsFilter())
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root._tf_code_updater_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
