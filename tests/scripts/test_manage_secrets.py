from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from app.secrets.store import CredentialsStore
from scripts.manage_secrets import cli


def test_add_and_list(tmp_path: Path) -> None:
    runner = CliRunner()
    path = tmp_path / "creds.enc"
    r1 = runner.invoke(
        cli,
        [
            "--path",
            str(path),
            "--passphrase",
            "pw",
            "add",
            "ad_mortgage",
            "--username",
            "u",
            "--password",
            "p",
        ],
    )
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(cli, ["--path", str(path), "--passphrase", "pw", "list"])
    assert "ad_mortgage" in r2.output

    store = CredentialsStore(path=path, passphrase="pw")
    c = store.get("ad_mortgage")
    assert c.username == "u"
    assert c.password == "p"


def test_remove(tmp_path: Path) -> None:
    runner = CliRunner()
    path = tmp_path / "creds.enc"
    runner.invoke(
        cli,
        [
            "--path",
            str(path),
            "--passphrase",
            "pw",
            "add",
            "x",
            "--username",
            "u",
            "--password",
            "p",
        ],
    )
    r = runner.invoke(cli, ["--path", str(path), "--passphrase", "pw", "remove", "x"])
    assert r.exit_code == 0
    r2 = runner.invoke(cli, ["--path", str(path), "--passphrase", "pw", "list"])
    assert "x" not in r2.output
