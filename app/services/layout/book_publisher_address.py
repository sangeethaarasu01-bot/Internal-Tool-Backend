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
    r"(?im)(\d{1,5}\s+.+)\s*,\s*([^,\n]+)\s*,\s*"
    r"([A-Za-z][A-Za-z\s.'\-]+?)\s+(\d{5}(?:-\d{4})?)"
)
US_STREET_LINE_RE = re.compile(r"^\d{1,5}\s+.+")
US_CITY_STATE_ZIP_LINE_RE = re.compile(
    r"^([A-Za-z][A-Za-z\s.'\-]+?)\s*,\s*([A-Za-z][A-Za-z\s.'\-]+?)\s+(\d{5}(?:-\d{4})?)$"
)
UK_POSTCODE_RE = r"[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}"
UK_SLASH_ADDRESS_RE = re.compile(
    rf"(?is)(Unit\s+.+?)\s*/\s*(London)\s+({UK_POSTCODE_RE})\s*/\s*(UK|United Kingdom)\b"
)
UK_LONDON_BLOCK_RE = re.compile(
    rf"(?is)(Unit\s+[^/\n]+(?:,\s*[^,\n]+)*)\s*(?:/\s*|\n+)\s*"
    rf"(London)\s+({UK_POSTCODE_RE})\s*(?:/\s*|\n+)?\s*(UK|United Kingdom)?"
)
UK_COMMA_ADDRESS_RE = re.compile(
    rf"(?is)(Unit\s+.+?),\s*(London)\s+({UK_POSTCODE_RE}),\s*(UK|United Kingdom)\b"
)
UK_MULTILINE_RE = re.compile(
    rf"(?is)(Unit\s+[^\n]+?)\s*\n\s*(London)\s+({UK_POSTCODE_RE})\s*"
    rf"(?:\n\s*(United Kingdom|UK)\s*)?"
)
UK_LONDON_POSTCODE_LINE_RE = re.compile(rf"^(London)\s+({UK_POSTCODE_RE})$", re.IGNORECASE)
_NEW_STREET_LINE_RE = re.compile(r"^\s*(?:\d{1,5}\s+\S|Unit\s+)", re.IGNORECASE)
_COUNTRY_ONLY_LINE_RE = re.compile(
    r"^\s*(United Kingdom|UK|United States of America|United States|USA)\s*\.?\s*$",
    re.IGNORECASE,
)
_WEBSITE_LINE_RE = re.compile(r"^(?:https?://)?www\.", re.IGNORECASE)


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


def _first_website_in_text(text: str) -> str | None:
    for match in WEBSITE_RE.finditer(text or ""):
        site = match.group(0).strip().rstrip(".,;")
        lowered = site.lower()
        if lowered.startswith("www.") or lowered.startswith("http://") or lowered.startswith("https://"):
            return _normalize_website(site)
    return None


def _country_in_chunk(chunk: str) -> str | None:
    for pattern, label in (
        (r"\bUnited States of America\b", "United States of America"),
        (r"\bUnited States\b", "United States"),
        (r"\bUnited Kingdom\b", "United Kingdom"),
        (r"\bUSA\b", "USA"),
        (r"\bUK\b", "UK"),
    ):
        if re.search(pattern, chunk, re.IGNORECASE):
            return label
    return None


def _is_website_only_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _WEBSITE_LINE_RE.match(stripped):
        return True
    if stripped.lower().startswith("www.") and "." in stripped[4:]:
        return True
    return bool(WEBSITE_RE.fullmatch(stripped))


def _address_lines_from_segment(segment: str) -> list[str]:
    lines: list[str] = []
    for line in (segment or "").splitlines():
        stripped = normalize_text(line).strip()
        if not stripped or _is_website_only_line(stripped):
            continue
        lines.append(stripped)
    return lines


def _parse_multiline_address_block(segment: str) -> PublisherAddress | None:
    """Parse one blank-line-separated imprint block (multi-line US or UK)."""
    lines = _address_lines_from_segment(segment)
    if not lines:
        return None

    if US_STREET_LINE_RE.match(lines[0]) and len(lines) >= 2:
        city_match = US_CITY_STATE_ZIP_LINE_RE.match(lines[1])
        if city_match:
            return PublisherAddress(
                street=lines[0],
                city=city_match.group(1).strip(),
                state=city_match.group(2).strip(),
                post_code=city_match.group(3).strip(),
                country=_country_in_chunk(segment),
            )

    if re.match(r"^Unit\s+", lines[0], re.IGNORECASE):
        street = lines[0]
        city: str | None = None
        post_code: str | None = None
        country: str | None = None
        for line in lines[1:]:
            if _COUNTRY_ONLY_LINE_RE.match(line):
                country = _country_in_chunk(line) or normalize_text(line)
                continue
            london_match = UK_LONDON_POSTCODE_LINE_RE.match(line)
            if london_match:
                city = london_match.group(1).strip()
                post_code = london_match.group(2).strip().upper()
                continue
            postcode_only = re.match(rf"^({UK_POSTCODE_RE})$", line, re.IGNORECASE)
            if postcode_only and not post_code:
                post_code = postcode_only.group(1).strip().upper()
        if not country:
            country = _country_in_chunk(segment)
        if street and city and post_code:
            return PublisherAddress(
                street=street,
                city=city,
                post_code=post_code,
                country=country,
            )
    return None


