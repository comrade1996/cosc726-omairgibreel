#!/usr/bin/env python3
"""Week 6 retrieval and scoped-memory assignment implementation."""

from __future__ import annotations

import argparse
import json
from typing import Any

try:
    from . import lab6_kit as K
except ImportError:
    import lab6_kit as K

AblationRow = K.AblationRow
EpisodicStore = K.EpisodicStore
MemoryScope = K.MemoryScope
ProceduralStore = K.ProceduralStore
ScopeError = K.ScopeError
SemanticStore = K.SemanticStore


def make_search_tool(retriever: Any, parents: dict[str, str] | None = None):
    """Wrap a retriever as a read-only tool with structured results."""

    def search_policy(query: str, k: int = 3) -> dict:
        cleaned = query.strip()
        if len(cleaned) < 4:
            return {
                "ok": False,
                "error": "query_too_short",
                "hint": "Use at least four non-space characters.",
            }
        if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 10:
            return {"ok": False, "error": "invalid_k", "hint": "Use k from 1 to 10."}
        chunks = retriever.retrieve(cleaned, k=k)
        if not chunks:
            return {
                "ok": False,
                "error": "no_matches",
                "hint": "Rephrase the policy question or escalate.",
            }
        passages = []
        evidence_ids = []
        for chunk in chunks:
            text = chunk.text
            if parents is not None:
                parent_id = chunk.parent_id or chunk.doc_id
                text = parents.get(parent_id, text)
            passages.append(
                {
                    "doc_id": chunk.doc_id,
                    "chunk_id": chunk.chunk_id,
                    "text": text,
                }
            )
            evidence_ids.append(chunk.chunk_id)
        return {"ok": True, "passages": passages, "evidence_ids": evidence_ids}

    return search_policy


def seed_memory() -> tuple[EpisodicStore, SemanticStore, ProceduralStore]:
    """Create the two-user memory fixture and activate one reviewed procedure."""
    episodic = EpisodicStore()
    semantic = SemanticStore()
    procedural = ProceduralStore()
    alice = MemoryScope(user_id="cust-4417")
    bob = MemoryScope(user_id="cust-9001")

    first = episodic.write(
        alice,
        what="late delivery for order A1032",
        action="requested pending credit approval",
        outcome="approved by supervisor",
        when="2026-06-18",
        provenance=["POL-LATE", "A1032"],
    )
    second = episodic.write(
        alice,
        what="late delivery for order A1091",
        action="escalated repeat delivery complaint",
        outcome="human follow-up scheduled",
        when="2026-07-24",
        provenance=["POL-LATE", "A1091"],
    )
    episodic.write(
        bob,
        what="address change for order A1044",
        action="confirmed identity",
        outcome="address updated at depot",
        when="2026-07-20",
        provenance=["POL-ADDRESS", "A1044"],
    )

    semantic.write(alice, "contact_preference", "email", asserted="2026-05-01")
    semantic.write(alice, "contact_preference", "sms", asserted="2026-07-22")
    semantic.write(bob, "contact_preference", "phone", asserted="2026-07-20")

    procedure = procedural.propose(
        "PROC-REPEAT-LATE",
        when="the same customer has two late deliveries within 60 days",
        then="escalate with both episode IDs and the policy evidence",
        provenance=[first.episode_id, second.episode_id],
    )
    procedural.review(procedure.rule_id, approve=True)
    return episodic, semantic, procedural


def isolation_test(
    episodic: EpisodicStore,
    semantic: SemanticStore,
) -> None:
    """Prove user-scoped reads are disjoint and scopeless reads fail loudly."""
    alice = MemoryScope(user_id="cust-4417")
    bob = MemoryScope(user_id="cust-9001")
    alice_episodes = episodic.recall(alice, k=99)
    bob_episodes = episodic.recall(bob, k=99)
    assert all(item.scope.user_id == alice.user_id for item in alice_episodes)
    assert all(item.scope.user_id == bob.user_id for item in bob_episodes)
    assert {item.episode_id for item in alice_episodes}.isdisjoint(
        {item.episode_id for item in bob_episodes}
    )
    alice_pref = semantic.get(alice, "contact_preference")
    bob_pref = semantic.get(bob, "contact_preference")
    assert alice_pref and alice_pref.value == "sms"
    assert bob_pref and bob_pref.value == "phone"
    try:
        episodic.recall(MemoryScope(), k=1)
    except ScopeError:
        pass
    else:
        raise AssertionError("a scopeless read was accepted")


def _retrieval_context(
    question: K.EvalQuestion,
    retriever: Any | None,
    parents: dict[str, str] | None,
) -> tuple[list[str], set[str]]:
    if retriever is None:
        return [], set()
    lines: list[str] = []
    documents: set[str] = set()
    for chunk in retriever.retrieve(question.question, k=3):
        documents.add(chunk.doc_id)
        text = chunk.text
        if parents is not None:
            text = parents.get(chunk.parent_id or chunk.doc_id, text)
        lines.append(f"[DOC {chunk.doc_id} {chunk.chunk_id}] {text}")
    return lines, documents


