"""Magnet identity is separate from native share URL identity."""
from urllib.parse import parse_qs, urlsplit
import base64
import re


def magnet_key(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.casefold() != "magnet":
            return ""
        for xt in parse_qs(parsed.query).get("xt", []):
            prefix, _, digest = xt.rpartition(":")
            if prefix.casefold() != "urn:btih":
                continue
            if re.fullmatch(r"[a-fA-F0-9]{40}", digest):
                return digest.lower()
            if re.fullmatch(r"[a-zA-Z2-7]{32}", digest):
                return base64.b32decode(digest.upper()).hex()
    except (ValueError, UnicodeError):
        pass
    return ""


def magnet_title(value: str) -> str:
    return str((parse_qs(urlsplit(value).query).get("dn") or [""])[0]) if magnet_key(value) else ""
