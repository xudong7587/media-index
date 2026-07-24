from __future__ import annotations

from app.clients.qas import QasClient
from app.clients.moviepilot_115 import MoviePilot115Client
from app.clients.p115 import P115Client
from app.core.config import get_settings
from app.providers.base import ProviderKey, TransferProvider
from app.providers.qas import QasTransferProvider
from app.providers.moviepilot_115 import MoviePilot115TransferProvider
from app.providers.p115 import P115TransferProvider


def resolve_provider_key(save_target: str, requested: str | ProviderKey | None = None) -> str:
    target = str(save_target or "cloud").strip().lower()
    raw = str(requested or "").strip().lower()
    if target == "local":
        if raw in {"", "qas"}:
            return ""
        if raw != "p115":
            raise ValueError("本地任务只支持 QAS 或原生 115")
        settings = get_settings()
        if "p115" not in settings.enabled_provider_keys():
            raise ValueError("原生 115 尚未启用")
        if not P115Client(settings).configured():
            raise ValueError("原生 115 尚未配置")
        return "p115"
    if target != "cloud":
        raise ValueError(f"不支持的保存目标：{save_target}")

    settings = get_settings()
    value = raw or settings.default_provider_key()
    try:
        provider = ProviderKey(value)
    except ValueError as exc:
        raise ValueError(f"不支持的云盘 provider：{value}") from exc
    if provider.value not in settings.enabled_provider_keys():
        raise ValueError(f"云盘 provider 未启用：{provider.value}")
    if provider is ProviderKey.P115 and not P115Client(settings).configured():
        raise ValueError("原生 115 尚未配置")
    if provider is ProviderKey.MOVIEPILOT_115 and not MoviePilot115Client(settings).configured():
        raise ValueError("MoviePilot 115 尚未配置")
    return provider.value


def get_transfer_provider(
    provider: str | ProviderKey,
    *,
    qas: QasClient | None = None,
    moviepilot_115: MoviePilot115Client | None = None,
    p115: P115Client | None = None,
    target: str = "cloud",
) -> TransferProvider:
    key = ProviderKey(str(provider))
    if key is ProviderKey.QAS:
        return QasTransferProvider(qas)
    if key is ProviderKey.MOVIEPILOT_115:
        return MoviePilot115TransferProvider(moviepilot_115)
    if key is ProviderKey.P115:
        if target == "local":
            from app.providers.p115 import P115LocalTransferProvider

            return P115LocalTransferProvider(p115)
        return P115TransferProvider(p115)
    raise ValueError(f"云盘 provider 尚未实现：{key.value}")
