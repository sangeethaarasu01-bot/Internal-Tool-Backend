"""Parse publisher postal addresses and websites from copyright/imprint pages."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.layout.semantic_patterns import normalize_text

WEBSITE_RE = re.compile(
    r"\b(?:https?://)?(?:www\.)?([a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+)+(?:/[^\s]*)?)",
    re.IGNORECASE,
)
US_ADDRESS_RE = re.compile(
    r"(?im)(\d{1,5}\s+[^,\n]+(?:,\s*[^,\n]+)?)\s*,\s*"
    r"([A-Za-z][A-Za-z\s.'\-]+?)\s*,\s*([A-Za-z][A-Za-z\s.'\-]+?)\s+(\d{5}(?:-\d{4})?)"
)
UK_ADDRESS_RE = re.compile(
    r"(?im)^\s*(\d{1,4}\s+[\w\s\.'\-]+(?:street|st\.?|road|rd\.?))\s*,\s*"
    r"([A-Za-z][A-Za-z\s.'\-]+?)\s*,\s*([A-Za-z][A-Za-z\s.'\-]+?)\s+([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\s*$"
)


@dataclass(frozen=True)
class PublisherAddress:
    street: str | None = None
    city: str | None = None
    state: str | None = None
    post_code: str | None = None
    country: str | None = None
    website: str | None = None


def _normalize_website(raw: str) -> str:
    cleaned = raw.strip().rstrip(".,;")
    if not cleaned.lower().startswith(("http://", "https://")):
        return f"https://{cleaned}"
    return cleaned


def extract_publisher_addresses(text: str) -> list[PublisherAddress]:
    """Best-effort parse of US/UK-style publisher addresses and websites."""
    addresses: list[PublisherAddress] = []
    seen: set[tuple[str, ...]] = set()

    for match in US_ADDRESS_RE.finditer(text or ""):
        street = normalize_text(match.group(1)).strip()
        city = normalize_text(match.group(2)).strip()
        state = normalize_text(match.group(3)).strip()
        post_code = match.group(4).strip()
        key = (street, city, state, post_code)
        if key in seen:
            continue
        seen.add(key)
        addresses.append(
            PublisherAddress(
                street=street,
                city=city,
                state=state,
                post_code=post_code,
                country="United States",
            )
        )

    for match in UK_ADDRESS_RE.finditer(text or ""):
        street = normalize_text(match.group(1)).strip()
        city = normalize_text(match.group(2)).strip()
        region = normalize_text(match.group(3)).strip()
        post_code = match.group(4).strip().upper()
        key = (street, city, region, post_code)
        if key in seen:
            continue
        seen.add(key)
        addresses.append(
            PublisherAddress(
                street=street,
                city=city,
                state=region,
                post_code=post_code,
                country="United Kingdom",
            )
        )

    websites: list[str] = []
    for match in WEBSITE_RE.finditer(text or ""):
        site = match.group(0).strip().rstrip(".,;")
        if "rowman" in site.lower() or "littlefield" in site.lower() or site.lower().startswith("www."):
            normalized = _normalize_website(site)
            if normalized not in websites:
                websites.append(normalized)

    if websites and addresses:
        first = addresses[0]
        addresses[0] = PublisherAddress(
            street=first.street,
            city=first.city,
            state=first.state,
            post_code=first.post_code,
            country=first.country,
            website=websites[0],
        )
    elif websites:
        addresses.append(PublisherAddress(website=websites[0]))

    return addresses
