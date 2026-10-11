"""PDF-first IEEE journal detection for JATS metadata overlay."""

from app.constants.ieee_journals import lookup_ieee_journal
from app.services.jats_metadata_overlay import (
    _detect_journal_title,
    _infer_doi,
    _infer_manuscript_id,
    build_jats_metadata_overlay,
)
from app.models.semantic_mapping import SemanticMappingBody


def test_lookup_tce_from_filename() -> None:
    journal = lookup_ieee_journal(source_filename="tce-amarakorba-3658363-proof.pdf1.pdf")
    assert journal is not None
    assert journal.acronym == "TCE"


def test_pdf_header_overrides_ir_tap_journal_header() -> None:
    header = (
        "IEEE Transactions on Consumer Electronics\n"
        "10.1109/TCE.2026.3658363\n"
        "TCE-2025-04-1269\n"
    )
    ir = {
        "front": {
            "journal_header": {
                "text": "IEEE Transactions on Antennas and Propagation",
                "elements": [],
            }
        }
    }
    title = _detect_journal_title(header, ir, "tce-amarakorba-3658363-proof.pdf1.pdf")
    assert title == "IEEE Transactions on Consumer Electronics"


def test_infer_tce_doi_and_manuscript_from_proof_header() -> None:
    header = (
        "IEEE Trans. Consumer Electronics VOLUME 72, 2026\n"
        "Digital Object Identifier 10.1109/TCE.2026.3658363\n"
        "Manuscript ID TCE-2025-04-1269\n"
    )
    doi = _infer_doi(header, 2026, "3658363", "tce-amarakorba-3658363-proof.pdf1.pdf")
    assert doi == "10.1109/TCE.2026.3658363"
    ms = _infer_manuscript_id(header, "tce-amarakorba-3658363-proof.pdf1.pdf", "3658363")
    assert ms == "TCE-2025-04-1269"


def test_build_overlay_resolves_tce_journal_meta() -> None:
    phase1 = {
        "pages": [{"raw_page_text": "IEEE Transactions on Consumer Electronics\n10.1109/TCE.2026.3658363\n"}],
        "source_filename": "tce-amarakorba-3658363-proof.pdf1.pdf",
    }
    ir = {
        "front": {
            "journal_header": {
                "text": "IEEE Transactions on Antennas and Propagation",
                "elements": [],
            }
        }
    }
    overlay = build_jats_metadata_overlay(
        phase1=phase1,
        ir=ir,
        mapping=SemanticMappingBody(front={}, body=[], back={}),
        source=None,
    )
    assert overlay.journal is not None
    assert overlay.journal.acronym == "TCE"
    assert overlay.doi == "10.1109/TCE.2026.3658363"