def _publisher_address_segments(text: str) -> list[str]:
    """Split imprint text on blank lines and new street/unit lines (top to bottom)."""
    segments: list[str] = []
    current: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                segments.append("\n".join(current))
                current = []
            continue
        if _COUNTRY_ONLY_LINE_RE.match(stripped):
            if current:
                current.append(stripped)
                segments.append("\n".join(current))
                current = []
            else:
                current = [stripped]
            continue
        if _NEW_STREET_LINE_RE.match(stripped) and current:
            segments.append("\n".join(current))
            current = [stripped]
            continue
        current.append(stripped)
    if current:
        segments.append("\n".join(current))
    return segments


def _add_address(
    found: list[tuple[int, PublisherAddress]],
    seen: set[tuple[str, ...]],
    offset: int,
    address: PublisherAddress,
) -> None:
    region = "uk" if address.street and re.match(r"^Unit\s+", address.street, re.I) else "us"
    key = (
        region,
        address.street or "",
        address.city or "",
        address.state or "",
        address.post_code or "",
    )
    if key in seen:
        return
    seen.add(key)
    found.append((offset, address))


def _parse_segment(
    segment: str,
    found: list[tuple[int, PublisherAddress]],
    seen: set[tuple[str, ...]],
    offset: int,
    *,
    full_source: str | None = None,
) -> None:
    source = segment or ""
    imprint_context = full_source or source

    block = _parse_multiline_address_block(source)
    if block:
        if not block.country and re.search(r"\bUnit\s+", source, re.I):
            block = PublisherAddress(
                street=block.street,
                city=block.city,
                state=block.state,
                post_code=block.post_code,
                country=_country_in_chunk(imprint_context),
                website=block.website,
            )
        _add_address(found, seen, offset, block)

    for match in US_ADDRESS_RE.finditer(source):
        street = normalize_text(match.group(1)).strip()
        city = normalize_text(match.group(2)).strip()
        state = normalize_text(match.group(3)).strip()
        post_code = match.group(4).strip()
        _add_address(
            found,
            seen,
            offset + match.start(),
            PublisherAddress(
                street=street,
                city=city,
                state=state,
                post_code=post_code,
                country=_country_in_chunk(source),
            ),
        )

    for pattern in (
        UK_MULTILINE_RE,
        UK_COMMA_ADDRESS_RE,
        UK_SLASH_ADDRESS_RE,
        UK_LONDON_BLOCK_RE,
    ):
        for match in pattern.finditer(source):
            street = normalize_text(match.group(1)).strip().rstrip(".,;")
            city = normalize_text(match.group(2)).strip()
            post_code = match.group(3).strip().upper()
            country_raw = ""
            if match.lastindex and match.lastindex >= 4 and match.group(4):
                country_raw = match.group(4).strip()
            country = _country_in_chunk(source) or (
                normalize_text(country_raw) if country_raw else None
            )
            if not country and re.search(r"\bUnit\s+", source, re.I):
                country = _country_in_chunk(imprint_context)
            _add_address(
                found,
                seen,
                offset + match.start(),
                PublisherAddress(
                    street=street,
                    city=city,
                    post_code=post_code,
                    country=country,
                ),
            )


def extract_publisher_addresses(text: str) -> list[PublisherAddress]:
    """Parse US and UK publisher offices; website attaches to the first address only."""
    source = text or ""
    segments = _publisher_address_segments(source)
    if not segments:
        segments = [source]

    found: list[tuple[int, PublisherAddress]] = []
    seen: set[tuple[str, ...]] = set()
    search_from = 0
    for segment in segments:
        pos = source.find(segment, search_from)
        if pos < 0:
            pos = search_from
        _parse_segment(segment, found, seen, pos, full_source=source)
        search_from = pos + max(len(segment), 1)

    _parse_segment(source, found, seen, 0, full_source=source)

    found.sort(key=lambda item: item[0])
    addresses = [addr for _, addr in found]

    first_block = segments[0] if segments else source
    website = _first_website_in_text(first_block) or _first_website_in_text(source)
    if website and addresses:
        first = addresses[0]
        addresses[0] = PublisherAddress(
            street=first.street,
            city=first.city,
            state=first.state,
            post_code=first.post_code,
            country=first.country,
            website=website,
        )
    elif website and not addresses:
        addresses.append(PublisherAddress(website=website))
    return addresses
