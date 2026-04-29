from __future__ import annotations


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    if chunk_size <= 0:
        return [normalized]
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 5)

    chunks: list[str] = []
    step = max(1, chunk_size - overlap)
    start = 0
    length = len(normalized)
    while start < length:
        end = min(length, start + chunk_size)
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == length:
            break
        start += step
    return chunks

