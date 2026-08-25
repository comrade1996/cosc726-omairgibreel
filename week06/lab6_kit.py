"""
COSC726 Lab 5 — memory and knowledge (support module)
=====================================================
Real embeddings, a real vector store, no mocks and no other lab.

    pip install chromadb openai
    ollama pull qwen2.5:7b
    ollama pull nomic-embed-text        # 768-dim embeddings, no API key
    ollama serve

What this module gives you
--------------------------
    POLICY_DOCS             the corpus to retrieve from
    chunk_fixed / recursive / parent_child      three strategies to compare
    OllamaEmbedder          REAL embeddings via /api/embeddings
    ChromaRetriever         a REAL vector store (in-process, no Docker)
    KeywordRetriever        the lexical baseline you must beat
    EpisodicStore / SemanticStore / ProceduralStore
    MemoryScope             the authorisation key on every read and write
    QUESTIONS               a fixed evaluation set with gold answers
    ablate()                render the with/without table

Self-contained: no import from any other week's lab.

Two traps this module makes visible rather than hiding
------------------------------------------------------
1. `nomic-embed-text` returns 768 dimensions. OpenAI's returns 1536. A
   collection built with one and queried with the other fails -- and this is
   reportedly the commonest reason a local memory setup silently breaks.
   `ChromaRetriever` records its dimension and refuses a mismatch loudly.

2. Chroma collection names must be 3-512 characters of [a-zA-Z0-9._-].
   `"t"` raises. Ours are named for you; yours will not be.
"""
from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = [
    "POLICY_DOCS", "Chunk", "chunk_fixed", "chunk_recursive",
    "chunk_parent_child", "OllamaEmbedder", "ChromaRetriever",
    "KeywordRetriever", "MemoryScope", "ScopeError", "Episode",
    "EpisodicStore", "Fact", "SemanticStore", "Procedure", "ProceduralStore",
    "EvalQuestion", "QUESTIONS", "score_retrieval", "AblationRow", "ablate",
    "OLLAMA_URL", "EMBED_MODEL",
]

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")


# ---------------------------------------------------------------------------
# 1. The corpus
# ---------------------------------------------------------------------------

POLICY_DOCS: dict[str, str] = {
    "POL-LATE": (
        "Late delivery policy. An order delivered three or more days after "
        "the promised date qualifies for a ten per cent credit. A credit "
        "changes the customer account and therefore requires approval from a "
        "human supervisor; it may be proposed but never applied directly by "
        "an agent. Orders fewer than three days late do not qualify for any "
        "credit. This policy was certified on 2026-07-01 and supersedes the "
        "version dated 2025-11-14, which used a five-day threshold."),
    "POL-REFUND": (
        "Refund policy. A refund may be issued for goods that arrive damaged "
        "or that were never delivered. Refunds require photographic evidence "
        "for damage claims. A refund is a financial action and always "
        "requires human approval. Refund requests older than ninety days "
        "from the delivery date are declined automatically."),
    "POL-ADDRESS": (
        "Address change policy. A delivery address may be changed while an "
        "order is still at the depot. Once an order is out for delivery the "
        "address cannot be changed and the customer must arrange redelivery "
        "with the courier. Address changes require identity confirmation."),
    "POL-BILLING": (
        "Billing disputes. Duplicate charges, incorrect amounts and "
        "unrecognised transactions are handled by the billing team and not "
        "by support agents. Support agents must escalate billing disputes "
        "immediately without attempting a resolution."),
    "POL-ESCALATE": (
        "Escalation. An agent must escalate to a human when evidence is "
        "insufficient, when a customer has contacted us about the same issue "
        "more than once in sixty days, or when the request falls outside the "
        "agent's remit. Escalation should carry the context gathered so far."),
}


# ---------------------------------------------------------------------------
# 2. Chunking
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Chunk:
    doc_id: str
    chunk_id: str
    text: str
    parent_id: str | None = None

    def __repr__(self) -> str:
        return f"<{self.chunk_id}: {self.text[:44]!r}...>"


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def chunk_fixed(docs: dict[str, str], size: int = 18,
                overlap: int = 0) -> list[Chunk]:
    """Split on a fixed word count. The naive baseline.

    Watch what this does to POL-LATE: the threshold ("three or more days")
    and the consequence ("requires approval") can land in different chunks,
    so neither answers the question alone. That is chunking capping
    everything downstream, and no re-ranker recovers from it.
    """
    out: list[Chunk] = []
    for doc_id, text in docs.items():
        toks = text.split()
        step = max(size - overlap, 1)
        for i in range(0, len(toks), step):
            piece = " ".join(toks[i:i + size])
            if piece:
                out.append(Chunk(doc_id, f"{doc_id}#f{i // step}", piece))
    return out


