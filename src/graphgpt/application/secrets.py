from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from graphgpt.domain.diagnostics import Diagnostic, GraphGPTError, Severity

REDACTED = "[REDACTED]"
_ENV_REFERENCE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_SENSITIVE_SUFFIXES = (
    "apikey",
    "accesstoken",
    "authtoken",
    "bearertoken",
    "clientsecret",
    "credential",
    "password",
    "secretkey",
    "token",
)
_SENSITIVE_KEYS = frozenset({"authorization", "cookie", "secret", "secrets", "token"})


def validate_secret_config(value: Any, path: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    _scan(value, path, diagnostics)
    return diagnostics


def resolve_environment_refs(value: Any, path: str = "config") -> Any:
    if isinstance(value, str):
        match = _ENV_REFERENCE.fullmatch(value)
        if match:
            name = match.group(1)
            if name not in os.environ:
                raise GraphGPTError(
                    [
                        _error(
                            "SEC-004",
                            path,
                            f"environment variable '{name}' is not set",
                            "Set the variable before compiling or running the workflow.",
                        )
                    ]
                )
            return os.environ[name]
        return value
    if isinstance(value, Mapping):
        return {
            str(key): resolve_environment_refs(item, f"{path}.{key}")
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            resolve_environment_refs(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, tuple):
        return tuple(
            resolve_environment_refs(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    return value


def redact_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if _is_sensitive_key(name) and item is not None and not _is_env_reference(item):
                output[name] = REDACTED
            else:
                output[name] = redact_secrets(item)
        return output
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    if isinstance(value, str) and _has_url_credentials(value):
        return REDACTED
    return value


def _scan(value: Any, path: str, diagnostics: list[Diagnostic]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            item_path = f"{path}.{name}"
            if _is_sensitive_key(name) and item is not None and not _is_env_reference(item):
                diagnostics.append(
                    _error(
                        "SEC-003",
                        item_path,
                        "sensitive configuration must use an ${ENV_VAR} reference",
                        "Move the value to an environment variable and reference its name.",
                    )
                )
            _scan(item, item_path, diagnostics)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan(item, f"{path}[{index}]", diagnostics)
        return
    if not isinstance(value, str):
        return
    if value.startswith("${") and value.endswith("}") and not _is_env_reference(value):
        diagnostics.append(
            _error(
                "SEC-004",
                path,
                "invalid environment reference syntax",
                "Use ${NAME} with letters, numbers, and underscores.",
            )
        )
    if _has_url_credentials(value):
        diagnostics.append(
            _error(
                "SEC-003",
                path,
                "URL credentials are not allowed in workflow configuration",
                "Use separate environment references for provider credentials.",
            )
        )


def _is_env_reference(value: Any) -> bool:
    return isinstance(value, str) and _ENV_REFERENCE.fullmatch(value) is not None


def _is_sensitive_key(key: str) -> bool:
    normalized = "".join(character for character in key.lower() if character.isalnum())
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def _has_url_credentials(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and (
            parsed.username is not None or parsed.password is not None
        )
    except ValueError:
        return False


def _error(code: str, path: str, message: str, hint: str) -> Diagnostic:
    return Diagnostic(
        code=f"GRAPHGPT-{code}",
        severity=Severity.ERROR,
        path=path,
        message=message,
        hint=hint,
    )
