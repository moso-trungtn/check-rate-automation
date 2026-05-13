"""Encrypted credentials store (Fernet + scrypt-derived key)."""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


class BadPassphrase(RuntimeError):
    pass


class MissingStore(FileNotFoundError):
    pass


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str
    notes: str | None = None


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


_SALT_BYTES = 16


class CredentialsStore:
    def __init__(self, path: Path, passphrase: str) -> None:
        self.path = path
        self._passphrase = passphrase

    def save(self, creds: dict[str, Credentials]) -> None:
        salt = os.urandom(_SALT_BYTES)
        key = _derive_key(self._passphrase, salt)
        payload = json.dumps(
            {
                k: {"username": v.username, "password": v.password, "notes": v.notes}
                for k, v in creds.items()
            }
        ).encode("utf-8")
        token = Fernet(key).encrypt(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(salt + token)

    def _load(self) -> dict[str, Credentials]:
        if not self.path.exists():
            raise MissingStore(f"No credentials file at {self.path}")
        raw = self.path.read_bytes()
        salt, token = raw[:_SALT_BYTES], raw[_SALT_BYTES:]
        key = _derive_key(self._passphrase, salt)
        try:
            plain = Fernet(key).decrypt(token)
        except InvalidToken as e:
            raise BadPassphrase("Wrong passphrase or corrupted store") from e
        data: dict[str, dict[str, str | None]] = json.loads(plain)
        return {
            k: Credentials(
                username=str(v["username"]),
                password=str(v["password"]),
                notes=v.get("notes"),
            )
            for k, v in data.items()
        }

    def get(self, lender: str) -> Credentials:
        return self._load()[lender]
