"""Tests for the 3-layer memory system (memory.py)."""

import json
from pathlib import Path

from memory import Memory, Transcript, TopicStore, MemoryIndex


class TestTranscript:
    def test_append_creates_entry(self, ghost_dir):
        t = Transcript(ghost_dir / "transcript.jsonl")
        t.append(role="user", content="hello world")

        entries = t.read_all()
        assert len(entries) == 1
        assert entries[0]["role"] == "user"
        assert entries[0]["content"] == "hello world"
        assert "ts" in entries[0]

    def test_append_preserves_meta(self, ghost_dir):
        t = Transcript(ghost_dir / "transcript.jsonl")
        t.append(role="system", content="test", event="inject", confidence="verified")

        entries = t.read_all()
        assert entries[0]["event"] == "inject"
        assert entries[0]["confidence"] == "verified"

    def test_read_since_cursor(self, ghost_dir):
        t = Transcript(ghost_dir / "transcript.jsonl")
        t.append(role="user", content="first")
        _, cursor = t.read_since(0)

        t.append(role="user", content="second")
        t.append(role="user", content="third")

        entries, new_cursor = t.read_since(cursor)
        assert len(entries) == 2
        assert entries[0]["content"] == "second"
        assert entries[1]["content"] == "third"
        assert new_cursor > cursor

    def test_read_since_empty(self, ghost_dir):
        t = Transcript(ghost_dir / "transcript.jsonl")
        entries, cursor = t.read_since(0)
        assert entries == []
        assert cursor == 0

    def test_entry_count(self, ghost_dir):
        t = Transcript(ghost_dir / "transcript.jsonl")
        assert t.entry_count() == 0

        t.append(role="user", content="a")
        t.append(role="user", content="b")
        assert t.entry_count() == 2

    def test_byte_size(self, ghost_dir):
        t = Transcript(ghost_dir / "transcript.jsonl")
        assert t.byte_size() == 0

        t.append(role="user", content="hello")
        assert t.byte_size() > 0

    def test_skips_corrupt_lines(self, ghost_dir):
        path = ghost_dir / "transcript.jsonl"
        path.write_text('{"role":"user","content":"good"}\nNOT JSON\n{"role":"user","content":"also good"}\n')
        t = Transcript(path)
        entries = t.read_all()
        assert len(entries) == 2


class TestTopicStore:
    def test_write_and_read(self, ghost_dir):
        ts = TopicStore(ghost_dir / "topics")
        ts.write("test-topic", "# Test\nSome content")

        content = ts.read("test-topic")
        assert content == "# Test\nSome content"

    def test_read_nonexistent(self, ghost_dir):
        ts = TopicStore(ghost_dir / "topics")
        assert ts.read("nonexistent") is None

    def test_list_topics(self, ghost_dir):
        ts = TopicStore(ghost_dir / "topics")
        ts.write("alpha", "content a")
        ts.write("beta", "content b")
        ts.write("gamma", "content c")

        topics = ts.list_topics()
        assert topics == ["alpha", "beta", "gamma"]

    def test_list_topics_empty(self, ghost_dir):
        ts = TopicStore(ghost_dir / "topics")
        assert ts.list_topics() == []

    def test_read_all(self, ghost_dir):
        ts = TopicStore(ghost_dir / "topics")
        ts.write("x", "content x")
        ts.write("y", "content y")

        all_topics = ts.read_all()
        assert all_topics == {"x": "content x", "y": "content y"}

    def test_overwrite(self, ghost_dir):
        ts = TopicStore(ghost_dir / "topics")
        ts.write("topic", "version 1")
        ts.write("topic", "version 2")
        assert ts.read("topic") == "version 2"


class TestMemoryIndex:
    def test_init_creates_file(self, ghost_dir):
        idx = MemoryIndex(ghost_dir / "MEMORY.md")
        content = idx.read()
        assert "Ghost Agent Memory Index" in content
        assert "Dream cycle: 0" in content

    def test_write_and_read(self, ghost_dir):
        idx = MemoryIndex(ghost_dir / "MEMORY.md")
        idx.write("# Custom Index\nDream cycle: 5")
        assert idx.read() == "# Custom Index\nDream cycle: 5"

    def test_no_overwrite_existing(self, ghost_dir):
        path = ghost_dir / "MEMORY.md"
        path.write_text("# Existing content")
        idx = MemoryIndex(path)
        assert idx.read() == "# Existing content"


class TestMemory:
    def test_init_creates_structure(self, tmp_path):
        state_dir = tmp_path / ".ghost"
        mem = Memory(state_dir)

        assert state_dir.exists()
        assert (state_dir / "MEMORY.md").exists()
        assert (state_dir / "topics").is_dir()
        assert (state_dir / "transcript.jsonl").exists()
        assert (state_dir / "GHOST_SPEC.md").exists()

    def test_dream_cursor(self, tmp_path):
        mem = Memory(tmp_path / ".ghost")
        assert mem.get_dream_cursor() == 0

        mem.set_dream_cursor(1234)
        assert mem.get_dream_cursor() == 1234

    def test_dream_state_persistence(self, tmp_path):
        mem = Memory(tmp_path / ".ghost")
        assert mem.get_dream_state() is None

        state = {"cursor": 100, "phases": {"orient": {"deltas": []}}}
        mem.set_dream_state(state)
        loaded = mem.get_dream_state()
        assert loaded["cursor"] == 100
        assert "orient" in loaded["phases"]

        # Clear state
        mem.set_dream_state(None)
        assert mem.get_dream_state() is None

    def test_build_context(self, tmp_path):
        mem = Memory(tmp_path / ".ghost")
        mem.topics.write("project-a", "# Project A\n100 tests passing")
        mem.transcript.append(role="user", content="hello ghost")

        ctx = mem.build_context()
        assert "MEMORY INDEX" in ctx
        assert "project-a" in ctx
        assert "100 tests passing" in ctx
        assert "hello ghost" in ctx

    def test_build_context_truncates_long_entries(self, tmp_path):
        mem = Memory(tmp_path / ".ghost")
        long_text = "x" * 1000
        mem.transcript.append(role="user", content=long_text)

        ctx = mem.build_context()
        # Content should be truncated at 600 chars
        assert "x" * 600 in ctx
        assert "x" * 601 not in ctx

    def test_status(self, tmp_path):
        mem = Memory(tmp_path / ".ghost")
        mem.topics.write("t1", "content")
        mem.transcript.append(role="user", content="entry")

        s = mem.status()
        assert s["topic_count"] == 1
        assert s["topics"] == ["t1"]
        assert s["transcript_entries"] == 1
        assert s["transcript_bytes"] > 0
        assert s["dream_cursor"] == 0
        assert s["undreamed_entries"] == 1

    def test_ghost_spec_not_overwritten(self, tmp_path):
        state_dir = tmp_path / ".ghost"
        state_dir.mkdir()
        spec = state_dir / "GHOST_SPEC.md"
        spec.write_text("# Custom Spec")

        mem = Memory(state_dir)
        assert mem.base_dir == state_dir
        assert spec.read_text() == "# Custom Spec"
