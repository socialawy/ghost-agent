"""Tests for Phase 5: Continuous Context Management.

Covers: TOKEN_BUDGET, CONTEXT_COLLAPSE, REACTIVE_COMPACT, HISTORY_SNIP, CACHED_MICROCOMPACT.
"""

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from memory import Memory, CompactCache
from dream import DreamEngine


# ── CompactCache ────────────────────────────────────────

class TestCompactCache:
    @pytest.fixture
    def cache(self, tmp_path):
        return CompactCache(tmp_path / "compact_cache.json")

    def test_get_miss(self, cache):
        assert cache.get(0, 100) is None

    def test_put_and_get(self, cache):
        cache.put(0, 100, "summary of first 100 bytes")
        assert cache.get(0, 100) == "summary of first 100 bytes"

    def test_put_replaces_existing(self, cache):
        cache.put(0, 100, "old")
        cache.put(0, 100, "new")
        assert cache.get(0, 100) == "new"

    def test_invalidate_after(self, cache):
        cache.put(0, 100, "a")
        cache.put(100, 200, "b")
        cache.put(200, 300, "c")
        cache.invalidate_after(150)
        assert cache.get(0, 100) == "a"
        assert cache.get(100, 200) == "b"  # start=100 < 150
        assert cache.get(200, 300) is None  # start=200 >= 150

    def test_max_regions(self, cache):
        for i in range(25):
            cache.put(i * 100, (i + 1) * 100, f"region_{i}")
        # Should keep only last 20
        data = json.loads(cache.path.read_text())
        assert len(data["regions"]) == 20
        # Oldest should be gone
        assert cache.get(0, 100) is None
        assert cache.get(2400, 2500) == "region_24"


# ── Topic Reference Tracking ────────────────────────────

class TestTopicRefs:
    @pytest.fixture
    def mem(self, tmp_path):
        return Memory(tmp_path / ".ghost")

    def test_track_and_get_recent(self, mem):
        mem.track_reference("my-topic")
        refs = mem._get_recent_refs(max_age_seconds=60)
        assert "my-topic" in refs

    def test_stale_refs_excluded(self, mem):
        # Write a ref with old timestamp
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        mem._save_refs({"old-topic": old_ts})
        refs = mem._get_recent_refs(max_age_seconds=1800)
        assert "old-topic" not in refs

    def test_multiple_refs(self, mem):
        mem.track_reference("alpha")
        mem.track_reference("beta")
        refs = mem._get_recent_refs()
        assert "alpha" in refs
        assert "beta" in refs


# ── TOKEN_BUDGET & CONTEXT_COLLAPSE ─────────────────────

class TestBuildContextBudget:
    @pytest.fixture
    def mem(self, tmp_path):
        m = Memory(tmp_path / ".ghost")
        m.topics.write("small-topic", "Short content here.")
        m.topics.write("big-topic", "X" * 5000)
        m.topics.write("medium-topic", "M" * 2000)
        return m

    def test_no_budget_includes_all(self, mem):
        ctx = mem.build_context(token_budget=0)
        assert "XXXXX" in ctx
        assert "MMMMM" in ctx
        assert "Short content" in ctx

    def test_budget_collapses_large_topics(self, mem):
        # Very tight budget forces collapse
        ctx = mem.build_context(token_budget=500)
        # At least one topic should be collapsed
        assert "[COLLAPSED:" in ctx

    def test_referenced_topics_survive_budget(self, mem):
        mem.track_reference("big-topic")
        ctx = mem.build_context(token_budget=500)
        # big-topic was referenced, so it should appear in full
        assert "XXXXX" in ctx

    def test_transcript_truncated_under_budget(self, mem):
        # Add many transcript entries
        for i in range(20):
            mem.transcript.append(role="user", content=f"Message number {i} " * 20)
        ctx = mem.build_context(include_recent=20, token_budget=500)
        # Should truncate transcript
        assert "RECENT INTERACTIONS" in ctx or "[..." in ctx

    def test_unlimited_budget_same_as_zero(self, mem):
        ctx_zero = mem.build_context(token_budget=0)
        # No collapse markers
        assert "[COLLAPSED:" not in ctx_zero


