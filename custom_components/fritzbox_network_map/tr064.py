"""Shared TR-064 SOAP transport and HTTP Digest authentication helpers."""

from __future__ import annotations

import hashlib
import re
import secrets
from urllib.parse import urlsplit


async def async_tr064_request(
    *, session, username: str, password: str, url: str, service: str,
    action: str, soap_body: str, auth_error_cls: type[Exception],
) -> str:
    """Perform a TR-064 SOAP request, retrying with HTTP Digest when challenged."""
    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPAction": f'"{service}#{action}"',
    }
    async with session.post(
        url, data=soap_body.encode("utf-8"), headers=headers, timeout=20
    ) as response:
        if response.status != 401:
            response.raise_for_status()
            return await response.text()
        challenge = response.headers.get("WWW-Authenticate", "")

    auth_header = digest_authorization(
        challenge=challenge, method="POST", url=url,
        username=username, password=password,
    )
    if not auth_header:
        raise auth_error_cls("TR-064-Digest-Anmeldung wird von der FRITZ!Box nicht angeboten.")

    headers["Authorization"] = auth_header
    async with session.post(
        url, data=soap_body.encode("utf-8"), headers=headers, timeout=20
    ) as response:
        if response.status in (401, 403):
            raise auth_error_cls("TR-064-Anmeldung fehlgeschlagen oder Benutzerrechte fehlen.")
        response.raise_for_status()
        return await response.text()


def digest_authorization(
    *, challenge: str, method: str, url: str, username: str, password: str
) -> str | None:
    """Build the HTTP Digest Authorization header from a FRITZ!Box challenge."""
    if not challenge.lower().startswith("digest "):
        return None
    params = {
        key.lower(): (quoted_value or unquoted_value)
        for key, quoted_value, unquoted_value in re.findall(
            r'(\w+)\s*=\s*(?:"([^"]*)"|([^,\s]+))', challenge
        )
    }
    realm = params.get("realm")
    nonce = params.get("nonce")
    if not realm or not nonce:
        return None

    qop_values = params.get("qop", "auth").replace('"', "").split(",")
    qop = "auth" if "auth" in qop_values else qop_values[0]
    parsed = urlsplit(url)
    uri = parsed.path or "/"
    if parsed.query:
        uri += "?" + parsed.query
    nc = "00000001"
    cnonce = secrets.token_hex(8)

    def md5(value: str) -> str:
        return hashlib.md5(value.encode("utf-8")).hexdigest()

    ha1 = md5(f"{username}:{realm}:{password}")
    if params.get("algorithm", "MD5").upper() == "MD5-SESS":
        ha1 = md5(f"{ha1}:{nonce}:{cnonce}")
    ha2 = md5(f"{method}:{uri}")
    response = md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    parts = [
        f'username="{username}"',
        f'realm="{realm}"',
        f'nonce="{nonce}"',
        f'uri="{uri}"',
        f'response="{response}"',
        f"qop={qop}",
        f"nc={nc}",
        f'cnonce="{cnonce}"',
    ]
    if params.get("opaque"):
        parts.append(f'opaque="{params["opaque"]}"')
    if params.get("algorithm"):
        parts.append(f'algorithm={params["algorithm"]}')
    return "Digest " + ", ".join(parts)
