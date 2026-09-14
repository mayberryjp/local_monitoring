"""Domain-level error type for downstream check failures."""

from __future__ import annotations


class CheckError(Exception):
    """Raised when a downstream check cannot be completed."""

    def __init__(self, code: str, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
