"""Token-based authentication for relay connections.

Clients (mobile app, local STT pipe, etc.) must present a valid token
to send commands. Tokens are generated during pairing and persisted
to disk so they survive restarts.
"""

import hashlib
import json
import logging
import secrets
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_FILE = Path.home() / ".nymble" / "paired_devices.json"


class TokenStore:
    """Manages authentication tokens for paired devices."""

    def __init__(self, path: Path = DEFAULT_TOKEN_FILE):
        self._path = path
        self._tokens: dict[str, dict] = {}  # token_hash -> device info
        self._load()

    def _load(self):
        """Load tokens from disk."""
        if self._path.exists():
            try:
                self._tokens = json.loads(self._path.read_text())
                logger.info("Loaded %d paired device(s)", len(self._tokens))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load token file: %s", e)
                self._tokens = {}

    def _save(self):
        """Persist tokens to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._tokens, indent=2))

    @staticmethod
    def _hash_token(token: str) -> str:
        """Hash a token for storage (we don't store plaintext)."""
        return hashlib.sha256(token.encode()).hexdigest()

    def generate_token(self, device_name: str = "Unknown") -> str:
        """Generate a new auth token for a device. Returns the plaintext token."""
        token = secrets.token_urlsafe(32)
        token_hash = self._hash_token(token)
        self._tokens[token_hash] = {
            "name": device_name,
            "created": time.time(),
            "last_used": None,
        }
        self._save()
        logger.info("Generated token for device: %s", device_name)
        return token

    def validate(self, token: str) -> str | None:
        """Validate a token. Returns the device name if valid, None otherwise.

        Updates last_used timestamp on success. Reloads from disk in case
        another process added a token while we're running.
        """
        token_hash = self._hash_token(token)
        device = self._tokens.get(token_hash)

        if not device:
            # Reload from disk — another process may have added tokens
            self._load()
            device = self._tokens.get(token_hash)

        if device:
            device["last_used"] = time.time()
            self._save()
            return device["name"]
        return None

    def revoke(self, token: str) -> bool:
        """Revoke a token. Returns True if it existed."""
        token_hash = self._hash_token(token)
        if token_hash in self._tokens:
            del self._tokens[token_hash]
            self._save()
            return True
        return False

    def revoke_all(self):
        """Revoke all tokens."""
        self._tokens = {}
        self._save()

    def list_devices(self) -> list[dict]:
        """List all paired devices (without exposing token hashes)."""
        return [
            {"name": info["name"], "created": info["created"], "last_used": info["last_used"]}
            for info in self._tokens.values()
        ]

    @property
    def count(self) -> int:
        return len(self._tokens)
