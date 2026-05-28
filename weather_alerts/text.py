from __future__ import annotations

import re
from typing import Iterable

SECTION_HEADER_RE = re.compile(
    r"\*\s*(WHAT|WHERE|WHEN|IMPACTS|ADDITIONAL DETAILS|PRECAUTIONARY/PREPAREDNESS ACTIONS)\.\s*",
    flags=re.IGNORECASE,
)

ABBREVIATIONS: tuple[tuple[str, str], ...] = (
    (r"\bmph\b", "miles per hour"),
    (r"\bkt\b", "knots"),
    (r"\bkts\b", "knots"),
    (r"\bnm\b", "nautical miles"),
    (r"\bft\.?\b", "feet"),
    (r"\bin\.?\b", "inches"),
    (r"\bmi\b", "miles"),
    (r"\bhrs\b", "hours"),
    (r"\bhr\b", "hour"),
    (r"\bmin\b", "minute"),
    (r"\bsec\b", "second"),
    (r"\bblw\b", "below"),
    (r"\babv\b", "above"),
    (r"\bavg\b", "average"),
    (r"\btill\b", "until"),
    (r"\bbtwn\b", "between"),
    (r"\bw/\b", "with"),
    (r"\bc/o\b", "care of"),
    (r"\be\.g\.\b", "for example"),
    (r"\bi\.e\.\b", "that is"),
    (r"\best\.\b", "estimated"),
    (r"\bN/A\b", "not available"),
    (r"&", "and"),
    (r"%", "percent"),
    (r"\.\.\.", "."),
)


def clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\r", " ").replace("\n", " ")).strip()


def normalize_section_headers(text: str) -> str:
    return SECTION_HEADER_RE.sub(lambda m: f"*{m.group(1).upper()}: ", text)


def expand_common_abbreviations(text: str) -> str:
    output = text
    for pattern, replacement in ABBREVIATIONS:
        output = re.sub(pattern, replacement, output, flags=re.IGNORECASE)
    return output


def truncate_words(text: str, max_words: int | None) -> str:
    if not max_words or max_words <= 0:
        return text
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip() + "..."


def modify_description(text: str, max_words: int | None = 150) -> str:
    text = clean_whitespace(str(text or ""))
    text = normalize_section_headers(text)
    text = expand_common_abbreviations(text)
    text = clean_whitespace(text)
    return truncate_words(text, max_words)


def telegram_chunks(text: str, *, limit: int = 3900) -> Iterable[str]:
    """Split text below Telegram's 4096 character sendMessage limit."""
    text = str(text or "").strip()
    if not text:
        return
    while len(text) > limit:
        cut = max(text.rfind("\n", 0, limit), text.rfind(" ", 0, limit))
        if cut < max(400, int(limit * 0.5)):
            cut = limit
        chunk = text[:cut].strip()
        if chunk:
            yield chunk
        text = text[cut:].strip()
    if text:
        yield text


def build_alert_message(
    *,
    title: str,
    description: str,
    county_label: str | None = None,
    prefix: str = "",
    max_words: int | None = 150,
) -> str:
    parts = []
    if prefix:
        parts.append(prefix.strip())
    parts.append(f"Detailed alert for {title}.")
    if county_label:
        parts.append(f"Area: {county_label}.")
    if description:
        parts.append(description)
    return modify_description(" ".join(parts), max_words=max_words)
