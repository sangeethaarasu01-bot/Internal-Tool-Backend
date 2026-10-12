from app.constants.ieee_journals import lookup_ieee_journal


def test_lookup_ieee_access_from_doi_and_filename() -> None:
    journal = lookup_ieee_journal(
        doi="10.1109/ACCESS.2026.3657695",
        source_filename="access-kakichi-3657695-proof.pdf1.pdf",
    )
    assert journal is not None
    assert journal.acronym == "ACCESS"
    assert journal.ieee_id == "0063500"


def test_lookup_tce_from_title() -> None:
    journal = lookup_ieee_journal(journal_title="IEEE Transactions on Consumer Electronics")
    assert journal is not None
    assert journal.acronym == "TCE"


def test_lookup_jssc_from_doi_and_filename() -> None:
    journal = lookup_ieee_journal(
        doi="10.1109/JSSC.2026.3657757",
        source_filename="jssc-qin-3657757-proof.pdf1.pdf",
    )
    assert journal is not None
    assert journal.acronym == "JSSC"
    assert journal.coden == "IJSCBC"