def chunk_recursive(docs: dict[str, str]) -> list[Chunk]:
    """Split on sentence boundaries. The recommended starting point."""
    out: list[Chunk] = []
    for doc_id, text in docs.items():
        sents = [s.strip() for s in re.split(r"(?<=\.)\s+", text) if s.strip()]
        for i, sent in enumerate(sents):
            out.append(Chunk(doc_id, f"{doc_id}#r{i}", sent))
    return out


def chunk_parent_child(docs: dict[str, str]
                       ) -> tuple[list[Chunk], dict[str, str]]:
    """Embed small children, return the whole parent for context.

    Small for finding, large for understanding -- the dominant production
    pattern, and the resolution of the semantic-chunking paradox.
    """
    children = [Chunk(c.doc_id, c.chunk_id, c.text, parent_id=c.doc_id)
                for c in chunk_recursive(docs)]
    return children, dict(docs)


# ---------------------------------------------------------------------------
# 3. Real embeddings
# ---------------------------------------------------------------------------

class EmbedderError(RuntimeError):
    pass


class OllamaEmbedder:
    """Real embeddings from a local Ollama server. No API key, no network.

    `nomic-embed-text` returns 768 dimensions. If you swap the model you
    change the dimension, and every collection built with the old one is
    invalid. That is not a bug you can patch around -- it is a re-index.
    """

    def __init__(self, model: str = EMBED_MODEL, base_url: str = OLLAMA_URL):
        self.model = model
        self.url = f"{base_url.rstrip('/')}/api/embeddings"
        self._dim: int | None = None
        self._cache: dict[str, list[float]] = {}

    @property
    def dim(self) -> int | None:
        return self._dim

    def embed(self, text: str) -> list[float]:
        if text in self._cache:
            return self._cache[text]
        payload = json.dumps({"model": self.model, "prompt": text}).encode()
        req = urllib.request.Request(
            self.url, data=payload,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                vec = json.loads(resp.read())["embedding"]
        except urllib.error.URLError as exc:
            raise EmbedderError(
                f"cannot reach Ollama at {self.url}. Is `ollama serve` "
                f"running, and have you run `ollama pull {self.model}`? "
                f"({exc})") from None
        if self._dim is None:
            self._dim = len(vec)
        elif len(vec) != self._dim:
            raise EmbedderError(
                f"dimension changed mid-run: {len(vec)} vs {self._dim}")
        self._cache[text] = vec
        return vec

    def embed_many(self, texts: Iterable[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


# ---------------------------------------------------------------------------
# 4. Retrieval
# ---------------------------------------------------------------------------

class KeywordRetriever:
    """Lexical retrieval with IDF weighting. The baseline you must beat.

    On a corpus this small it is genuinely hard to beat -- which is the
    point. Measure before you reach for embeddings.
    """

    name = "keyword"

    def __init__(self, chunks: Iterable[Chunk],
                 parents: dict[str, str] | None = None):
        self.chunks = list(chunks)
        self.parents = parents
        self.tokens = [Counter(_words(c.text)) for c in self.chunks]
        df: Counter[str] = Counter()
        for t in self.tokens:
            df.update(set(t))
        n = max(len(self.chunks), 1)
        self.idf = {w: math.log(1 + n / (1 + c)) for w, c in df.items()}

    def retrieve(self, query: str, k: int = 3) -> list[Chunk]:
        q = _words(query)
        scored = []
        for chunk, toks in zip(self.chunks, self.tokens):
            score = sum(toks.get(w, 0) * self.idf.get(w, 0.0) for w in q)
            score /= math.sqrt(sum(toks.values()) or 1)
            scored.append((score, chunk))
        scored.sort(key=lambda p: (-p[0], p[1].chunk_id))
        return [c for s, c in scored[:k] if s > 0]


class ChromaRetriever:
    """A real vector store: ChromaDB, in-process, no Docker.

    Note the collection name rule: 3-512 characters of [a-zA-Z0-9._-],
    starting and ending alphanumeric. A one-character name raises.
    """

    name = "chroma"

    def __init__(self, chunks: Iterable[Chunk], embedder: OllamaEmbedder,
                 parents: dict[str, str] | None = None,
                 collection: str = "cosc726-policies"):
        import chromadb

        self.chunks = list(chunks)
        self.parents = parents
        self.embedder = embedder
        self.client = chromadb.EphemeralClient()
        try:
            self.client.delete_collection(collection)
        except Exception:
            pass
        # cosine, not the L2 default: we care about direction, not magnitude
        self.col = self.client.get_or_create_collection(
            collection, metadata={"hnsw:space": "cosine"})

        vecs = embedder.embed_many(c.text for c in self.chunks)
        self.dim = len(vecs[0]) if vecs else 0
        self.col.add(
            ids=[c.chunk_id for c in self.chunks],
            embeddings=vecs,
            documents=[c.text for c in self.chunks],
            metadatas=[{"doc_id": c.doc_id,
                        "parent_id": c.parent_id or ""} for c in self.chunks])

    def retrieve(self, query: str, k: int = 3) -> list[Chunk]:
        qv = self.embedder.embed(query)
        if len(qv) != self.dim:
            raise EmbedderError(
                f"query embedding is {len(qv)}-dim but the collection is "
                f"{self.dim}-dim. You changed embedding model; re-index.")
        res = self.col.query(query_embeddings=[qv], n_results=k)
        by_id = {c.chunk_id: c for c in self.chunks}
        return [by_id[i] for i in res["ids"][0] if i in by_id]


# ---------------------------------------------------------------------------
# 5. Memory stores, scoped
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MemoryScope:
    """The authorisation key carried on EVERY read and write.

    Memory access is an authorisation decision, not a lookup. A store that
    accepts a query without a scope is a cross-user leak waiting to happen.
    """
    user_id: str | None = None
    agent_id: str = "layla"
    session_id: str | None = None

    def matches(self, other: "MemoryScope") -> bool:
        if self.user_id is not None and self.user_id != other.user_id:
            return False
        return self.agent_id == other.agent_id


class ScopeError(PermissionError):
    """Raised on a scopeless access. Deliberately loud."""


def _require(scope: MemoryScope | None) -> MemoryScope:
    if scope is None or scope.user_id is None:
        raise ScopeError(
            "every memory read and write must carry a user scope; a "
            "scopeless query is how customer A's data reaches customer B")
    return scope


@dataclass
class Episode:
    episode_id: str
    scope: MemoryScope
    when: str
    what: str
    action: str
    outcome: str
    provenance: list[str] = field(default_factory=list)


class EpisodicStore:
    """What happened, when, and with what outcome."""

    def __init__(self) -> None:
        self._items: list[Episode] = []
        self._n = 2290

    def write(self, scope: MemoryScope, what: str, action: str, outcome: str,
              when: str, provenance: list[str] | None = None) -> Episode:
        _require(scope)
        self._n += 1
        ep = Episode(f"ep-{self._n}", scope, when, what, action, outcome,
                     provenance or [])
        self._items.append(ep)
        return ep

    def recall(self, scope: MemoryScope, about: str = "",
               k: int = 5) -> list[Episode]:
        _require(scope)
        hits = [e for e in self._items if e.scope.matches(scope)]
        if about:
            terms = set(_words(about))
            hits = [e for e in hits
                    if terms & set(_words(e.what + " " + e.action))]
        return sorted(hits, key=lambda e: e.when, reverse=True)[:k]

    def count_since(self, scope: MemoryScope, about: str, since: str) -> int:
        """How many times lately? The 'again' question, made checkable."""
        return len([e for e in self.recall(scope, about, k=99)
                    if e.when >= since])


@dataclass
class Fact:
    key: str
    value: str
    scope: MemoryScope
    asserted: str
    superseded_by: str | None = None

    @property
    def active(self) -> bool:
        return self.superseded_by is None


class SemanticStore:
    """Facts, with supersession rather than duplication."""

    def __init__(self) -> None:
        self._items: list[Fact] = []

    def write(self, scope: MemoryScope, key: str, value: str,
              asserted: str) -> Fact:
        _require(scope)
        for f in self._items:
            if f.key == key and f.scope.matches(scope) and f.active:
                f.superseded_by = asserted          # supersede, not duplicate
        fact = Fact(key, value, scope, asserted)
        self._items.append(fact)
        return fact

    def get(self, scope: MemoryScope, key: str) -> Fact | None:
        _require(scope)
        hits = [f for f in self._items
                if f.key == key and f.scope.matches(scope) and f.active]
        return hits[-1] if hits else None

    def history(self, key: str) -> list[Fact]:
        return [f for f in self._items if f.key == key]


@dataclass
class Procedure:
    rule_id: str
    when: str
    then: str
    status: str = "candidate"            # candidate | active
    provenance: list[str] = field(default_factory=list)


class ProceduralStore:
    """Rules, with a status field so a candidate cannot masquerade as law."""

    def __init__(self) -> None:
        self._items: dict[str, Procedure] = {}

    def propose(self, rule_id: str, when: str, then: str,
                provenance: list[str]) -> Procedure:
        p = Procedure(rule_id, when, then, "candidate", provenance)
        self._items[rule_id] = p
        return p

    def review(self, rule_id: str, approve: bool) -> Procedure | None:
        p = self._items.get(rule_id)
        if p is None:
            return None
        if not approve:
            self._items.pop(rule_id)
            return None
        p.status = "active"
        return p

    def active(self) -> list[Procedure]:
        return [p for p in self._items.values() if p.status == "active"]


# ---------------------------------------------------------------------------
# 6. Evaluation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvalQuestion:
    qid: str
    question: str
    gold_docs: set[str]
    gold_answer_contains: list[str]
    note: str = ""


QUESTIONS: list[EvalQuestion] = [
    EvalQuestion("Q1", "How many days late does an order have to be to "
                       "qualify for a credit?",
                 {"POL-LATE"}, ["three", "3"],
                 "Single-fact lookup. Everything should get this."),
    EvalQuestion("Q2", "Can an agent apply a credit itself?",
                 {"POL-LATE"}, ["approval", "human"],
                 "The threshold and the authority are different sentences. "
                 "Fixed-size chunking splits them."),
    EvalQuestion("Q3", "A customer says their parcel arrived smashed. What "
                       "do they need to provide?",
                 {"POL-REFUND"}, ["photograph", "evidence"],
                 "Paraphrase: 'smashed' never appears in the corpus."),
    EvalQuestion("Q4", "The order is already out for delivery. Can we change "
                       "the address?",
                 {"POL-ADDRESS"}, ["cannot", "redelivery", "courier"],
                 "Requires the negative case, not just the topic."),
    EvalQuestion("Q5", "Customer reports being charged twice. What now?",
                 {"POL-BILLING"}, ["escalate", "billing team"],
                 "'Charged twice' vs 'duplicate charges' -- no shared word. "
                 "This is where lexical retrieval fails."),
    EvalQuestion("Q6", "This is the customer's second complaint this month "
                       "about the same order. Does that change anything?",
                 {"POL-ESCALATE"}, ["escalate", "more than once"],
                 "Needs BOTH retrieval and episodic memory."),
]


def score_retrieval(retriever: Any, questions: Iterable[EvalQuestion],
                    k: int = 3) -> dict[str, float]:
    """Retrieval recall and precision, measured SEPARATELY from answers.

    Report only end-to-end quality and you cannot tell which stage failed.
    """
    qs = list(questions)
    hits, prec = 0, 0.0
    for q in qs:
        got = retriever.retrieve(q.question, k=k)
        docs = {c.doc_id for c in got}
        if q.gold_docs & docs:
            hits += 1
        prec += (len(q.gold_docs & docs) / len(docs)) if docs else 0.0
    n = max(len(qs), 1)
    return {"recall": hits / n, "precision": prec / n, "k": k}


@dataclass
class AblationRow:
    name: str
    recall: float
    precision: float
    answered: float
    tokens: int

    def as_row(self) -> str:
        return (f"{self.name:<28}{self.recall:>8.0%}{self.precision:>11.0%}"
                f"{self.answered:>10.0%}{self.tokens:>10}")


def ablate(rows: list[AblationRow]) -> str:
    hdr = (f"{'configuration':<28}{'recall':>8}{'precision':>11}"
           f"{'answered':>10}{'tokens':>10}")
    out = [hdr, "-" * len(hdr)] + [r.as_row() for r in rows]
    out.append("")
    out.append("Expect at least one layer to make things worse. That is a "
               "finding,\nnot a bug -- report it.")
    return "\n".join(out)
