"""Parse publisher postal addresses and websites from copyright/imprint pages."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.layout.semantic_patterns import normalize_text

WEBSITE_RE = re.compile(
    r"\b(?:https?://)?(?:www\.)?([a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+)+(?:/[^\s]*)?)",
    re.IGNORECASE,
)
# Street = entire line before city, state, and ZIP (keep Suite/Apt/Floor/Unit segments).
US_ADDRESS_RE = re.compile(
    r"(?im)(\d{1,5}\s+.+)\s*,\s*([^,\n]+)\s*,\s*"
    r"([A-Za-z][A-Za-z\s.'\-]+?)\s+(\d{5}(?:-\d{4})?)"
)
UK_POSTCODE_RE = r"[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}"
UK_SLASH_ADDRESS_RE = re.compile(
    rf"(?is)(Unit\s+.+?)\s*/\s*(London)\s+({UK_POSTCODE_RE})\s*/\s*(UK|United Kingdom)\b"
)
UK_LONDON_BLOCK_RE = re.compile(
    rf"(?is)(Unit\s+[^/\n]+(?:,\s*[^/\n]+)*)\s*(?:/\s*|\n+)\s*"
    rf"(London)\s+({UK_POSTCODE_RE})\s*(?:/\s*|\n+)?\s*(UK|United Kingdom)?"
)
UK_COMMA_ADDRESS_RE = re.compile(
    rf"(?is)(Unit\s+.+?),\s*(London)\s+({UK_POSTCODE_RE}),\s*(UK|United Kingdom)\b"
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


def _country_near_address(source: str, start: int, end: int) -> str | None:
    """Return a country only when explicitly named on the same line as the address."""
    line_start = source.rfind("\n", 0, start) + 1
    line_end = source.find("\n", end)
    if line_end == -1:
        line_end = len(source)
    window = source[line_start:line_end]
    for pattern, label in (
        (r"\bUnited States of America\b", "United States of America"),
        (r"\bUnited States\b", "United States"),
        (r"\bUSA\b", "USA"),
        (r"\bUnited Kingdom\b", "United Kingdom"),
        (r"\bUK\b", "UK"),
    ):
        match = re.search(pattern, window, re.IGNORECASE)
        if match:
            return label
    return None


def _collect_websites(text: str) -> list[str]:
    websites: list[str] = []
    for match in WEBSITE_RE.finditer(text or ""):
        site = match.group(0).strip().rstrip(".,;")
        if "rowman" in site.lower() or "littlefield" in site.lower() or site.lower().startswith("www."):
            normalized = _normalize_website(site)
            if normalized not in websites:
                websites.append(normalized)
    return websites


def extract_publisher_addresses(text: str) -> list[PublisherAddress]:
    """Parse US and UK publisher offices; website attaches to the first address only."""
    source = text or ""
    found: list[tuple[int, PublisherAddress]] = []
    seen: set[tuple[str, ...]] = set()

    for match in US_ADDRESS_RE.finditer(source):
        street = normalize_text(match.group(1)).strip()
        city = normalize_text(match.group(2)).strip()
        state = normalize_text(match.group(3)).strip()
        post_code = match.group(4).strip()
        key = ("us", street, city, state, post_code)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            (
                match.start(),
                PublisherAddress(
                    street=street,
                    city=city,
                    state=state,
                    post_code=post_code,
                    country=_country_near_address(source, match.start(), match.end()),
                ),
            )
        )

    for pattern in (UK_COMMA_ADDRESS_RE, UK_SLASH_ADDRESS_RE, UK_LONDON_BLOCK_RE):
        for match in pattern.finditer(source):
            street = normalize_text(match.group(1)).strip().rstrip(".,;")
            city = normalize_text(match.group(2)).strip()
            post_code = match.group(3).strip().upper()
            country_raw = (match.group(4) or "").strip()
            country = (
                _country_near_address(source, match.start(), match.end())
                or (normalize_text(country_raw) if country_raw else None)
            )
            key = ("uk", street, city, post_code)
            if key in seen:
                continue
            seen.add(key)
            found.append(
                (
                    match.start(),
                    PublisherAddress(
                        street=street,
                        city=city,
                        post_code=post_code,
                        country=country,
                    ),
                )
            )

    found.sort(key=lambda item: item[0])
    addresses = [addr for _, addr in found]
    websites = _collect_websites(source)
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
