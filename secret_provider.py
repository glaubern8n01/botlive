from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping, Optional, Protocol

from publisher_contract import AuthenticationError


class SecretProvider(Protocol):
    def resolve(self, secret_ref: str) -> Mapping[str, str]: ...


class EnvironmentSecretProvider:
    """Resolve ``env:NAME`` without ever logging the resulting value."""

    prefix = "env:"

    def resolve(self, secret_ref: str) -> Mapping[str, str]:
        if not secret_ref.startswith(self.prefix):
            raise AuthenticationError("unsupported environment secret reference")
        name = secret_ref[len(self.prefix) :]
        raw = os.getenv(name)
        if not raw:
            raise AuthenticationError(f"environment secret is not configured: {name}")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {"token": raw}
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(item, str) for key, item in value.items()
        ):
            raise AuthenticationError(f"environment secret must be a string map: {name}")
        return value


class LocalTokenSecretProvider:
    """Compatibility provider restricted to BotLive's existing ``.tokens`` root."""

    prefix = "local-token:"

    def __init__(self, tokens_root: Optional[Path] = None) -> None:
        self.tokens_root = (
            tokens_root or Path(__file__).resolve().parent / ".tokens"
        ).resolve()

    def resolve(self, secret_ref: str) -> Mapping[str, str]:
        if not secret_ref.startswith(self.prefix):
            raise AuthenticationError("unsupported local token reference")
        relative = Path(secret_ref[len(self.prefix) :])
        if relative.is_absolute() or ".." in relative.parts:
            raise AuthenticationError("invalid local token reference")
        path = (self.tokens_root / relative).resolve()
        if self.tokens_root not in path.parents:
            raise AuthenticationError("local token reference escapes token root")
        if not path.is_file():
            raise AuthenticationError("local token file is not configured")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AuthenticationError("local token file is invalid") from exc
        if not isinstance(value, dict):
            raise AuthenticationError("local token must contain an object")
        return {str(key): str(item) for key, item in value.items() if item is not None}


class CompositeSecretProvider:
    def __init__(self, *providers: SecretProvider) -> None:
        self.providers = providers

    def resolve(self, secret_ref: str) -> Mapping[str, str]:
        for provider in self.providers:
            prefix = getattr(provider, "prefix", None)
            if prefix and secret_ref.startswith(prefix):
                return provider.resolve(secret_ref)
        raise AuthenticationError("no provider accepts this secret reference")
