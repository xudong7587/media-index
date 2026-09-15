from __future__ import annotations

import json
import re
import unicodedata
from typing import Iterable


DEFAULT_QUALITY_PRIORITY = (
    "4K 原盘",
    "4K DV",
    "4K HDR",
    "4K SDR",
    "4K",
    "1080P HDR",
    "1080P",
    "720P",
    "WEB-DL",
    "WEBRip",
    "SDR",
)
DEFAULT_RESOURCE_EXCLUDES = ("TC", "TS", "CAM", "抢先", "预览版", "480p")


def normalize_quality_keyword(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")).casefold()).strip()


def configured_quality_keywords(raw: str | Iterable[str] | None) -> tuple[str, ...]:
    values: object = raw
    if isinstance(raw, str):
        try:
            values = json.loads(raw)
        except (TypeError, ValueError):
            values = ()
    if not isinstance(values, (list, tuple)):
        values = ()
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = str(value or "").strip()
        key = normalize_quality_keyword(label)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(label)
    return tuple(result) or DEFAULT_QUALITY_PRIORITY


def quality_aliases(label: str) -> tuple[str, ...]:
    key = normalize_quality_keyword(label)
    aliases = [key]
    known = {
        "4kdv": ("2160pdv", "dv", "dolbyvision"),
        "4k原盘": ("4kremux", "2160premux", "uhdremux", "blurayremux"),
        "4khdr": ("2160phdr", "hdr10", "dolbyvision", "杜比视界"),
        "4ksdr": ("2160psdr",),
        "4k": ("2160p",),
        "1080phdr": ("1080phdr10",),
        "web-dl": ("webdl",),
        "webrip": (),
    }
    aliases.extend(known.get(key, ()))
    return tuple(dict.fromkeys(aliases))


def quality_priority_score(name: str, raw: str | Iterable[str] | None = None) -> int:
    compact = normalize_quality_keyword(name)
    keywords = configured_quality_keywords(raw)
    for index, label in enumerate(keywords):
        key = normalize_quality_keyword(label)
        high_res = bool(re.search(r"(?i)(?<![a-z0-9])(?:4k|2160p|uhd)(?![a-z0-9])", name))
        full_hd = bool(re.search(r"(?i)(?<!\d)1080p", name))
        features = {
            "4k原盘": high_res and any(token in compact for token in ("remux", "原盘", "bdmv")),
            "4kdv": high_res and bool(re.search(r"(?i)(?<![a-z])dv(?![a-z])|dolby[ ._-]*vision|杜比视界", name)),
            "4khdr": high_res and "hdr" in compact,
            "4ksdr": high_res and "sdr" in compact,
            "1080phdr": full_hd and "hdr" in compact,
        }
        matches = features[key] if key in features else any(alias and alias in compact for alias in quality_aliases(label))
        if matches:
            return (len(keywords) - index) * 100 + len(normalize_quality_keyword(label))
    return 0


def configured_resource_excludes(raw: str | Iterable[str] | None) -> tuple[str, ...]:
    values: object = raw
    if isinstance(raw, str):
        try:
            values = json.loads(raw)
        except (TypeError, ValueError):
            values = ()
    if not isinstance(values, (list, tuple)):
        values = ()
    result = tuple(dict.fromkeys(str(value or "").strip() for value in values if str(value or "").strip()))
    return result or DEFAULT_RESOURCE_EXCLUDES


def excluded_resource_keyword(name: str, raw: str | Iterable[str] | None = None) -> str:
    haystack = unicodedata.normalize("NFKC", str(name or "")).casefold()
    for label in configured_resource_excludes(raw):
        token = unicodedata.normalize("NFKC", label).casefold().strip()
        if not token:
            continue
        if re.fullmatch(r"[a-z0-9]+", token):
            if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", haystack):
                return label
        elif token in haystack:
            return label
    return ""
