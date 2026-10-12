from __future__ import annotations

from app.services.layout.book_publisher_address import extract_publisher_addresses


def test_us_and_uk_comma_separated_addresses() -> None:
    text = (
        "4501 Forbes Boulevard, Suite 200, Lanham, Maryland 20706\n"
        "Unit A, Whitacre Mews, 26-34 Stannary Street, London SE11 4AB, UK"
    )
    addresses = extract_publisher_addresses(text)
    assert len(addresses) == 2
    assert addresses[0].street == "4501 Forbes Boulevard, Suite 200"
    assert addresses[0].city == "Lanham"
    assert addresses[0].state == "Maryland"
    assert addresses[0].post_code == "20706"
    assert addresses[1].street == "Unit A, Whitacre Mews, 26-34 Stannary Street"
    assert addresses[1].city == "London"
    assert "SE11" in (addresses[1].post_code or "")


def test_us_and_uk_addresses_website_on_first_only() -> None:
    text = (
        "Published by Lexington Books\n"
        "4501 Forbes Boulevard, Suite 200, Lanham, Maryland 20706\n"
        "www.rowman.com\n"
        "Unit A, Whitacre Mews, 26-34 Stannary Street / London SE11 4AB / UK"
    )
    addresses = extract_publisher_addresses(text)
    assert len(addresses) == 2
    assert addresses[0].website
    assert addresses[1].website is None
    assert addresses[0].street == "4501 Forbes Boulevard, Suite 200"
    assert addresses[1].street == "Unit A, Whitacre Mews, 26-34 Stannary Street"
    assert "SE11" in (addresses[1].post_code or "")


def test_us_street_includes_suite_apt_and_floor() -> None:
    text = "100 Broadway, Apt 4B, Floor 3, New York, New York 10001"
    addresses = extract_publisher_addresses(text)
    assert len(addresses) == 1
    assert addresses[0].street == "100 Broadway, Apt 4B, Floor 3"
