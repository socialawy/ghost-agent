"""3-layer persistent memory system.

Layer 1 — MEMORY.md        Lightweight index, always loaded into LLM context.
Layer 2 — topics/*.md      Deep per-topic knowledge files.
Layer 3 — transcript.jsonl  Append-only interaction log (hidden from main context
                            unless explicitly recalled).
"""

import json
import logging
import os
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


# ── Unified Memory facade ────────────────────────────────

class Memory:
    """Combined 3-layer memory with cursor tracking."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.index = MemoryIndex(base_dir / "MEMORY.md")
        self.topics = TopicStore(base_dir / "topics")
        self.transcript = Transcript(base_dir / "transcript.jsonl")
        self._cursor_path = base_dir / ".dream_cursor"
        self._state_path = base_dir / "dream_state.json"
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

    # context builder ──────────────────────────────────────

    def build_context(self, include_recent: int = 15) -> str:
        """Assemble a context string from all three layers for injection into
        the LLM system prompt."""
        parts = ["=== MEMORY INDEX ===", self.index.read()]

        topics = self.topics.read_all()
        if topics:
            parts.append("\n=== TOPIC KNOWLEDGE ===")
            for name, content in topics.items():
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
                parts.append(f"[{role}] {text}")

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