from __future__ import annotations

from app.models.extracted_document import ExtractedTableSummary, TableExtractionQuality
from app.pipeline.phase1.tables import _filter_and_rank_tables


def test_rejects_uncaptioned_reference_like_table() -> None:
    from app.pipeline.table_extraction.phase1_filter import passes_phase1_table_validation

    rows = [[f"[{i}] Author et al., Title, 2020."] for i in range(1, 20)]
    assert passes_phase1_table_validation(rows, caption=None) is False


def test_merge_reference_rows_collapses_continuations() -> None:
    from app.pipeline.phase1.tables import _merge_reference_table_rows, _postprocess_extracted_table
    from app.models.extracted_document import ExtractedTableSummary

    raw_rows = [
        ["[26] Start row"],
        ["continuation text"],
        ["[28] Second row"],
        ["more text"],
    ]
    merged = _merge_reference_table_rows(raw_rows)
    assert len(merged) == 2
    assert "continuation" in merged[0][0]

    table = ExtractedTableSummary(
        table_id="t1",
        page_number=1,
        caption="TABLE I",
        rows=raw_rows,
    )
    from app.pipeline.phase1.captions import CaptionCandidate

    caps = [
        CaptionCandidate(
            page_number=1,
            text="TABLE I\nCOMPARISON WITH OTHER HARMONIC SUPPRESSION FILTERING ANTENNAS",
            bbox=[0.0, 0.0, 1.0, 1.0],
            block_ids=[],
            caption_type="table",
        )
    ]
    out = _postprocess_extracted_table(table, caps)
    assert out.subtitle is None or isinstance(out.subtitle, str)


def test_normalize_ocr_comparison_table_nine_columns() -> None:
    from app.pipeline.phase1.tables import _postprocess_extracted_table
    from app.pipeline.phase1.captions import CaptionCandidate

    ocr_rows = [
        [
            "Ref. [26] [28] [31] [32]",
            "Operation Frequency 2.9 GHz 2.25 GHz 5.44 GHz 2.35 GHz",
            "Impedance Bandwidth 27.5% 49% 19.7% 56%",
            "Size (3o²) 0.33*0.32 1.05*1.05 0.66*0.66 0.4*0.4",
            "Profile (20) 1 0.25 0.1 0.28",
            "COMPARISONWITHOTHERHARMONICSUPPRESSIONFILTERINGANTENNAS MethodofSuppression filter integrated",
            "GainIn-Band (dBi) 2.5 7.9 7.4 8.3",
            "Freq.Selectivity (dB/GHz) 30 42 60 170",
            "Gain Suppression 10 dB@4.5fo 13 dB@4f 23 dB@2.3fo 18.4 dB@1.9fo",
        ],
        ["[29]", "2.38 GHz", "5.6%", "", "0.02", "resonatorintegrated", "9.7", "200", "25 dB@2.2fo"],
        ["[27]", "2.45 GHz", "3.2%", "", "0.02", "resonatorintegrated", "2", "220", "12.6 dB@6.4fo"],
        ["[33]", "3.55GHz", "13.3%", "0.54*0.54", "0.08", "hybrid feed", "8.1", "60", "18 dB@1.7fo"],
        ["[30]", "2.45 GHz", "9%", "0.65*0.65", "0.05", "slot loading", "6.7", "50", "16.7 dB@4fo"],
        ["[34]", "2.3 GHz", "50.8%", "0.46*0.46", "0.28", "slotloading+filter", "8", "130", "24.8 dB@4.8fo"],
    ]
    caps = [
        CaptionCandidate(
            page_number=4,
            text="TABLE I\nCOMPARISON WITH OTHER HARMONIC SUPPRESSION FILTERING ANTENNAS",
            bbox=[288.0, 56.0, 319.0, 66.0],
            block_ids=[],
            caption_type="table",
        )
    ]
    table = ExtractedTableSummary(
        table_id="table_9",
        page_number=4,
        rows=ocr_rows,
        caption="TABLE I",
    )
    out = _postprocess_extracted_table(table, caps)
    assert out.table_id == "table_1"
    assert out.subtitle and "COMPARISON" in out.subtitle.upper()
    assert out.column_count == 9
    assert out.row_count == len(out.rows)
    assert out.row_count == 10
    assert out.column_count == 9
    assert len(out.rows[0]) == 9
    data_refs = [row[0] for row in out.rows[1:]]
    assert data_refs[:4] == ["[26]", "[28]", "[31]", "[32]"]
    assert "[29]" in data_refs
    assert "[34]" in data_refs
    assert out.extraction_quality and out.extraction_quality.caption_detected


def test_structure_ieee_table_merges_reference_rows() -> None:
    from app.pipeline.phase1.tables import _structure_ieee_comparison_table

    rows = [
        ["Ref.  Operation  Gain  Roll-off  Size  Profile"],
        ["[26] First reference row"],
        ["continuation of first"],
        ["[28] Second reference row"],
        ["more continuation"],
    ]
    structured, headers, subtitle = _structure_ieee_comparison_table(
        rows,
        subtitle="COMPARISON WITH OTHER HARMONIC SUPPRESSION FILTERING ANTENNAS",
    )
    assert len(headers) >= 2
    assert len(structured) == 3
    assert "[26]" in structured[1][0]
    assert "continuation" in structured[1][0]


