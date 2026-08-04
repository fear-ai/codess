"""Versioned resource-limit policy resolution for ingestion."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping


RESOURCE_POLICY_FORMAT = "codess.resource-policy/1"

BUILTIN_MAXIMUMS: dict[str, int] = {
    "transcript_bytes": 256 * 1024**2,
    "cursor_container_bytes": 10 * 1024**3,
    "events_per_source": 200_000,
    "events_per_session": 100_000,
    "context_content_chars": 250_000,
}


class ResourcePolicyError(ValueError):
    """A resource-policy file or override is not usable."""


@dataclass(frozen=True)
class ResourcePolicy:
    """Resolved maximums and the provenance of every effective value."""

    maximums: dict[str, int | None]
    origins: dict[str, str]
    file_path: str | None = None
    file_sha256: str | None = None

    def with_overrides(
        self,
        values: Mapping[str, int | None],
        *,
        origin: str,
    ) -> "ResourcePolicy":
        maximums = dict(self.maximums)
        origins = dict(self.origins)
        for key, value in values.items():
            _validate_limit(key, value)
            maximums[key] = value
            origins[key] = origin
        return replace(self, maximums=maximums, origins=origins)

    def disabled(self, *, origin: str) -> "ResourcePolicy":
        return self.with_overrides(
            {key: None for key in BUILTIN_MAXIMUMS},
            origin=origin,
        )

    def report(self) -> dict[str, Any]:
        return {
            "format": RESOURCE_POLICY_FORMAT,
            "file": self.file_path,
            "file_sha256": self.file_sha256,
            "effective_maximums": dict(self.maximums),
            "origins": dict(self.origins),
        }


def _validate_limit(key: str, value: Any) -> None:
    if key not in BUILTIN_MAXIMUMS:
        raise ResourcePolicyError(f"unknown maximum {key!r}")
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResourcePolicyError(f"maximum {key!r} must be an integer or null")
    if value <= 0:
        raise ResourcePolicyError(f"maximum {key!r} must be greater than zero")


def load_resource_policy(path: str | Path | None = None) -> ResourcePolicy:
    """Load a partial policy over built-ins and retain its exact file identity."""
    maximums: dict[str, int | None] = dict(BUILTIN_MAXIMUMS)
    origins = {key: "built-in" for key in BUILTIN_MAXIMUMS}
    if path is None:
        return ResourcePolicy(maximums=maximums, origins=origins)

    policy_path = Path(path).expanduser().resolve()
    try:
        payload = policy_path.read_bytes()
    except OSError as exc:
        raise ResourcePolicyError(f"cannot read {policy_path}: {exc}") from exc
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResourcePolicyError(f"cannot decode {policy_path} as UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ResourcePolicyError("policy root must be a JSON object")
    unknown_root = set(value) - {"format", "maximums"}
    if unknown_root:
        raise ResourcePolicyError(
            "unknown policy field(s): " + ", ".join(sorted(unknown_root))
        )
    if value.get("format") != RESOURCE_POLICY_FORMAT:
        raise ResourcePolicyError(
            f"format must be {RESOURCE_POLICY_FORMAT!r}"
        )
    if "maximums" not in value:
        raise ResourcePolicyError("policy must contain maximums")
    overrides = value["maximums"]
    if not isinstance(overrides, dict):
        raise ResourcePolicyError("maximums must be a JSON object")
    for key, limit in overrides.items():
        _validate_limit(key, limit)
        maximums[key] = limit
        origins[key] = "policy-file"
    return ResourcePolicy(
        maximums=maximums,
        origins=origins,
        file_path=str(policy_path),
        file_sha256=hashlib.sha256(payload).hexdigest(),
    )
