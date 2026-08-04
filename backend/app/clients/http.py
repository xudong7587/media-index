import urllib.request

from app.core.config import get_settings


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Do not forward API credentials to a server-selected redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ARG002
        return None


def open_url(request: str | urllib.request.Request, *, timeout: int, use_proxy: bool = True):
    """Open an outbound API request without following redirects."""
    handlers: list[urllib.request.BaseHandler] = [NoRedirectHandler()]
    proxy_url = get_settings().proxy_url.strip() if use_proxy else ""
    if proxy_url:
        handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    opener = urllib.request.build_opener(*handlers)
    return opener.open(request, timeout=timeout)
