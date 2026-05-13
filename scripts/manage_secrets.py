"""CLI to manage data/credentials.enc."""
from __future__ import annotations

from pathlib import Path

import click

from app.secrets.store import Credentials, CredentialsStore, MissingStore


@click.group()
@click.option("--path", required=True, type=click.Path(dir_okay=False, path_type=Path))
@click.option("--passphrase", required=True, envvar="CHECK_RATE_PASSPHRASE")
@click.pass_context
def cli(ctx: click.Context, path: Path, passphrase: str) -> None:
    ctx.obj = CredentialsStore(path=path, passphrase=passphrase)


def _load_all(store: CredentialsStore) -> dict[str, Credentials]:
    try:
        return store._load()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    except MissingStore:
        return {}


@cli.command()
@click.argument("lender")
@click.option("--username", required=True)
@click.option("--password", required=True)
@click.option("--notes", default=None)
@click.pass_obj
def add(
    store: CredentialsStore,
    lender: str,
    username: str,
    password: str,
    notes: str | None,
) -> None:
    all_creds = _load_all(store)
    all_creds[lender] = Credentials(username=username, password=password, notes=notes)
    store.save(all_creds)
    click.echo(f"saved {lender}")


@cli.command()
@click.argument("lender")
@click.pass_obj
def remove(store: CredentialsStore, lender: str) -> None:
    all_creds = _load_all(store)
    all_creds.pop(lender, None)
    store.save(all_creds)
    click.echo(f"removed {lender}")


@cli.command(name="list")
@click.pass_obj
def list_(store: CredentialsStore) -> None:
    for name in sorted(_load_all(store)):
        click.echo(name)


if __name__ == "__main__":
    cli()