def answer(
    question: K.EvalQuestion,
    retriever: Any | None,
    parents: dict[str, str] | None,
    episodic: EpisodicStore,
    semantic: SemanticStore,
    procedural: ProceduralStore,
    scope: MemoryScope,
    use_episodic: bool,
    use_semantic: bool,
    use_procedural: bool,
) -> tuple[str, int]:
    """Build tagged context and score only answers grounded in required evidence."""
    lines, documents = _retrieval_context(question, retriever, parents)
    if use_episodic:
        for episode in episodic.recall(scope, k=5):
            lines.append(
                f"[EPISODE {episode.episode_id} {episode.when}] "
                f"{episode.what}; {episode.action}; {episode.outcome}"
            )
    if use_semantic:
        preference = semantic.get(scope, "contact_preference")
        if preference:
            lines.append(
                f"[FACT {preference.key} asserted={preference.asserted}] {preference.value}"
            )
    if use_procedural:
        for procedure in procedural.active():
            lines.append(
                f"[PROCEDURE {procedure.rule_id}] when {procedure.when}; "
                f"then {procedure.then}; evidence={','.join(procedure.provenance)}"
            )
    context = "\n".join(lines)
    approximate_tokens = len(context) // 4
    grounded = bool(documents & question.gold_docs)
    contains_answer = any(
        required.lower() in context.lower()
        for required in question.gold_answer_contains
    )
    return (context if grounded and contains_answer else "insufficient evidence"), approximate_tokens


def run_ablation(embedder: K.OllamaEmbedder) -> list[AblationRow]:
    """Evaluate the eight required retrieval and memory configurations."""
    fixed = K.chunk_fixed(K.POLICY_DOCS)
    recursive = K.chunk_recursive(K.POLICY_DOCS)
    children, parents = K.chunk_parent_child(K.POLICY_DOCS)
    episodic, semantic, procedural = seed_memory()
    scope = MemoryScope(user_id="cust-4417")

    fixed_keyword = K.KeywordRetriever(fixed)
    recursive_keyword = K.KeywordRetriever(recursive)
    recursive_vectors = K.ChromaRetriever(
        recursive,
        embedder,
        collection="cosc726-ablate-recursive",
    )
    parent_vectors = K.ChromaRetriever(
        children,
        embedder,
        parents=parents,
        collection="cosc726-ablate-parent-child",
    )
    configurations = [
        ("no memory at all", None, None, False, False, False),
        ("fixed + keyword", fixed_keyword, None, False, False, False),
        ("recursive + keyword", recursive_keyword, None, False, False, False),
        ("recursive + embeddings", recursive_vectors, None, False, False, False),
        ("parent-child + embeddings", parent_vectors, parents, False, False, False),
        ("+ episodic", parent_vectors, parents, True, False, False),
        ("+ episodic + semantic", parent_vectors, parents, True, True, False),
        ("everything", parent_vectors, parents, True, True, True),
    ]
    rows: list[AblationRow] = []
    for name, retriever, parent_map, use_ep, use_sem, use_proc in configurations:
        if retriever is None:
            retrieval = {"recall": 0.0, "precision": 0.0}
        else:
            retrieval = K.score_retrieval(retriever, K.QUESTIONS)
        answered = 0
        token_total = 0
        for question in K.QUESTIONS:
            response, tokens = answer(
                question,
                retriever,
                parent_map,
                episodic,
                semantic,
                procedural,
                scope,
                use_ep,
                use_sem,
                use_proc,
            )
            answered += response != "insufficient evidence"
            token_total += tokens
        rows.append(
            AblationRow(
                name=name,
                recall=retrieval["recall"],
                precision=retrieval["precision"],
                answered=answered / len(K.QUESTIONS),
                tokens=round(token_total / len(K.QUESTIONS)),
            )
        )
    return rows


def self_test() -> None:
    fixed = K.chunk_fixed(K.POLICY_DOCS)
    search = make_search_tool(K.KeywordRetriever(fixed))
    assert search("x")["error"] == "query_too_short"
    result = search("late delivery credit threshold")
    assert result["ok"] and result["evidence_ids"]
    episodic, semantic, procedural = seed_memory()
    isolation_test(episodic, semantic)
    alice = MemoryScope(user_id="cust-4417")
    assert len(episodic.recall(alice, about="late delivery", k=99)) == 2
    facts = [
        item for item in semantic.history("contact_preference")
        if item.scope.user_id == alice.user_id
    ]
    assert len(facts) == 2 and sum(item.active for item in facts) == 1
    assert procedural.active()[0].status == "active"
    no_answer, tokens = answer(
        K.QUESTIONS[0],
        None,
        None,
        episodic,
        semantic,
        procedural,
        alice,
        False,
        False,
        False,
    )
    assert no_answer == "insufficient evidence" and tokens == 0
    print("ALL SELF-TESTS PASSED")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--ablation", action="store_true")
    args = parser.parse_args()
    if args.ablation:
        print(K.ablate(run_ablation(K.OllamaEmbedder())))
        return
    self_test()


if __name__ == "__main__":
    main()
