import urllib.request

from app.core.config import get_settings


def open_url(request: str | urllib.request.Request, *, timeout: int):
    """Open an outbound request through the optional configured proxy."""
    proxy_url = get_settings().proxy_url.strip()
    if not proxy_url:
        return urllib.request.urlopen(request, timeout=timeout)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    )
    return opener.open(request, timeout=timeout)
