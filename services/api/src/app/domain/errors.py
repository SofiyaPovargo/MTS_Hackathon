"""Domain errors mapped to HTTP responses in ``app.api.errors``."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all business-rule violations."""


class InvalidStateTransition(DomainError):
    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        super().__init__(f"invalid call transition: {current} -> {target}")


class ConsentRequired(DomainError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"recording is not allowed: {reason}")


class PermissionDenied(DomainError):
    pass


class NotFound(DomainError):
    pass


class Conflict(DomainError):
    pass


class UploadOffsetMismatch(Conflict):
    """A chunk arrived out of order; the client must resume at ``expected_offset``."""

    def __init__(self, expected_offset: int, total: int) -> None:
        self.expected_offset = expected_offset
        self.total = total
        super().__init__(
            f"upload offset mismatch: expected {expected_offset} of {total} bytes"
        )


class ValidationFailed(DomainError):
    pass


class PayloadTooLarge(DomainError):
    def __init__(self, limit_bytes: int) -> None:
        self.limit_bytes = limit_bytes
        super().__init__(f"payload exceeds the {limit_bytes} byte limit")