def test_structure_vco_performance_summary_table() -> None:
    from app.pipeline.phase1.tables import _structure_vco_performance_summary_rows

    raw_rows = [
        [
            "Topology Technology Techniques# Frequency [GHz]",
            "This work Quad-core Quad-mode 65-nm CMOS M 4.21 to 15.18",
            "L. Chao JSSC'23 [21] Quad-core Quad-mode 65-nm CMOS 12.1 to 32",
            "Y. Shu ISSCC'20 [18] Quad-core Quad-mode 40-nm CMOS M+E 18.6 to 40.1",
            "J. Gong ISSCC'22 [15] Dual-core Tri-mode 22-nm FinFET M+E 7.1 to 16.8",
            "O. El-Aassar JSSC'21 [14] Dual-core Tri-mode 22-nm FDSOI M+E 8 to 17",
            "Z. Kang ISSCC'24 [28] Single core Dual-mode 40-nm CMOS 8.9 to 21.9",
            "H. Ge ISSCC'24 [22] Quad-core Quad-mode 65-nm CMOS M+E 13.7 to 41.5",
        ],
        ["TR [%]", "113.2", "90.2", "73.2", "80.6", "72", "84.4", "101"],
        ["FTR Overlap°[%]", "10.5 to 14.7", "0.6 to 2.5", "4.1 to 5.0", "7.6 to 9.7", "2.2 to 4.4*", "2.0", "3.0 to 5.4"],
        ["PN @ 10MHz", "-130.7 to", "-122.1 to", "-122.7 to", "-128.7 to", "-134.7 to", "-131.1 to", "-124.4 to"],
        ["[dBc/Hz]", "-141.4", "-126.7", "-130.3", "-137.9", "-143.1", "-138.6", "-133.2"],
    ]
    structured = _structure_vco_performance_summary_rows(raw_rows)
    assert len(structured) == 15
    assert len(structured[0]) == 9
    assert structured[0][1] == "This work"
    assert structured[1][0] == "Topology"
    assert structured[5][0] == "TR [%]"
    assert "PN @ 10MHz" in structured[7][0]
    assert "[dBc/Hz]" in structured[7][0]


def test_vco_performance_table_passes_phase1_validation() -> None:
    from app.pipeline.table_extraction.phase1_filter import passes_phase1_table_validation
    from app.pipeline.phase1.tables import _structure_vco_performance_summary_rows

    raw_rows = [
        [
            "Topology Technology Techniques# Frequency [GHz]",
            "This work Quad-core Quad-mode 65-nm CMOS M 4.21 to 15.18",
            "L. Chao JSSC'23 [21] Quad-core Quad-mode 65-nm CMOS 12.1 to 32",
            "Y. Shu ISSCC'20 [18] Quad-core Quad-mode 40-nm CMOS M+E 18.6 to 40.1",
            "J. Gong ISSCC'22 [15] Dual-core Tri-mode 22-nm FinFET M+E 7.1 to 16.8",
            "O. El-Aassar JSSC'21 [14] Dual-core Tri-mode 22-nm FDSOI M+E 8 to 17",
            "Z. Kang ISSCC'24 [28] Single core Dual-mode 40-nm CMOS 8.9 to 21.9",
            "H. Ge ISSCC'24 [22] Quad-core Quad-mode 65-nm CMOS M+E 13.7 to 41.5",
        ],
        ["TR [%]", "113.2", "90.2", "73.2", "80.6", "72", "84.4", "101"],
    ]
    structured = _structure_vco_performance_summary_rows(raw_rows)
    assert passes_phase1_table_validation(
        structured,
        caption="TABLE I",
        caption_detected=True,
    )


def test_filter_tables_keeps_captioned_table_only() -> None:
    good = ExtractedTableSummary(
        table_id="table_1",
        page_number=4,
        row_count=8,
        column_count=3,
        rows=[["Ref.", "Operation Frequency", "Gain"]] + [["[26]", "2.9 GHz", "2.5"]] * 8,
        caption="TABLE I\nCOMPARISON WITH OTHER HARMONIC SUPPRESSION FILTERING ANTENNAS",
        extraction_quality=TableExtractionQuality(
            confidence=0.8,
            status="structured",
            caption_detected=True,
            structured_grid=True,
        ),
    )
    bad = ExtractedTableSummary(
        table_id="table_2",
        page_number=6,
        row_count=5,
        column_count=2,
        rows=[["[26]", "foo"], ["[27]", "bar"], ["x", "y"], ["a", "b"], ["c", "d"]],
        caption=None,
        extraction_quality=TableExtractionQuality(confidence=0.4, status="partial"),
    )
    kept = _filter_and_rank_tables([bad, good], [])
    assert len(kept) == 1
    assert kept[0].table_id == "table_1"
    assert kept[0].column_count >= 2
