from __future__ import annotations

from app.clients.qas import QasClient
from app.core.config import get_settings
from app.providers.base import ProviderKey, TransferProvider
from app.providers.qas import QasTransferProvider


def resolve_provider_key(save_target: str, requested: str | ProviderKey | None = None) -> str:
    target = str(save_target or "cloud").strip().lower()
    raw = str(requested or "").strip().lower()
    if target == "local":
        if raw:
            raise ValueError("本地任务不能指定云盘 provider")
        return ""
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
    if provider is not ProviderKey.QAS:
        raise ValueError(f"云盘 provider 尚未实现：{provider.value}")
    return provider.value


def get_transfer_provider(
    provider: str | ProviderKey,
    *,
    qas: QasClient | None = None,
) -> TransferProvider:
    key = ProviderKey(str(provider))
    if key is ProviderKey.QAS:
        return QasTransferProvider(qas)
    raise ValueError(f"云盘 provider 尚未实现：{key.value}")
