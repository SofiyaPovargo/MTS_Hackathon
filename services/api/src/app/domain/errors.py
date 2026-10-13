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


class ValidationFailed(DomainError):
    pass
