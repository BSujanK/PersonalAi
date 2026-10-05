"""Plain-text extraction from downloaded or local files. Never logs content."""

from __future__ import annotations

import io
import zipfile

from defusedxml import ElementTree
from pypdf import PdfReader

SUPPORTED_SUFFIXES = frozenset({".txt", ".md", ".csv", ".pdf", ".docx"})
MAX_TEXT_CHARS = 500_000
_MAX_PDF_PAGES = 200
_MAX_DOCX_XML_BYTES = 20 * 1024 * 1024
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace").removeprefix("﻿")


def _pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = reader.pages[:_MAX_PDF_PAGES]
        parts: list[str] = []
        total = 0
        for page in pages:
            text = page.extract_text()
            parts.append(text)
            total += len(text)
            if total >= MAX_TEXT_CHARS:
                break
        return "\n".join(parts)
    except Exception:
        return ""


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > _MAX_DOCX_XML_BYTES:
                return ""
            with archive.open(info) as handle:
                raw = handle.read(_MAX_DOCX_XML_BYTES + 1)
        if len(raw) > _MAX_DOCX_XML_BYTES:
            return ""
        root = ElementTree.fromstring(raw)
        paragraphs = [
            "".join(node.text or "" for node in para.iter(f"{_W_NS}t"))
            for para in root.iter(f"{_W_NS}p")
        ]
        return "\n".join(paragraphs)
    except Exception:
        return ""


def extract_text(data: bytes, suffix: str) -> str:
    """Text of a supported file, capped at 500,000 characters. Unreadable input gives ``""``."""
    suffix = suffix.lower()
    if suffix in (".txt", ".md", ".csv"):
        text = _decode(data)
    elif suffix == ".pdf":
        text = _pdf_text(data)
    elif suffix == ".docx":
        text = _docx_text(data)
    else:
        return ""
    return text[:MAX_TEXT_CHARS]
