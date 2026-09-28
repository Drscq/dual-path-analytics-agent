"""Runtime configuration: API key lookup and model ids.

The key is never written to disk by this project and never printed. Lookup order:
1. the GEMINI_API_KEY environment variable;
2. the macOS login keychain item with service name GEMINI_API_KEY.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

KEY_NAME = "GEMINI_API_KEY"

_SETUP_HINT = (
    f"No Gemini API key found. Either export {KEY_NAME}, or store it in the macOS keychain:\n"
    f'  security add-generic-password -a "$USER" -s {KEY_NAME} -T "" -w'
)


class MissingApiKeyError(RuntimeError):
    pass


def _read_keychain(service: str) -> str | None:
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:  # not macOS
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def load_api_key() -> str:
    """Return the Gemini API key, or raise MissingApiKeyError with setup instructions."""
    key = os.environ.get(KEY_NAME, "").strip() or _read_keychain(KEY_NAME)
    if not key:
        raise MissingApiKeyError(_SETUP_HINT)
    return key


@dataclass(frozen=True)
class Models:
    """Model ids for the two paths. Override with DPA_FAST_MODEL / DPA_SLOW_MODEL."""

    fast: str
    slow: str

    @classmethod
    def from_env(cls) -> Models:
        return cls(
            fast=os.environ.get("DPA_FAST_MODEL", "gemini-3.8-flash"),
            slow=os.environ.get("DPA_SLOW_MODEL", "gemini-3.1-pro-preview"),
        )
