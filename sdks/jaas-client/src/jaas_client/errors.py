"""Client-side error types for JaasRegistryClient.

Mirrors the shape of jaas_registry.common.errors.JaasError.to_dict() on the
server side (`{"code", "message", "details"}`) without importing that
package -- this client is deliberately standalone at runtime.
"""

from __future__ import annotations


class JaasClientError(Exception):
    """Base class for every error this client raises."""


class JaasApiError(JaasClientError):
    """The registry responded with an HTTP error status."""

    def __init__(
        self,
        status_code: int,
        code: str | None,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


class JaasNotFoundError(JaasApiError):
    """404 -- the skill/version/file doesn't exist, or isn't visible to this
    caller (the registry deliberately returns 404, not 403, for a private
    skill an unauthorized caller can't see -- see ui-design.md §5.4)."""


class JaasAuthError(JaasApiError):
    """401/403 -- missing, invalid, or insufficient credentials."""
