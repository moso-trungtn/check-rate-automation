"""Tests for the cURL → headers parser."""

from __future__ import annotations

import pytest

from app.moso.curl_parser import CurlParseError, parse_curl_to_headers

_SAMPLE_CURL = """curl 'https://www.viet18.com/exec/GetRatesOp' \\
  -H 'accept: */*' \\
  -H 'accept-language: en-US,en;q=0.9' \\
  -H 'content-type: application/json; charset=UTF-8' \\
  -b 'ftv=true; JSESSIONID=rZoT65; extend_session=178' \\
  -H 'origin: https://www.viet18.com' \\
  -H 'referer: https://www.viet18.com/pricing/qm' \\
  -H 'user: chauchau.inc@gmail.com' \\
  -H 'user-agent: Mozilla/5.0' \\
  -H 'x-property: version=20260513;X-Use-Enum-Ordinal=1' \\
  -H 'x-sdk-namespace: 5716104026521600' \\
  -H 'xsrf: dc113607-1dd7-4ae5-a94d-bae232e6c354' \\
  --data-raw '{"get_all_rates":true}'
"""


def test_parse_extracts_session_headers() -> None:
    headers = parse_curl_to_headers(_SAMPLE_CURL)
    assert headers["XSRF"] == "dc113607-1dd7-4ae5-a94d-bae232e6c354"
    assert headers["user"] == "chauchau.inc@gmail.com"
    assert headers["X-SDK-Namespace"] == "5716104026521600"
    assert headers["x-property"] == "version=20260513;X-Use-Enum-Ordinal=1"
    assert headers["Referer"] == "https://www.viet18.com/pricing/qm"
    assert headers["Origin"] == "https://www.viet18.com"
    assert headers["Cookie"] == "ftv=true; JSESSIONID=rZoT65; extend_session=178"
    # Allowlist drops the irrelevant request headers
    assert "accept" not in {k.lower() for k in headers}
    assert "accept-language" not in {k.lower() for k in headers}


def test_parse_canonical_capitalization() -> None:
    headers = parse_curl_to_headers(_SAMPLE_CURL)
    # Verify we used the canonical names, not the lowercase versions from curl
    assert "XSRF" in headers
    assert "xsrf" not in headers
    assert "X-SDK-Namespace" in headers
    assert "x-sdk-namespace" not in headers


def test_parse_rejects_empty() -> None:
    with pytest.raises(CurlParseError):
        parse_curl_to_headers("")


def test_parse_rejects_non_curl() -> None:
    with pytest.raises(CurlParseError) as ei:
        parse_curl_to_headers("just some random text without the c-word")
    assert "cURL" in str(ei.value)


def test_parse_warns_when_session_headers_missing() -> None:
    # Only Authorization → no session headers expected. No warning.
    api_key_curl = (
        "curl 'https://x/exec/op' "
        "-H 'authorization: Bearer abc123' "
        "-H 'content-type: application/json'"
    )
    h = parse_curl_to_headers(api_key_curl)
    assert h["Authorization"] == "Bearer abc123"
    assert "__warning__" not in h


def test_parse_warns_when_no_auth() -> None:
    # Has cookie but no XSRF or user → warning embedded
    partial = (
        "curl 'https://x/exec/op' "
        "-b 'session=abc' "
        "-H 'content-type: application/json'"
    )
    h = parse_curl_to_headers(partial)
    assert "__warning__" in h
    assert "XSRF" in h["__warning__"]


def test_parse_rejects_when_no_relevant_headers() -> None:
    # Only headers that are NOT in our allowlist
    irrelevant = (
        "curl 'https://x/foo' -H 'accept: image/png' -H 'sec-fetch-dest: image'"
    )
    with pytest.raises(CurlParseError) as ei:
        parse_curl_to_headers(irrelevant)
    assert "MOSO-relevant" in str(ei.value)
