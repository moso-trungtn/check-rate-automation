from pathlib import Path

import pytest

from app.secrets.store import (
    BadPassphrase,
    Credentials,
    CredentialsStore,
    MissingStore,
)


def test_encrypt_decrypt_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "creds.enc"
    store = CredentialsStore(path=path, passphrase="hunter2")
    store.save({"ad_mortgage": Credentials(username="u", password="p")})
    again = CredentialsStore(path=path, passphrase="hunter2")
    creds = again.get("ad_mortgage")
    assert creds.username == "u" and creds.password == "p"


def test_wrong_passphrase_rejected(tmp_path: Path) -> None:
    path = tmp_path / "creds.enc"
    CredentialsStore(path=path, passphrase="right").save(
        {"ad_mortgage": Credentials(username="u", password="p")}
    )
    bad = CredentialsStore(path=path, passphrase="wrong")
    with pytest.raises(BadPassphrase):
        bad.get("ad_mortgage")


def test_missing_file_raises(tmp_path: Path) -> None:
    store = CredentialsStore(path=tmp_path / "missing.enc", passphrase="x")
    with pytest.raises(MissingStore):
        store.get("anything")