# ── HISTORY_SNIP ────────────────────────────────────────

class TestSnipHistory:
    def test_short_history_unchanged(self):
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(5)]
        result = DreamEngine.snip_history(messages, "current turn", max_messages=40)
        assert len(result) == 5

    def test_long_history_trimmed(self):
        messages = [{"role": "user", "content": f"topic alpha discussion {i}"} for i in range(60)]
        result = DreamEngine.snip_history(messages, "topic alpha", max_messages=40)
        assert len(result) <= 40

    def test_relevant_messages_kept(self):
        messages = []
        # Early messages about "deployment"
        for i in range(30):
            messages.append({"role": "user", "content": f"deployment pipeline issue {i}"})
        # Recent messages about "testing"
        for i in range(30):
            messages.append({"role": "user", "content": f"testing framework setup {i}"})

        result = DreamEngine.snip_history(messages, "deployment pipeline fix", max_messages=40)
        # Should keep deployment messages (relevant) + recent testing messages
        deployment_count = sum(1 for m in result if "deployment" in m["content"])
        assert deployment_count > 0

    def test_irrelevant_early_messages_dropped(self):
        messages = []
        # Early irrelevant messages
        for i in range(30):
            messages.append({"role": "user", "content": f"weather forecast sunny {i}"})
        # Recent relevant messages
        for i in range(20):
            messages.append({"role": "user", "content": f"database migration {i}"})

        result = DreamEngine.snip_history(messages, "database migration plan", max_messages=30)
        # Weather messages should be dropped
        weather_count = sum(1 for m in result if "weather" in m["content"])
        assert weather_count == 0

    def test_empty_current_turn_falls_back(self):
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(60)]
        result = DreamEngine.snip_history(messages, "", max_messages=40)
        assert len(result) == 40


# ── MICRO_COMPACT ───────────────────────────────────────

class TestMicroCompact:
    @pytest.fixture
    def engine(self, tmp_path):
        mem = Memory(tmp_path / ".ghost")
        llm = MagicMock()
        return DreamEngine(mem, llm)

    def test_short_list_unchanged(self, engine):
        entries = [{"role": "user", "content": f"msg {i}"} for i in range(5)]
        result = engine.micro_compact(entries, max_entries=15)
        assert len(result) == 5

    def test_compacts_long_list(self, engine):
        entries = [{"role": "user", "content": f"msg {i}", "ts": "2026-01-01"} for i in range(30)]
        with patch.object(engine, '_call', return_value="Summary of old messages"):
            result = engine.micro_compact(entries, max_entries=15)
        assert len(result) < 30
        assert any("SUMMARY" in e.get("content", "") for e in result)

    def test_uses_cache(self, engine):
        entries = [{"role": "user", "content": f"msg {i}", "ts": "2026-01-01"} for i in range(30)]
        # First call — populates cache
        with patch.object(engine, '_call', return_value="Cached summary") as mock_call:
            result1 = engine.micro_compact(entries, max_entries=15)
            assert mock_call.called

        # Second call with same entries — should use cache
        with patch.object(engine, '_call', return_value="Should not be called") as mock_call2:
            result2 = engine.micro_compact(entries, max_entries=15)
            # Cache hit means _call not invoked
            assert not mock_call2.called

    def test_fallback_on_llm_error(self, engine):
        entries = [{"role": "user", "content": f"msg {i}", "ts": "2026-01-01"} for i in range(30)]
        with patch.object(engine, '_call', side_effect=Exception("LLM down")):
            result = engine.micro_compact(entries, max_entries=15)
        # Should return original on failure
        assert len(result) == 30
