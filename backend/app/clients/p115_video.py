"""115 cloud HLS transport. No downloads, account writes, or FFmpeg jobs.

The web video-info endpoint may enqueue 115's own transcode for an unprepared
file. Call only for an explicit cloud-quality request. Provider credentials
are confined to fixed API calls and the exact authenticated master entry;
CDN requests and redirects never receive provider credentials.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from app.clients.p115 import P115Client, P115Error

MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_HOSTS = ("115.com", "115cdn.com", "115cdn.net", "anxia.com")
_ATTRIBUTE = re.compile(r'([A-Z0-9-]+)=("[^"\r\n]*"|[^,\r\n]+)(?:,|$)')


class P115VideoAuthError(P115Error):
    pass


def media_url(value: str, base: str = "", *, upgrade_http: bool = False) -> str:
    if not value or len(value) > 8192 or any(ord(c) <= 32 or c == "\\" for c in value):
        raise P115Error("115 云端播放地址无效")
    url = urllib.parse.urljoin(base, value)
    if upgrade_http and url.startswith("http://"):
        url = "https://" + url[7:]
    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or parsed.port not in (None, 443)
                or parsed.username is not None or parsed.password is not None or parsed.fragment
                or not any(host == suffix or host.endswith("." + suffix) for suffix in _HOSTS)):
            raise ValueError()
    except ValueError:
        raise P115Error("115 云端播放地址不在支持的 HTTPS 范围") from None
    return url


def attributes(line: str) -> dict[str, str]:
    value = line.partition(":")[2]
    pairs = list(_ATTRIBUTE.finditer(value))
    if "".join(m.group(0) for m in pairs) != value:
        raise P115Error("115 HLS 属性格式不兼容")
    result = {m[1]: m[2].strip('"') for m in pairs}
    if len(result) != len(pairs):
        raise P115Error("115 HLS 属性重复")
    return result


def manifest_lines(body: bytes) -> list[str]:
    if len(body) > MAX_MANIFEST_BYTES:
        raise P115Error("115 HLS 清单过大")
    try:
        lines = [line.strip() for line in body.decode("utf-8-sig").splitlines() if line.strip()]
    except UnicodeError:
        raise P115Error("115 HLS 清单编码无效") from None
    if not lines or lines[0] != "#EXTM3U" or any(len(line) > 16384 for line in lines):
        raise P115Error("115 未返回可播放的 HLS 清单")
    if any(line.startswith(("#EXT-X-DEFINE:", "#EXT-X-CONTENT-STEERING:")) for line in lines):
        raise P115Error("115 HLS 使用了暂不支持的动态地址")
    return lines


@dataclass(frozen=True)
class VideoVariant:
    id: str
    width: int
    height: int
    bandwidth: int
    stream_line: str
    url: str

    def public(self) -> dict:
        edge = max(self.width, self.height)
        label = "4K" if edge >= 3840 else "2K" if edge >= 2560 else "1080P" if edge >= 1920 else "720P" if edge >= 1280 else f"{self.width}×{self.height}"
        return {"id": self.id, "label": f"115 云端 · {label}", "width": self.width,
                "height": self.height, "bandwidth": self.bandwidth}


@dataclass(frozen=True)
class VideoManifest:
    url: str
    common: tuple[str, ...]
    variants: tuple[VideoVariant, ...]

    def selected(self, variant: VideoVariant) -> bytes:
        return ("\n".join((*self.common, variant.stream_line, variant.url)) + "\n").encode()


def parse_master(body: bytes, url: str) -> VideoManifest:
    lines = manifest_lines(body)
    common: list[str] = []
    variants: list[VideoVariant] = []
    seen: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("#EXT-X-STREAM-INF:"):
            fields = attributes(line)
            if index + 1 >= len(lines) or lines[index + 1].startswith("#"):
                raise P115Error("115 HLS 档位缺少地址")
            target = media_url(lines[index + 1], url, upgrade_http=True)
            resolution = re.fullmatch(r"(\d{1,5})x(\d{1,5})", fields.get("RESOLUTION", ""))
            bandwidth = fields.get("BANDWIDTH", "")
            if not resolution or not bandwidth.isdigit() or not 0 < int(bandwidth) <= 1_000_000_000:
                raise P115Error("115 HLS 档位缺少有效分辨率或码率")
            width, height = map(int, resolution.groups())
            if not 0 < min(width, height) or max(width, height) > 16384:
                raise P115Error("115 HLS 分辨率无效")
            # Do not include expiring URLs in a variant identity.
            identity = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:32]
            if identity in seen:
                raise P115Error("115 HLS 档位身份重复")
            seen.add(identity)
            variants.append(VideoVariant(identity, width, height, int(bandwidth), line, target))
            index += 2
            continue
        if not line.startswith("#") or line.startswith("#EXTINF:"):
            raise P115Error("115 未返回多清晰度主清单")
        if not line.startswith("#EXT-X-I-FRAME-STREAM-INF:"):
            common.append(line)
        index += 1
    if not variants or len(variants) > 32:
        raise P115Error("115 云端暂无可用清晰度")
    return VideoManifest(url, tuple(common), tuple(sorted(variants, key=lambda v: (v.width * v.height, v.bandwidth), reverse=True)))


class P115VideoClient(P115Client):
    def _api(self, path: str, params: dict, user_agent: str) -> dict:
        if not self.configured():
            raise P115Error("请先在 MediaIndex 配置有效的 115 登录态")
        if path not in ("/files/get_info", "/files/video"):
            raise P115Error("115 视频接口无效")
        request = urllib.request.Request(self.API_ORIGIN + path + "?" + urllib.parse.urlencode(params),
                                         headers={"User-Agent": user_agent, "Cookie": self.settings.p115_cookie})
        try:
            with self._opener.open(request, timeout=min(30, self.settings.p115_request_timeout_seconds)) as response:
                raw = response.read(MAX_MANIFEST_BYTES + 1)
            if len(raw) > MAX_MANIFEST_BYTES:
                raise ValueError()
            result = json.loads(raw)
            if isinstance(result, dict) and result.get("errno") == 990001:
                raise P115VideoAuthError("115 登录已过期，请在 MediaIndex 重新扫码登录")
            if not isinstance(result, dict) or result.get("state") not in (True, 1):
                raise ValueError()
            return result
        except P115VideoAuthError:
            raise
        except Exception:
            # Never surface a provider message, request URL, cookie, or body.
            raise P115Error("115 视频查询失败，请检查登录态、权限或云端转码状态") from None

    def discover(self, file_id: str, user_agent: str) -> VideoManifest:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", file_id):
            raise P115Error("115 文件身份无效")
        if not user_agent or len(user_agent) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in user_agent):
            raise P115Error("播放设备 User-Agent 无效")
        info = self._api("/files/get_info", {"file_id": file_id}, user_agent)
        items = info.get("data")
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            raise P115Error("115 未确认唯一文件身份")
        item = items[0]
        if str(item.get("file_id", item.get("fid", ""))) != file_id:
            raise P115Error("115 返回文件与请求不一致")
        pickcode = str(item.get("pick_code") or item.get("pickcode") or item.get("pc") or "")
        if not re.fullmatch(r"[A-Za-z0-9]{6,64}", pickcode):
            raise P115Error("115 文件缺少有效播放标识")
        result = self._api("/files/video", {"pickcode": pickcode, "local": 0}, user_agent)
        target = result.get("video_url")
        if not isinstance(target, str) or not target:
            raise P115Error("115 云端尚无播放地址，可能正在转码或当前账号无权限")
        # Some responses advertise an HTTP manifest on a known 115 host. Only
        # upgrade to TLS; never fall back to cleartext if HTTPS fails.
        if target.startswith("http://"):
            target = "https://" + target[7:]
        target = media_url(target)
        entry = "https://115.com/api/video/m3u8/" + pickcode + ".m3u8"
        if target == entry:
            body, final_url = self._read_entry(entry, user_agent)
        else:
            body, final_url = self.read_manifest(target, user_agent)
        return parse_master(body, final_url)

    def _read_entry(self, entry: str, user_agent: str) -> tuple[bytes, str]:
        # Only discover constructs this exact first-party path from the verified
        # file's pickcode. The no-redirect opener prevents Cookie forwarding.
        request = urllib.request.Request(entry, headers={
            "User-Agent": user_agent, "Cookie": self.settings.p115_cookie,
            "Referer": "https://115.com/",
        })
        try:
            with self._opener.open(request, timeout=20) as response:
                if response.status != 200:
                    raise P115Error("115 播放入口响应无效")
                body = response.read(MAX_MANIFEST_BYTES + 1)
        except urllib.error.HTTPError as exc:
            code, location = exc.code, exc.headers.get("Location", "")
            exc.close()
            if code in (301, 302, 303, 307, 308):
                return self.read_manifest(media_url(location, entry), user_agent)
            if code in (401, 403):
                raise P115VideoAuthError("115 播放入口认证失败，请在 MediaIndex 检查登录态") from None
            raise P115Error("115 播放入口请求失败") from None
        except (OSError, ValueError):
            raise P115Error("115 播放入口连接失败") from None
        manifest_lines(body)
        return body, entry

    def open_media(self, url: str, user_agent: str, range_header: str = ""):
        target = media_url(url)
        if range_header and not re.fullmatch(r"bytes=\d{0,18}-\d{0,18}", range_header):
            raise P115Error("云端播放范围无效")
        if range_header == "bytes=-":
            raise P115Error("云端播放范围无效")
        headers = {"User-Agent": user_agent}
        if range_header:
            headers["Range"] = range_header
        for attempt in range(5):
            try:
                response = self._opener.open(urllib.request.Request(target, headers=headers), timeout=20)
                if response.status not in (200, 206):
                    response.close()
                    raise P115Error("115 云端媒体响应无效")
                return response, target
            except urllib.error.HTTPError as exc:
                location = exc.headers.get("Location", "")
                code = exc.code
                exc.close()
                if code in (301, 302, 303, 307, 308) and attempt < 4:
                    target = media_url(location, target)
                    continue
                if code in (401, 403):
                    raise P115Error("115 云端播放地址失效，请重新选择清晰度") from None
                raise P115Error("115 云端媒体请求失败") from None
            except (OSError, ValueError):
                raise P115Error("115 云端媒体连接失败") from None
        raise P115Error("115 云端重定向过多")

    def read_manifest(self, url: str, user_agent: str) -> tuple[bytes, str]:
        response, target = self.open_media(url, user_agent)
        with response:
            body = response.read(MAX_MANIFEST_BYTES + 1)
        manifest_lines(body)
        return body, target
