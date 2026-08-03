"""Small deterministic lexical retriever for PampaPilot's versioned knowledge."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
import unicodedata
from typing import Any, Mapping

from .media_discovery import WORKSPACE_ROOT


KNOWLEDGE_ROOT = WORKSPACE_ROOT / "knowledge"
TOKEN_RE = re.compile(r"[a-z0-9áéíóúüñ_#-]{3,}", re.IGNORECASE)
STOPWORDS = {
    "para", "como", "esta", "este", "esto", "desde", "sobre", "tener",
    "hacer", "mejor", "puede", "porque", "cuando", "pero", "solo", "cada",
}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _tokens(value: str) -> set[str]:
    return {
        _fold(match.group(0))
        for match in TOKEN_RE.finditer(value)
        if _fold(match.group(0)) not in STOPWORDS
    }


def _field(text: str, name: str) -> str | None:
    match = re.search(rf"(?mi)^{re.escape(name)}:\s*[\"']?([^\n\"']+)", text)
    return match.group(1).strip() if match else None


@lru_cache(maxsize=8)
def _index(root_text: str, signature: tuple[tuple[str, int, int], ...]) -> tuple[dict[str, Any], ...]:
    root = Path(root_text)
    documents: list[dict[str, Any]] = []
    for relative, _mtime, _size in signature:
        path = root / relative
        text = path.read_text(encoding="utf-8-sig")
        title = _field(text, "title") or path.stem.replace("-", " ").title()
        document_id = _field(text, "id") or f"knowledge.{path.with_suffix('').as_posix().replace('/', '.')}"
        stage = _field(text, "stage") or path.parent.name
        documents.append({
            "id": document_id,
            "title": title,
            "stage": stage,
            "source": relative.replace("\\", "/"),
            "text": text,
            "tokens": _tokens(f"{relative} {document_id} {title} {stage} {text}"),
        })
    return tuple(documents)


def _documents(root: Path) -> tuple[dict[str, Any], ...]:
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".md", ".yaml", ".yml"}
        and "agent" not in path.relative_to(root).parts
    )
    signature = tuple(
        (path.relative_to(root).as_posix(), path.stat().st_mtime_ns, path.stat().st_size)
        for path in files
    )
    return _index(str(root.resolve()), signature)


def retrieve_knowledge(
    query: str,
    project_context: Mapping[str, Any] | None = None,
    *,
    knowledge_root: Path | None = None,
    limit: int = 4,
    max_chars: int = 5_000,
) -> dict[str, Any]:
    """Return only relevant, cited excerpts; no embedding service is required."""

    root = (knowledge_root or KNOWLEDGE_ROOT).resolve()
    query_tokens = _tokens(query)
    if not query_tokens or not root.is_dir():
        return {"query": query, "items": [], "retrieval": "lexical-v1"}
    context = project_context or {}
    song = context.get("song", {}) if isinstance(context, Mapping) else {}
    hints = " ".join(str(song.get(key, "")) for key in ("source_kind", "status")) if isinstance(song, Mapping) else ""
    weighted_query = query_tokens | _tokens(hints)
    ranked: list[tuple[float, dict[str, Any]]] = []
    for document in _documents(root):
        overlap = weighted_query & document["tokens"]
        if not overlap:
            continue
        title_tokens = _tokens(f"{document['title']} {document['source']} {document['id']}")
        score = float(len(overlap)) + 2.0 * len(query_tokens & title_tokens)
        ranked.append((score, document))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]["source"]))
    items: list[dict[str, Any]] = []
    remaining = max_chars
    for score, document in ranked[:limit]:
        excerpt = document["text"].strip()
        allowance = min(1_800, remaining)
        if allowance < 200:
            break
        if len(excerpt) > allowance:
            excerpt = excerpt[:allowance].rsplit("\n", 1)[0] + "\n…"
        remaining -= len(excerpt)
        items.append({
            "knowledge_id": document["id"],
            "title": document["title"],
            "stage": document["stage"],
            "source": document["source"],
            "score": score,
            "excerpt": excerpt,
        })
    return {"query": query, "items": items, "retrieval": "lexical-v1"}
