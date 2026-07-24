from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, replace

from app.domain.media import LinkResolution, RenamePair
from app.services.episode_matcher import VIDEO_EXTENSIONS


_EPISODE_TOKEN = re.compile(r"(?i)(S)(0*\d+)([ ._-]*)(E)(0*\d+)")


@dataclass(frozen=True)
class EpisodeNameTemplate:
    prefix: str
    season_letter: str
    season_width: int
    separator: str
    episode_letter: str
    episode_width: int
    suffix: str

    def render(self, season_number: int, episode_number: int, extension: str) -> str:
        suffix = self.suffix.replace("{episode}", str(episode_number))
        token = (
            f"{self.season_letter}{season_number:0{self.season_width}d}"
            f"{self.separator}{self.episode_letter}{episode_number:0{self.episode_width}d}"
        )
        return f"{self.prefix}{token}{suffix}{extension}"


def adapt_resolution_to_existing_episode_names(
    resolution: LinkResolution,
    directory_response: dict,
    season_number: int,
) -> LinkResolution:
    template = infer_episode_name_template(directory_response, season_number)
    if template is None:
        return resolution
    adapted: list[RenamePair] = []
    for pair in resolution.rename_pairs:
        covered = pair.episode_numbers or ((pair.episode_number,) if pair.episode_number is not None else ())
        if len(covered) != 1:
            adapted.append(pair)
            continue
        extension = os.path.splitext(pair.replacement)[1].lower() or os.path.splitext(pair.source_name)[1].lower() or ".mp4"
        adapted.append(replace(pair, replacement=template.render(season_number, covered[0], extension)))
    return replace(resolution, rename_pairs=tuple(adapted))


def infer_episode_name_template(directory_response: dict, season_number: int) -> EpisodeNameTemplate | None:
    items = (directory_response.get("data") or {}).get("list") or []
    templates: list[EpisodeNameTemplate] = []
    for item in items:
        if not isinstance(item, dict) or item.get("dir") is True:
            continue
        name = str(item.get("file_name") or item.get("name") or "")
        stem, extension = os.path.splitext(name)
        if extension.casefold() not in VIDEO_EXTENSIONS:
            continue
        match = _EPISODE_TOKEN.search(stem)
        if not match or int(match.group(2)) != season_number:
            continue
        episode_number = int(match.group(5))
        suffix = re.sub(rf"(?<!\d){episode_number}(?!\d)", "{episode}", stem[match.end():])
        templates.append(
            EpisodeNameTemplate(
                prefix=stem[:match.start()],
                season_letter=match.group(1),
                season_width=len(match.group(2)),
                separator=match.group(3),
                episode_letter=match.group(4),
                episode_width=len(match.group(5)),
                suffix=suffix,
            )
        )
    if len(templates) < 3:
        return None
    signatures = [
        (
            template.prefix,
            template.season_letter,
            template.season_width,
            template.separator,
            template.episode_letter,
            template.suffix,
        )
        for template in templates
    ]
    signature, count = Counter(signatures).most_common(1)[0]
    if count / len(templates) < 0.6:
        return None
    matching = [template for template, candidate in zip(templates, signatures) if candidate == signature]
    return replace(matching[0], episode_width=max(template.episode_width for template in matching))
