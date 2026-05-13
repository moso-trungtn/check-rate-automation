"""Application settings (env-driven)."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    moso_base_url: str
    moso_headers_file: Path
    compare_tolerance: Decimal = Field(default=Decimal("0.001"))
    check_rate_passphrase: str | None = None
    data_dir: Path = Path("data")
