"""Tests for multi-workspace master index (memory.py MasterIndex)."""

from pathlib import Path

import pytest

from memory import Memory, MasterIndex


@pytest.fixture
def master(tmp_path):
    """MasterIndex with a temp path instead of ~/.ghost/."""
    return MasterIndex(path=tmp_path / "master.json")


@pytest.fixture
def two_workspaces(tmp_path):
    """Create two workspace .ghost/ directories with topics."""
    ws_a = tmp_path / "project-a" / ".ghost"
    ws_b = tmp_path / "project-b" / ".ghost"
    mem_a = Memory(ws_a)
    mem_b = Memory(ws_b)
    mem_a.topics.write("alpha", "# Alpha\nUses pytest for testing with 865 tests")
    mem_b.topics.write("beta", "# Beta\nDeploys to Kubernetes with Helm charts")
    return ws_a, ws_b, mem_a, mem_b


class TestMasterIndex:
    def test_register_and_list(self, master, tmp_path):
        ghost_dir = tmp_path / "proj" / ".ghost"
        Memory(ghost_dir)  # Creates the structure
        master.register("my-project", ghost_dir)

        workspaces = master.list_workspaces()
        assert "my-project" in workspaces
        assert workspaces["my-project"]["exists"] is True

    def test_list_empty(self, master):
        assert master.list_workspaces() == {}

    def test_unregister(self, master, tmp_path):
        ghost_dir = tmp_path / "proj" / ".ghost"
        Memory(ghost_dir)
        master.register("proj", ghost_dir)
        assert master.unregister("proj") is True
        assert master.list_workspaces() == {}

    def test_unregister_nonexistent(self, master):
        assert master.unregister("missing") is False

    def test_marks_stale_workspace(self, master, tmp_path):
        # Register a path that doesn't exist
        fake_path = tmp_path / "deleted" / ".ghost"
        master.register("ghost-project", fake_path)

        workspaces = master.list_workspaces()
        assert workspaces["ghost-project"]["exists"] is False

    def test_search_finds_in_memory_index(self, master, two_workspaces):
        ws_a, ws_b, _, _ = two_workspaces
        master.register("project-a", ws_a)
        master.register("project-b", ws_b)

        # MEMORY.md contains "Ghost Agent Memory Index" by default
        results = master.search("Memory Index")
        assert len(results) >= 2

    def test_search_finds_in_topics(self, master, two_workspaces):
        ws_a, ws_b, _, _ = two_workspaces
        master.register("project-a", ws_a)
        master.register("project-b", ws_b)

        results = master.search("pytest")
        assert any(r["workspace"] == "project-a" for r in results)
        assert not any(r["workspace"] == "project-b" and "alpha" in r.get("match_in", "") for r in results)

    def test_search_no_results(self, master, two_workspaces):
        ws_a, ws_b, _, _ = two_workspaces
        master.register("project-a", ws_a)
        results = master.search("nonexistent_term_xyz")
        assert results == []

    def test_register_updates_existing(self, master, tmp_path):
        ghost_dir = tmp_path / "proj" / ".ghost"
        mem = Memory(ghost_dir)
        master.register("proj", ghost_dir)

        mem.topics.write("new-topic", "content")
        master.register("proj", ghost_dir)

        workspaces = master.list_workspaces()
        assert workspaces["proj"]["topic_count"] == 1
