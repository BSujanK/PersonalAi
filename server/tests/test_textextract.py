from __future__ import annotations

import io
import zipfile

from pypdf import PdfWriter

from agent.connectors.textextract import MAX_TEXT_CHARS, SUPPORTED_SUFFIXES, extract_text

_DOC_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    "<w:p><w:r><w:t>First</w:t></w:r><w:r><w:t> line</w:t></w:r></w:p>"
    "<w:p><w:r><w:t>Second line</w:t></w:r></w:p></w:body></w:document>"
)


def _docx(xml: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
    return buf.getvalue()


def _tiny_pdf(text: str) -> bytes:
    stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return out


def test_text_formats_strip_bom_and_replace_bad_bytes() -> None:
    assert extract_text(b"\xef\xbb\xbfhello", ".txt") == "hello"
    assert extract_text(b"a,b\n1,2", ".CSV") == "a,b\n1,2"
    assert extract_text(b"ok\xff", ".md") == "ok�"


def test_unsupported_suffix_is_empty() -> None:
    assert extract_text(b"data", ".exe") == ""
    assert ".pdf" in SUPPORTED_SUFFIXES


def test_output_is_capped() -> None:
    assert len(extract_text(b"x" * (MAX_TEXT_CHARS + 10), ".txt")) == MAX_TEXT_CHARS


def test_docx_paragraphs() -> None:
    assert extract_text(_docx(_DOC_XML), ".docx") == "First line\nSecond line"


def test_oversized_docx_is_refused() -> None:
    padding = "<w:p><w:r><w:t>" + "a" * 100 + "</w:t></w:r></w:p>"
    big = _DOC_XML.replace("</w:body>", padding * 250_000 + "</w:body>")
    assert len(big) > 20 * 1024 * 1024
    assert extract_text(_docx(big), ".docx") == ""


def test_broken_docx_and_pdf_give_empty_text() -> None:
    assert extract_text(b"not a zip", ".docx") == ""
    assert extract_text(_docx("<w:document"), ".docx") == ""
    assert extract_text(b"%PDF-1.4 garbage", ".pdf") == ""


def test_docx_entity_bombs_are_refused() -> None:
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'
    assert extract_text(_docx(bomb), ".docx") == ""


def test_pdf_text_object() -> None:
    assert "Hello Synthetic" in extract_text(_tiny_pdf("Hello Synthetic"), ".pdf")


def test_blank_pdf_page_is_empty() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    assert extract_text(buf.getvalue(), ".pdf") == ""
