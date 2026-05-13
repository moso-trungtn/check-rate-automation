import json
from pathlib import Path

import pytest

from app.moso.headers import HeadersMissing, load_headers


def test_load_headers(tmp_path: Path) -> None:
    p = tmp_path / "h.json"
    p.write_text(json.dumps({"XSRF": "abc", "user": "u@x", "Cookie": "k=v"}))
    h = load_headers(p)
    assert h["XSRF"] == "abc"
    assert h["user"] == "u@x"
    assert h["Cookie"] == "k=v"


def test_load_headers_missing(tmp_path: Path) -> None:
    with pytest.raises(HeadersMissing):
        load_headers(tmp_path / "nope.json")
