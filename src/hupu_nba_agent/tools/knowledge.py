from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{1,4}|[A-Za-z0-9_-]{2,}")


@dataclass
class Chunk:
    source: str
    heading: str
    text: str


class KnowledgeBase:
    """Small local retrieval layer for SOP, templates, names, and examples."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.chunks = self._load_markdown()
        self.entities = self._load_entities()

    def search(self, query: str, top_k: int = 4) -> dict:
        top_k = max(1, min(top_k, 8))
        query_tokens = self._tokens(query)
        ranked: list[tuple[float, Chunk]] = []
        for chunk in self.chunks:
            haystack = f"{chunk.heading}\n{chunk.text}".lower()
            score = sum(
                3.0 if token in chunk.heading.lower() else 1.0
                for token in query_tokens
                if token in haystack
            )
            if query and query.lower() in haystack:
                score += 5.0
            if score:
                ranked.append((score, chunk))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return {
            "query": query,
            "results": [
                {
                    "source": chunk.source,
                    "heading": chunk.heading,
                    "text": chunk.text[:4_000],
                    "score": score,
                }
                for score, chunk in ranked[:top_k]
            ],
        }

    def lookup_entity(self, query: str, entity_type: str = "auto") -> dict:
        needle = query.casefold().strip()
        groups = [entity_type] if entity_type != "auto" else list(self.entities)
        matches = []
        for group in groups:
            for entity in self.entities.get(group, []):
                fields = [str(value) for value in entity.values() if isinstance(value, (str, int))]
                aliases = entity.get("aliases", [])
                haystack = " ".join([*fields, *aliases]).casefold()
                if needle and needle in haystack:
                    matches.append({"type": group, **entity})
        return {"query": query, "matches": matches[:12]}

    def _load_markdown(self) -> list[Chunk]:
        chunks: list[Chunk] = []
        if not self.root.exists():
            return chunks
        for path in sorted(self.root.glob("*.md")):
            heading = path.stem
            body: list[str] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("#"):
                    if body:
                        chunks.append(Chunk(path.name, heading, "\n".join(body).strip()))
                        body = []
                    heading = line.lstrip("#").strip()
                else:
                    body.append(line)
            if body:
                chunks.append(Chunk(path.name, heading, "\n".join(body).strip()))
        return [chunk for chunk in chunks if chunk.text]

    def _load_entities(self) -> dict:
        path = self.root / "entities.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {token.casefold() for token in TOKEN_RE.findall(text)}
