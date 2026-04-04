"""3-layer persistent memory system.

Layer 1 — MEMORY.md        Lightweight index, always loaded into LLM context.
Layer 2 — topics/*.md      Deep per-topic knowledge files.
Layer 3 — transcript.jsonl  Append-only interaction log (hidden from main context
                            unless explicitly recalled).
"""

import json
import logging
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ghost.memory")


# ── File locking ─────────────────────────────────────────

@contextmanager
def _file_lock(f):
    """Advisory file lock — platform-aware. Locks the open file handle during writes."""
    locked = False
    lock_pos = 0
    try:
        if sys.platform == "win32":
            import msvcrt
            lock_pos = f.tell()
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            locked = True
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
    except (OSError, IOError):
        logger.debug("File lock unavailable, proceeding without lock")
    try:
        yield
    finally:
        if locked:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    f.seek(lock_pos)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except (OSError, IOError):
                pass


# ── Layer 3: Append-only transcript ──────────────────────

class Transcript:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, role: str, content: str, session: str = "default", **meta):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "content": content,
            "session": session,
            **meta,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            with _file_lock(f):
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_since(self, cursor: int = 0) -> tuple[list[dict], int]:
        """Read entries from byte-offset *cursor*.  Returns (entries, new_cursor)."""
        entries = []
        with open(self.path, "r", encoding="utf-8") as f:
            f.seek(cursor)
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning("Skipping corrupt transcript line at offset ~%d", cursor)
            new_cursor = f.tell()
        return entries, new_cursor

    def read_all(self) -> list[dict]:
        entries, _ = self.read_since(0)
        return entries

    def entry_count(self) -> int:
        if not self.path.exists():
            return 0
        with open(self.path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())

    def byte_size(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0


# ── Layer 2: Topic knowledge store ───────────────────────

class TopicStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def list_topics(self) -> list[str]:
        return sorted(f.stem for f in self.directory.glob("*.md"))

    def read(self, topic: str) -> Optional[str]:
        path = self.directory / f"{topic}.md"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def write(self, topic: str, content: str):
        path = self.directory / f"{topic}.md"
        path.write_text(content, encoding="utf-8")
        logger.info("Wrote topic: %s (%d chars)", topic, len(content))

    def read_all(self) -> dict[str, str]:
        return {t: self.read(t) for t in self.list_topics()}

    def snapshot(self, cycle: int, topics: list[str] | None = None):
        """Save copies of topic files to dream_history/cycle_N/ for diffing."""
        history_dir = self.directory.parent / "dream_history" / f"cycle_{cycle}"
        history_dir.mkdir(parents=True, exist_ok=True)
        targets = topics if topics else self.list_topics()
        for t in targets:
            content = self.read(t)
            if content:
                (history_dir / f"{t}.md").write_text(content, encoding="utf-8")

    def get_snapshot(self, cycle: int) -> dict[str, str]:
        """Read a saved snapshot for a given cycle."""
        history_dir = self.directory.parent / "dream_history" / f"cycle_{cycle}"
        if not history_dir.exists():
            return {}
        return {
            f.stem: f.read_text(encoding="utf-8")
            for f in sorted(history_dir.glob("*.md"))
        }

    def list_snapshots(self) -> list[int]:
        """Return sorted list of available snapshot cycle numbers."""
        history_dir = self.directory.parent / "dream_history"
        if not history_dir.exists():
            return []
        cycles = []
        for d in history_dir.iterdir():
            if d.is_dir() and d.name.startswith("cycle_"):
                try:
                    cycles.append(int(d.name.split("_", 1)[1]))
                except ValueError:
                    pass
        return sorted(cycles)

    def prune_snapshots(self, keep: int = 5):
        """Remove old snapshots, keeping the most recent N."""
        cycles = self.list_snapshots()
        if len(cycles) <= keep:
            return
        history_dir = self.directory.parent / "dream_history"
        for c in cycles[:-keep]:
            import shutil
            snap_dir = history_dir / f"cycle_{c}"
            if snap_dir.exists():
                shutil.rmtree(snap_dir)


# ── Layer 1: Memory index ────────────────────────────────

class MemoryIndex:
    def __init__(self, path: Path):
        self.path = path
        if not self.path.exists():
            self._init()

    def _init(self):
        self.write(
            "# Ghost Agent Memory Index\n"
            f"Last updated: {datetime.now(timezone.utc).isoformat()}\n"
            "Dream cycle: 0\n\n"
            "## Active Context\n"
            "- Status: freshly initialized\n\n"
            "## Topic Files\n"
            "(none yet)\n\n"
            "## Pending Observations\n"
            "(none yet)\n"
        )

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def write(self, content: str):
        self.path.write_text(content, encoding="utf-8")


# ── Compact Cache ───────────────────────────────────────

class CompactCache:
    """Cache (start_offset, end_offset) -> summary for compacted transcript regions.

    Avoids re-summarizing the same transcript segments during context building.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"regions": []}

    def _save(self, data: dict):
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get(self, start: int, end: int) -> Optional[str]:
        """Return cached summary for a byte range, or None."""
        data = self._load()
        for region in data["regions"]:
            if region["start"] == start and region["end"] == end:
                return region["summary"]
        return None

    def put(self, start: int, end: int, summary: str):
        """Store a summary for a byte range."""
        data = self._load()
        # Replace existing if same range
        data["regions"] = [r for r in data["regions"] if not (r["start"] == start and r["end"] == end)]
        data["regions"].append({"start": start, "end": end, "summary": summary})
        # Keep at most 20 cached regions
        if len(data["regions"]) > 20:
            data["regions"] = data["regions"][-20:]
        self._save(data)

    def invalidate_after(self, offset: int):
        """Remove cached regions that start after the given offset (transcript changed)."""
        data = self._load()
        data["regions"] = [r for r in data["regions"] if r["start"] < offset]
        self._save(data)


# ── Unified Memory facade ────────────────────────────────

class Memory:
    """Combined 3-layer memory with cursor tracking."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.index = MemoryIndex(base_dir / "MEMORY.md")
        self.topics = TopicStore(base_dir / "topics")
        self.transcript = Transcript(base_dir / "transcript.jsonl")
        self.compact_cache = CompactCache(base_dir / "compact_cache.json")
        self._cursor_path = base_dir / ".dream_cursor"
        self._state_path = base_dir / "dream_state.json"
        self._refs_path = base_dir / ".topic_refs.json"
        self._write_spec()

    def _write_spec(self):
        """Write GHOST_SPEC.md — the integration contract for any AI tool reading this directory."""
        spec = self.base_dir / "GHOST_SPEC.md"
        if spec.exists() and spec.stat().st_size > 0:
            return
        spec.write_text("""\
# Ghost Agent Memory — Integration Spec

## For AI Assistants / IDEs / Agents

This directory contains persistent memory for the workspace.
Read these files to get full context on the user's projects and decisions.

### Quick Start (paste into any AI chat)
Read these files for context:

.ghost/MEMORY.md (index — start here)
.ghost/topics/*.md (detailed knowledge per topic)

### File Format
- `MEMORY.md` — Graph-indexed overview. Nodes map to topic files.
- `topics/*.md` — One file per knowledge domain. Pure markdown.
- `transcript.jsonl` — Raw interaction log (usually not needed).
- `sources.json` — Linked source files the dream engine monitors.
- `daemon.json` — KAIROS daemon state (tick count, last dream).

### Writing Convention
- Any tool can READ freely.
- Only Ghost's dream engine WRITES to topics/ and MEMORY.md.
- To contribute knowledge: append to `transcript.jsonl` or use `ghost inject`.

### Example: Claude Code / Windsurf / Cursor Integration
Add to your project's `.claude/instructions.md` or equivalent:
Before starting work, read .ghost/MEMORY.md and relevant .ghost/topics/*.md
files to understand project context and recent decisions.
""", encoding="utf-8")

    # dream cursor ─────────────────────────────────────────

    def get_dream_cursor(self) -> int:
        if self._cursor_path.exists():
            try:
                return int(self._cursor_path.read_text().strip())
            except ValueError:
                return 0
        return 0

    def set_dream_cursor(self, cursor: int):
        self._cursor_path.write_text(str(cursor))

    # dream state persistence ─────────────────────────────

    def get_dream_state(self) -> Optional[dict]:
        """Load incomplete dream state if it exists."""
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Could not load dream state: %s", exc)
        return None

    def set_dream_state(self, state: Optional[dict]):
        """Save current dream progress or delete if finished."""
        if state is None:
            if self._state_path.exists():
                self._state_path.unlink()
        else:
            self._state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    # topic reference tracking ────────────────────────────

    def track_reference(self, topic: str):
        """Record that a topic was referenced in the current turn."""
        refs = self._load_refs()
        refs[topic] = datetime.now(timezone.utc).isoformat()
        self._save_refs(refs)

    def _load_refs(self) -> dict:
        if self._refs_path.exists():
            try:
                return json.loads(self._refs_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_refs(self, refs: dict):
        self._refs_path.write_text(json.dumps(refs), encoding="utf-8")

    def _get_recent_refs(self, max_age_seconds: float = 1800) -> set[str]:
        """Return topics referenced within the last max_age_seconds."""
        refs = self._load_refs()
        now = datetime.now(timezone.utc)
        recent = set()
        for topic, ts in refs.items():
            try:
                dt = datetime.fromisoformat(ts)
                if (now - dt).total_seconds() <= max_age_seconds:
                    recent.add(topic)
            except Exception:
                pass
        return recent

    # context builder ──────────────────────────────────────

    @staticmethod
    def _estimate_chars(token_budget: int) -> int:
        """Convert token budget to approximate character budget (4 chars/token)."""
        return token_budget * 4

    def build_context(self, include_recent: int = 15, token_budget: int = 0) -> str:
        """Assemble a context string from all three layers.

        If token_budget > 0, topics that don't fit are collapsed to a one-line
        header. Recently referenced topics get priority for full inclusion.
        """
        parts = ["=== MEMORY INDEX ===", self.index.read()]
        index_chars = sum(len(p) for p in parts)

        topics = self.topics.read_all()
        recent_refs = self._get_recent_refs() if token_budget > 0 else set()
        char_budget = self._estimate_chars(token_budget) if token_budget > 0 else 0

        # Reserve 30% of budget for transcript
        topic_budget = int(char_budget * 0.7) - index_chars if char_budget > 0 else 0
        transcript_budget = int(char_budget * 0.3) if char_budget > 0 else 0

        if topics:
            parts.append("\n=== TOPIC KNOWLEDGE ===")
            topic_chars_used = 0

            # Sort: recently-referenced topics first
            sorted_topics = sorted(topics.keys(), key=lambda t: (t not in recent_refs, t))

            for name in sorted_topics:
                content = topics[name]
                if token_budget > 0:
                    if topic_chars_used + len(content) > topic_budget and name not in recent_refs:
                        # Collapse
                        parts.append(f"\n--- {name} ---")
                        parts.append(f"[COLLAPSED: {len(content)} chars, /recall {name}]")
                        topic_chars_used += 60  # overhead for collapsed line
                    else:
                        parts.append(f"\n--- {name} ---")
                        parts.append(content)
                        topic_chars_used += len(content)
                else:
                    parts.append(f"\n--- {name} ---")
                    parts.append(content)

        # Only the tail of the transcript — the rest is for dreaming
        entries = self.transcript.read_all()
        recent = entries[-include_recent:]
        if recent:
            parts.append("\n=== RECENT INTERACTIONS (last %d) ===" % len(recent))
            for e in recent:
                role = e.get("role", "?")
                text = e.get("content", "")
                if len(text) > 600:
                    text = text[:600] + "…"
                line = f"[{role}] {text}"
                if token_budget > 0 and transcript_budget > 0:
                    transcript_budget -= len(line)
                    if transcript_budget < 0:
                        parts.append(f"[...{len(recent)} entries, use /context for full view]")
                        break
                parts.append(line)

        return "\n".join(parts)

    # status ───────────────────────────────────────────────

    def status(self) -> dict:
        cursor = self.get_dream_cursor()
        undreamed, _ = self.transcript.read_since(cursor)
        return {
            "topics": self.topics.list_topics(),
            "topic_count": len(self.topics.list_topics()),
            "transcript_entries": self.transcript.entry_count(),
            "transcript_bytes": self.transcript.byte_size(),
            "dream_cursor": cursor,
            "undreamed_entries": len(undreamed),
        }


# ── Multi-Workspace Master Index ────────────────────────

class MasterIndex:
    """Cross-workspace registry at ~/.ghost/master.json."""

    def __init__(self, path: Path = None):
        if path is None:
            path = Path.home() / ".ghost" / "master.json"
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"workspaces": {}}

    def _save(self, data: dict):
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def register(self, name: str, ghost_dir: Path):
        """Register a workspace in the master index."""
        data = self._load()
        mem = Memory(ghost_dir) if ghost_dir.exists() else None
        data["workspaces"][name] = {
            "path": str(ghost_dir),
            "registered": datetime.now(timezone.utc).isoformat(),
            "topic_count": len(mem.topics.list_topics()) if mem else 0,
        }
        self._save(data)

    def unregister(self, name: str) -> bool:
        data = self._load()
        if name in data["workspaces"]:
            del data["workspaces"][name]
            self._save(data)
            return True
        return False

    def list_workspaces(self) -> dict:
        """Return all workspaces, marking stale ones."""
        data = self._load()
        for name, info in data["workspaces"].items():
            info["exists"] = Path(info["path"]).exists()
        return data["workspaces"]

    def search(self, query: str) -> list[dict]:
        """Search across all workspace MEMORY.md files for a query."""
        results = []
        for name, info in self.list_workspaces().items():
            ghost_dir = Path(info["path"])
            if not ghost_dir.exists():
                continue
            index_path = ghost_dir / "MEMORY.md"
            if not index_path.exists():
                continue
            content = index_path.read_text(encoding="utf-8").lower()
            if query.lower() in content:
                results.append({
                    "workspace": name,
                    "path": info["path"],
                    "match_in": "MEMORY.md",
                })
            # Also search topics
            topics_dir = ghost_dir / "topics"
            if topics_dir.exists():
                for f in topics_dir.glob("*.md"):
                    try:
                        tc = f.read_text(encoding="utf-8").lower()
                        if query.lower() in tc:
                            results.append({
                                "workspace": name,
                                "path": info["path"],
                                "match_in": f"topics/{f.stem}",
                            })
                    except Exception:
                        pass
        return results