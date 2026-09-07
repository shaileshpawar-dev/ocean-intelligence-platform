"""Chunking, lexical indexing and reranking.

Why BM25 rather than embeddings
-------------------------------
The default deployment has no API key and no model download. BM25 is a strong,
well-understood lexical ranker that runs in pure Python over a few hundred
chunks in microseconds, and it is *inspectable*: you can see exactly which
query terms matched. For a corpus of regulatory instruments -- where the user's
vocabulary ("MARPOL", "Annex I", "discharge", "Arabian Sea") overlaps the
document vocabulary almost exactly -- lexical matching is not a compromise.

Dense retrieval is a genuine improvement for paraphrase-heavy queries, and
:class:`DenseIndex` slots in behind the same interface when
``sentence-transformers`` is installed. It is optional on purpose.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

#: Words carrying no retrieval signal in this domain.
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "about",
        "over",
        "under",
        "between",
        "during",
    ]
)

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-/][a-z0-9]+)*")

# BM25 parameters. k1 controls term-frequency saturation, b the strength of
# length normalisation. These are the conventional defaults.
BM25_K1 = 1.5
BM25_B = 0.75


def tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics, drop stopwords.

    Hyphens and slashes are kept inside tokens so "MARPOL 73/78" and
    "ship-source" survive as meaningful units.
    """
    return [
        token
        for token in TOKEN_RE.findall(text.lower())
        if token not in STOPWORDS and len(token) > 1
    ]


def chunk_text(text: str, target_words: int = 110, overlap_words: int = 25) -> list[str]:
    """Split text into overlapping, sentence-aligned chunks.

    Chunks end on sentence boundaries so a retrieved passage is readable on
    its own, and overlap so a fact spanning a boundary is not lost. Both
    matter more than exact chunk size: a passage that starts mid-sentence
    reads as though the system is quoting carelessly.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    if not sentences:
        return []

    chunks: list[str] = []
    current: list[str] = []
    count = 0

    for sentence in sentences:
        words = len(sentence.split())
        if count + words > target_words and current:
            chunks.append(" ".join(current))
            # Carry the tail sentences forward as overlap.
            carried: list[str] = []
            carried_words = 0
            for previous in reversed(current):
                previous_words = len(previous.split())
                if carried_words + previous_words > overlap_words:
                    break
                carried.insert(0, previous)
                carried_words += previous_words
            current, count = carried, carried_words
        current.append(sentence)
        count += words

    if current:
        chunks.append(" ".join(current))
    return chunks


@dataclass(slots=True)
class ScoredChunk:
    """One retrieval hit."""

    chunk_id: int
    document_id: str
    title: str
    text: str
    score: float
    doc_type: str = ""
    source_url: str | None = None
    year: int | None = None
    publication: str | None = None
    notice: str = ""
    #: Query terms that actually matched, so a reader can judge the hit.
    matched_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise a hit, including why it matched."""
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "title": self.title,
            "text": self.text,
            "score": round(self.score, 4),
            "doc_type": self.doc_type,
            "source_url": self.source_url,
            "year": self.year,
            "publication": self.publication,
            "notice": self.notice,
            "matched_terms": self.matched_terms,
        }


class BM25Index:
    """In-memory BM25 index over chunk texts.

    Rebuilt from the database on demand. At the scale this platform operates
    (hundreds of chunks) a rebuild is sub-millisecond, so there is no cache
    invalidation problem to get wrong.
    """

    def __init__(self) -> None:
        """Create an empty index."""
        self.chunks: list[dict] = []
        self.tokens: list[list[str]] = []
        self.freqs: list[Counter[str]] = []
        self.doc_freq: Counter[str] = Counter()
        self.avg_len: float = 0.0

    def add(self, chunk: dict) -> None:
        """Add one chunk. ``chunk`` must carry ``text`` and metadata."""
        tokens = tokenize(chunk["text"])
        self.chunks.append(chunk)
        self.tokens.append(tokens)
        self.freqs.append(Counter(tokens))
        for term in set(tokens):
            self.doc_freq[term] += 1

    def finalise(self) -> None:
        """Compute corpus statistics. Call once after all adds."""
        lengths = [len(t) for t in self.tokens]
        self.avg_len = sum(lengths) / len(lengths) if lengths else 0.0

    @property
    def size(self) -> int:
        """Number of indexed chunks."""
        return len(self.chunks)

    def search(self, query: str, limit: int = 8) -> list[ScoredChunk]:
        """Rank chunks against ``query`` by BM25.

        Returns only chunks that matched at least one query term; a zero-score
        hit is not a hit, and padding the result list to ``limit`` with
        unrelated passages would invite the LLM to cite them.
        """
        terms = tokenize(query)
        if not terms or not self.chunks:
            return []

        n = len(self.chunks)
        results: list[ScoredChunk] = []

        for index, freqs in enumerate(self.freqs):
            length = len(self.tokens[index])
            score = 0.0
            matched: list[str] = []

            for term in set(terms):
                tf = freqs.get(term, 0)
                if tf == 0:
                    continue
                matched.append(term)
                df = self.doc_freq.get(term, 0)
                # BM25 IDF with the +0.5 smoothing that keeps it positive.
                idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
                denominator = tf + BM25_K1 * (
                    1 - BM25_B + BM25_B * (length / (self.avg_len or 1))
                )
                score += idf * (tf * (BM25_K1 + 1)) / denominator

            if score <= 0:
                continue
            chunk = self.chunks[index]
            results.append(
                ScoredChunk(
                    chunk_id=chunk["chunk_id"],
                    document_id=chunk["document_id"],
                    title=chunk["title"],
                    text=chunk["text"],
                    score=score,
                    doc_type=chunk.get("doc_type", ""),
                    source_url=chunk.get("source_url"),
                    year=chunk.get("year"),
                    publication=chunk.get("publication"),
                    notice=chunk.get("notice", ""),
                    matched_terms=sorted(matched),
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]


def rerank(
    hits: list[ScoredChunk],
    query: str,
    *,
    region: str | None = None,
    prefer_types: tuple[str, ...] = (),
) -> list[ScoredChunk]:
    """Re-order hits using signals BM25 cannot see.

    Three adjustments, each multiplicative and small enough that it refines
    the lexical ordering rather than overriding it:

    * a title-term match is worth more than a body match
    * an exact phrase occurrence is strong evidence of topical fit
    * region and document-type hints from the caller nudge relevant sources up

    This is a feature-based reranker, not a cross-encoder. A cross-encoder
    would be better and needs a model download; this is the honest version
    that runs everywhere.
    """
    terms = set(tokenize(query))
    phrase = " ".join(tokenize(query)[:4])

    for hit in hits:
        boost = 1.0
        title_terms = set(tokenize(hit.title))
        overlap = len(terms & title_terms)
        if overlap:
            boost += 0.16 * overlap
        if phrase and phrase in " ".join(tokenize(hit.text)):
            boost += 0.30
        if region and region.lower() in hit.text.lower():
            boost += 0.22
        if prefer_types and hit.doc_type in prefer_types:
            boost += 0.14
        hit.score *= boost

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits
