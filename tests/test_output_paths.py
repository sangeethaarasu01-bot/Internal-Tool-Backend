from app.utils.output_paths import xml_output_filename


def test_xml_output_filename_from_pdf_name() -> None:
    assert (
        xml_output_filename("access-kakichi-3657695-proof.pdf")
        == "access-kakichi-3657695-proof.xml"
    )


def test_xml_output_filename_strips_path() -> None:
    assert xml_output_filename(r"uploads\foo\paper.pdf") == "paper.xml"
