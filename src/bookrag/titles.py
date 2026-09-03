"""Best-effort title/author guessing from a filename - the last resort when a
book has no usable internal metadata and no explicit --title/--author."""

from __future__ import annotations

import re

_SMALL_WORDS = {
    "a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to",
}


def guess_title_author(filename_stem: str) -> tuple[str, str | None]:
    normalized = re.sub(r"[_\-]+", " ", filename_stem).strip()
    normalized = re.sub(r"\s+", " ", normalized)

    match = re.match(r"^(.*?)\s+by\s+(.+)$", normalized, flags=re.IGNORECASE)
    if match:
        title, author = match.group(1).strip(), match.group(2).strip()
    else:
        title, author = normalized, None

    return _title_case(title), _title_case(author) if author else None


def _title_case(text: str) -> str:
    words = text.split(" ")
    result = []
    for i, word in enumerate(words):
        if i > 0 and word.lower() in _SMALL_WORDS:
            result.append(word.lower())
        else:
            result.append(word[:1].upper() + word[1:] if word else word)
    return " ".join(result)
