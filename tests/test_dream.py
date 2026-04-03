"""Tests for the 4-phase dream engine (dream.py)."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from memory import Memory
from llm_client import LLMClient, RateLimitError
from dream import DreamEngine


@pytest.fixture
def engine(tmp_path):
    """Create a DreamEngine with a fresh memory and mocked LLM."""
    state_dir = tmp_path / ".ghost"
    mem = Memory(state_dir)
    llm = MagicMock(spec=LLMClient)
    return DreamEngine(mem, llm, workspace_root=tmp_path)


class TestShouldDream:
    def test_not_enough_entries(self, engine):
        assert engine.should_dream(min_entries=5) is False

    def test_enough_entries(self, engine):
        for i in range(5):
            engine.memory.transcript.append(role="user", content=f"entry {i}")
        assert engine.should_dream(min_entries=5) is True

    def test_respects_cursor(self, engine):
        for i in range(5):
            engine.memory.transcript.append(role="user", content=f"entry {i}")
        # Advance cursor past all entries
        engine.memory.set_dream_cursor(engine.memory.transcript.byte_size())
        assert engine.should_dream(min_entries=5) is False

    def test_session_aware_needs_sessions(self, engine):
        for i in range(5):
            engine.memory.transcript.append(role="user", content=f"entry {i}", session="session-1")
        # Only 1 session — not enough
        assert engine.should_dream_session_aware(min_entries=5, min_sessions=2) is False

    def test_session_aware_passes(self, engine):
        for i in range(3):
            engine.memory.transcript.append(role="user", content=f"entry {i}", session="session-1")
        for i in range(3):
            engine.memory.transcript.append(role="user", content=f"entry {i}", session="session-2")
        assert engine.should_dream_session_aware(min_entries=5, min_sessions=2) is True


class TestFormatEntries:
    def test_basic_formatting(self, engine):
        entries = [
            {"ts": "2026-04-01T10:00:00", "role": "user", "content": "hello"},
            {"ts": "2026-04-01T10:01:00", "role": "assistant", "content": "hi there"},
        ]
        result = engine._format_entries(entries)
        assert "[2026-04-01T10:00:0" in result
        assert "(user)" in result
        assert "hello" in result
        assert "(assistant)" in result

    def test_truncates_long_content(self, engine):
        entries = [
            {"ts": "2026-04-01T10:00:00", "role": "user", "content": "x" * 3000},
        ]
        result = engine._format_entries(entries)
        assert "…[truncated]" in result
        assert len(result) < 3000

    def test_includes_metadata(self, engine):
        entries = [
            {
                "ts": "2026-04-01T10:00:00",
                "role": "user",
                "content": "fact",
                "confidence": "verified",
                "event": "inject",
            },
        ]
        result = engine._format_entries(entries)
        assert "confidence:verified" in result
        assert "event:inject" in result


class TestVerify:
    def test_file_exists_pass(self, engine, tmp_path):
        test_file = tmp_path / "real_file.txt"
        test_file.write_text("content")

        verifications = [
            {"claim": "real_file.txt exists", "check_type": "file_exists", "check_path": str(test_file)}
        ]
        result = engine._verify(verifications)
        assert result[0]["verified"] is True
        assert result[0]["confidence"] == "high"

    def test_file_exists_fail(self, engine):
        verifications = [
            {"claim": "missing.txt exists", "check_type": "file_exists", "check_path": "/nonexistent/missing.txt"}
        ]
        result = engine._verify(verifications)
        assert result[0]["verified"] is False

    def test_file_contains_match(self, engine, tmp_path):
        test_file = tmp_path / "data.txt"
        test_file.write_text("The project has 107 registered repositories and uses GitHub.")

        verifications = [
            {"claim": "107 registered repositories", "check_type": "file_contains", "check_path": str(test_file)}
        ]
        result = engine._verify(verifications)
        assert result[0]["verified"] is True

    def test_check_type_none(self, engine):
        verifications = [
            {"claim": "something", "check_type": "none"}
        ]
        result = engine._verify(verifications)
        assert result[0]["verified"] is None


class TestApplyTopics:
    def test_writes_topics(self, engine):
        result = {
            "topic_updates": [
                {"topic": "new-topic", "action": "create", "content": "# New Topic\nContent here"},
            ],
            "verifications": [],
        }
        engine._apply_topics(result)
        assert engine.memory.topics.read("new-topic") == "# New Topic\nContent here"

    def test_skips_empty_topic(self, engine):
        result = {
            "topic_updates": [
                {"topic": "", "action": "create", "content": "orphan content"},
                {"topic": "valid", "action": "create", "content": ""},
            ],
            "verifications": [],
        }
        engine._apply_topics(result)
        assert engine.memory.topics.list_topics() == []

    def test_skips_unverified_claims(self, engine):
        result = {
            "topic_updates": [
                {"topic": "suspicious", "action": "create", "content": "user has 9999 projects"},
            ],
            "verifications": [
                {"claim": "user has 9999 projects", "verified": False, "confidence": "low"},
            ],
        }
        engine._apply_topics(result)
        assert engine.memory.topics.read("suspicious") is None


class TestRebuildIndex:
    def test_builds_graph_index(self, engine, sample_consolidate_result):
        engine.memory.topics.write("co-workspace", "content")
        engine._rebuild_index(sample_consolidate_result)

        index = engine.memory.index.read()
        assert "Ghost Agent Memory Index" in index
        assert "co-workspace" in index
        assert "Active Context" in index

    def test_handles_empty_graph(self, engine):
        result = {
            "index_graph": {"nodes": [], "edges": []},
            "active_context": "nothing happening",
            "pending_observations": [],
        }
        engine._rebuild_index(result)
        index = engine.memory.index.read()
        assert "nothing happening" in index


class TestDreamCycle:
    """Test the full dream() flow with mocked LLM calls."""

    @patch.object(DreamEngine, "_call")
    def test_skips_when_no_entries(self, mock_call, engine):
        result = engine.dream()
        assert result["status"] == "skipped"
        mock_call.assert_not_called()

    @patch.object(DreamEngine, "_call")
    def test_full_cycle(self, mock_call, engine, sample_orient_result, sample_consolidate_result):
        # Add entries so dream has something to process
        for i in range(5):
            engine.memory.transcript.append(role="user", content=f"test entry {i}")

        # With <10 topics and topics_to_load in orient, Gather skips LLM call.
        # So we need: orient, consolidate, prune (3 calls, not 4).
        mock_call.side_effect = [
            sample_orient_result,
            sample_consolidate_result,
            {"demotions": [], "removals": [], "stale_observations": [], "prune_log": "Nothing to prune"},
        ]

        result = engine.dream()
        assert result["status"] == "ok"
        assert result["cycle"] == 1
        assert "dream_log" in result

        # Verify cursor was advanced
        assert engine.memory.get_dream_cursor() > 0

        # Verify dream state was cleared
        assert engine.memory.get_dream_state() is None

        # Verify topic was written by consolidate
        assert engine.memory.topics.read("co-workspace") is not None

    @patch.object(DreamEngine, "_call")
    def test_skips_on_no_deltas(self, mock_call, engine):
        for i in range(5):
            engine.memory.transcript.append(role="user", content=f"test {i}")

        mock_call.return_value = {
            "deltas": [],
            "topics_to_load": [],
            "topics_to_create": [],
            "orient_summary": "Nothing meaningful",
        }

        result = engine.dream()
        assert result["status"] == "skipped"
        assert result["reason"] == "no deltas"

    @patch.object(DreamEngine, "_call")
    def test_pauses_on_rate_limit(self, mock_call, engine):
        for i in range(5):
            engine.memory.transcript.append(role="user", content=f"test {i}")

        mock_call.side_effect = RateLimitError("Rate limited", retry_after_seconds=60)

        result = engine.dream()
        assert result["status"] == "paused"
        assert result["retry_after"] == 60

        # Dream state should be saved for resume
        state = engine.memory.get_dream_state()
        assert state is not None

    @patch.object(DreamEngine, "_call")
    def test_resumes_from_saved_state(self, mock_call, engine, sample_orient_result, sample_consolidate_result):
        for i in range(5):
            engine.memory.transcript.append(role="user", content=f"test {i}")

        # Simulate saved state with orient already complete
        entries, cursor = engine.memory.transcript.read_since(0)
        state = {
            "cursor": 0,
            "new_cursor": cursor,
            "entries": entries,
            "phases": {"orient": sample_orient_result},
            "started_at": "2026-04-01T00:00:00",
        }
        engine.memory.set_dream_state(state)

        # Orient is cached, Gather skips LLM (small topic set).
        # Only need: consolidate, prune (2 calls)
        mock_call.side_effect = [
            sample_consolidate_result,
            {"demotions": [], "removals": [], "stale_observations": [], "prune_log": "clean"},
        ]

        result = engine.dream()
        assert result["status"] == "ok"
        # Orient cached + Gather skipped = only consolidate + prune
        assert mock_call.call_count == 2


class TestQualityScoring:
    def test_clean_when_no_change(self, engine):
        before = {"topic-a": "# Topic A\n107 projects"}
        after = {"topic-a": "# Topic A\n107 projects"}
        result = engine._score_quality(before, after)
        assert result["verdict"] == "clean"
        assert result["warnings"] == []

    def test_warns_on_shrink(self, engine):
        before = {"topic-a": "x" * 1000}
        after = {"topic-a": "x" * 500}
        result = engine._score_quality(before, after)
        assert result["verdict"] == "degraded"
        assert any("shrank" in w for w in result["warnings"])

    def test_warns_on_deleted_topic(self, engine):
        before = {"topic-a": "content here"}
        after = {}
        result = engine._score_quality(before, after)
        assert any("deleted" in w for w in result["warnings"])

    def test_tracks_created_topic(self, engine):
        before = {}
        after = {"new-topic": "# New\nFresh content"}
        result = engine._score_quality(before, after)
        assert result["verdict"] == "clean"
        assert result["scores"]["new-topic"]["action"] == "created"

    def test_warns_on_lost_terms(self, engine):
        before = {"t": "GRID project has 865 tests on GitHub"}
        after = {"t": "Project has tests"}
        result = engine._score_quality(before, after)
        assert result["scores"]["t"]["terms_lost"]

    def test_extract_key_terms(self, engine):
        text = "Grid has 865 tests, parallaxin uses GitHub Pages at E:\\co\\GRID"
        terms = engine._extract_key_terms(text)
        assert "865" in terms
        assert "Grid" in terms  # Capitalized word
        assert "GitHub" in terms  # CamelCase
        assert "E:\\co\\GRID" in terms  # File path


class TestCrossLinkGraph:
    def test_no_links_with_one_topic(self, engine):
        engine.memory.topics.write("only-one", "# Single topic\nSome content here")
        result = engine._cross_link_graph()
        assert result == []

    def test_links_topics_with_shared_terms(self, engine):
        engine.memory.topics.write("project-a", "# Project Alpha\nUses GitHub Actions for testing with pytest framework and Docker containers")
        engine.memory.topics.write("project-b", "# Project Beta\nDeployed via GitHub Actions with Docker containers and pytest validation")
        result = engine._cross_link_graph()
        assert len(result) >= 1
        assert result[0]["from"] == "project-a"
        assert result[0]["to"] == "project-b"

    def test_no_links_for_unrelated_topics(self, engine):
        engine.memory.topics.write("cooking", "# Recipes\nPasta carbonara with eggs and cheese")
        engine.memory.topics.write("physics", "# Quantum\nEntanglement and superposition states")
        result = engine._cross_link_graph()
        assert result == []


class TestSnapshot:
    def test_snapshot_and_read(self, engine):
        engine.memory.topics.write("alpha", "content alpha")
        engine.memory.topics.write("beta", "content beta")
        engine.memory.topics.snapshot(1)

        snap = engine.memory.topics.get_snapshot(1)
        assert snap == {"alpha": "content alpha", "beta": "content beta"}

    def test_snapshot_specific_topics(self, engine):
        engine.memory.topics.write("alpha", "content alpha")
        engine.memory.topics.write("beta", "content beta")
        engine.memory.topics.snapshot(1, topics=["alpha"])

        snap = engine.memory.topics.get_snapshot(1)
        assert "alpha" in snap
        assert "beta" not in snap

    def test_list_snapshots(self, engine):
        engine.memory.topics.write("t", "content")
        engine.memory.topics.snapshot(3)
        engine.memory.topics.snapshot(5)
        engine.memory.topics.snapshot(1)

        assert engine.memory.topics.list_snapshots() == [1, 3, 5]

    def test_prune_snapshots(self, engine):
        engine.memory.topics.write("t", "content")
        for i in range(7):
            engine.memory.topics.snapshot(i)

        engine.memory.topics.prune_snapshots(keep=3)
        remaining = engine.memory.topics.list_snapshots()
        assert remaining == [4, 5, 6]

    def test_get_nonexistent_snapshot(self, engine):
        assert engine.memory.topics.get_snapshot(999) == {}
