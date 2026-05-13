"""Parse a Chrome DevTools 'Copy as cURL' string into a MOSO headers dict.

Only headers relevant to MOSO authentication are kept (XSRF, user,
X-SDK-Namespace, x-property, Cookie, Referer, Origin, Content-Type,
User-Agent). All other request flags (--data, --compressed, accept,
sec-*, priority, etc.) are ignored.

Case-insensitive matching on the curl side; the output uses canonical
casing that the MOSO server / our existing config expects.
"""
from __future__ import annotations

import re


class CurlParseError(ValueError):
    pass


# Canonical capitalization for the header keys we care about.
# Any header whose lower-cased name is NOT a key here is dropped.
_ALLOWLIST: dict[str, str] = {
    "xsrf": "XSRF",
    "user": "user",
    "x-sdk-namespace": "X-SDK-Namespace",
    "x-property": "x-property",
    "referer": "Referer",
    "origin": "Origin",
    "user-agent": "User-Agent",
    "content-type": "Content-Type",
    "authorization": "Authorization",
}

_REQUIRED = ("XSRF", "user", "Cookie")  # at minimum we expect these for a session

# -H 'Name: Value' or -H "Name: Value"
_HEADER_RE = re.compile(
    r"""-H\s+(?P<q>['"])(?P<name>[^:]+?):\s*(?P<value>.*?)(?P=q)""",
    re.DOTALL,
)
# -b 'cookie=...; ...'  or  --cookie 'cookie=...'
_COOKIE_RE = re.compile(
    r"""(?:^|\s)(?:-b|--cookie)\s+(?P<q>['"])(?P<value>.*?)(?P=q)""",
    re.DOTALL,
)


def parse_curl_to_headers(curl_text: str) -> dict[str, str]:
    """Extract MOSO-relevant headers from a 'Copy as cURL' string.

    Returns a dict ready to be written to ``data/moso-headers.json``.

    Raises ``CurlParseError`` if the input does not look like a curl
    invocation or does not contain at least one MOSO auth header.
    """
    text = curl_text.strip()
    if not text:
        raise CurlParseError("Empty input.")
    if "curl" not in text[:200]:
        raise CurlParseError(
            "Doesn't look like a cURL command — paste the full 'Copy as cURL' "
            "string starting with `curl ...`."
        )

    headers: dict[str, str] = {}
    for m in _HEADER_RE.finditer(text):
        name = m.group("name").strip().lower()
        value = m.group("value").strip()
        canonical = _ALLOWLIST.get(name)
        if canonical and value:
            headers[canonical] = value

    cookie_match = _COOKIE_RE.search(text)
    if cookie_match:
        headers["Cookie"] = cookie_match.group("value").strip()

    if not headers:
        raise CurlParseError(
            "Found no MOSO-relevant headers (XSRF, user, Cookie, X-SDK-Namespace, "
            "x-property). Make sure you copied the GetRatesOp request, not a "
            "static asset like an image or font."
        )

    # Warn (via a marker key) when a likely-needed header is missing, so the
    # caller / UI can surface it. We DO NOT raise — the user might be using
    # API-key auth which doesn't need XSRF/Cookie.
    missing = [h for h in _REQUIRED if h not in headers]
    if missing and "Authorization" not in headers:
        # Embed warning into the result via a special key the route strips
        # out before saving. Avoids tuple-return ceremony.
        headers["__warning__"] = (
            f"Missing typical session headers: {', '.join(missing)}. "
            "If you're using an API key, set the Authorization header instead. "
            "Otherwise capture a fresh GetRatesOp from a logged-in browser."
        )
    return headers
