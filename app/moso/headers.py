"""Load MOSO session headers from a JSON file."""
from __future__ import annotations

import json
from pathlib import Path


class HeadersMissing(FileNotFoundError):
    pass


def load_headers(path: Path) -> dict[str, str]:
    if not path.exists():
        raise HeadersMissing(
            f"MOSO headers file not found at {path}. "
            "Populate it by copying DevTools request headers — see docs/moso-endpoint-recon.md."
        )
    data: dict[str, object] = json.loads(path.read_text())
    return {str(k): str(v) for k, v in data.items()}
