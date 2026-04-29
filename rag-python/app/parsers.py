from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader

from .chunking import split_text


@dataclass
class ParsedChunk:
    content: str
    page_number: int | None
    anchor_text: str


def parse_document(file_name: str, payload: bytes, chunk_size: int, chunk_overlap: int) -> list[ParsedChunk]:
    lower_name = file_name.lower()
    if lower_name.endswith(".pdf"):
        return _parse_pdf(payload, chunk_size, chunk_overlap)
    text = _decode_text(payload)
    return _build_text_chunks(text, None, chunk_size, chunk_overlap)


def _parse_pdf(payload: bytes, chunk_size: int, chunk_overlap: int) -> list[ParsedChunk]:
    reader = PdfReader(BytesIO(payload))
    chunks: list[ParsedChunk] = []
    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        page_chunks = _build_text_chunks(text, i + 1, chunk_size, chunk_overlap)
        chunks.extend(page_chunks)
    return chunks


def _decode_text(payload: bytes) -> str:
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="ignore")


def _build_text_chunks(
    text: str,
    page_number: int | None,
    chunk_size: int,
    chunk_overlap: int,
) -> list[ParsedChunk]:
    results: list[ParsedChunk] = []
    for idx, content in enumerate(split_text(text, chunk_size, chunk_overlap), start=1):
        anchor = content[:80].replace("\n", " ").strip()
        results.append(
            ParsedChunk(
                content=content,
                page_number=page_number,
                anchor_text=anchor if anchor else f"chunk-{idx}",
            )
        )
    return results
