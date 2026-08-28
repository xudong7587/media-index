import ipaddress
import urllib.parse
import urllib.request

from app.core.config import get_settings


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Do not forward API credentials to a server-selected redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ARG002
        return None


def open_url(
    request: str | urllib.request.Request,
    *,
    timeout: int,
    use_proxy: bool = True,
    proxy_url_override: str | None = None,
):
    """Open an outbound API request without following redirects."""
    handlers: list[urllib.request.BaseHandler] = [NoRedirectHandler()]
    proxy_url = (
        str(proxy_url_override).strip()
        if proxy_url_override is not None
        else get_settings().proxy_url.strip()
    ) if use_proxy else ""
    if not use_proxy or _is_local_destination(request):
        # Never send Docker service names, loopback or LAN API calls through an
        # Internet proxy, even when the host forgot to configure NO_PROXY.
        handlers.append(urllib.request.ProxyHandler({}))
    elif proxy_url:
        handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    opener = urllib.request.build_opener(*handlers)
    return opener.open(request, timeout=timeout)


def _is_local_destination(request: str | urllib.request.Request) -> bool:
    url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
    hostname = (urllib.parse.urlparse(url).hostname or "").strip().casefold()
    if not hostname:
        return False
    if hostname in {"localhost", "host.docker.internal"} or hostname.endswith(".local") or "." not in hostname:
        return True
    try:
        return ipaddress.ip_address(hostname).is_private or ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False
