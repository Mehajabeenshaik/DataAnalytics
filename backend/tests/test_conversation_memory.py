"""Tests for Phase 10 — conversation memory / follow-up resolution."""

from conversation_memory import ConversationMemory


def test_record_and_get_context_in_order():
    mem = ConversationMemory(max_turns=5)
    mem.record_turn("s1", "total revenue", "single_metric", "total_revenue")
    mem.record_turn("s1", "by region", "single_metric", "total_revenue", groupby="region")

    ctx = mem.get_context("s1")
    lines = ctx.split("\n")
    assert len(lines) == 2
    assert "total revenue" in lines[0]
    assert "by region" in lines[1]


def test_exceeding_max_turns_drops_oldest():
    mem = ConversationMemory(max_turns=2)
    mem.record_turn("s1", "q1", "single_metric", "a")
    mem.record_turn("s1", "q2", "single_metric", "b")
    mem.record_turn("s1", "q3", "single_metric", "c")

    ctx = mem.get_context("s1")
    assert "q1" not in ctx
    assert "q2" in ctx
    assert "q3" in ctx


def test_unknown_session_returns_empty_no_crash():
    mem = ConversationMemory()
    assert mem.get_context("does-not-exist") == ""


def test_session_eviction_does_not_crash():
    mem = ConversationMemory(max_turns=2, max_sessions=2)
    mem.record_turn("s1", "q", "single_metric", "a")
    mem.record_turn("s2", "q", "single_metric", "a")
    mem.record_turn("s3", "q", "single_metric", "a")  # should evict s1

    assert mem.get_context("s1") == ""
    assert mem.get_context("s3") != ""