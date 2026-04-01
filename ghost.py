#!/usr/bin/env python3
"""Ghost Agent — local memory/dream/daemon system.

Usage:
    python ghost.py init                   Initialize .ghost/ state directory
    python ghost.py chat                   Interactive chat with persistent memory
    python ghost.py dream                  Run one dream consolidation cycle
    python ghost.py compact                Compact old transcript entries
    python ghost.py status                 Show memory status
    python ghost.py daemon                 Start KAIROS always-on daemon
    python ghost.py recall <topic>         Print a topic file
    python ghost.py inject <text>          Add an observation directly to transcript
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from llm_client import LLMClient
from memory import Memory
from dream import DreamEngine

# ── Logging ───────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ghost")


# ── Config ────────────────────────────────────────────────

def load_config(path: str = "config.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        logger.error("Config file not found: %s", path)
        logger.error("Copy config.yaml.example to config.yaml and fill in your API key.")
        sys.exit(1)
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── CHAT SYSTEM PROMPT ───────────────────────────────────

CHAT_SYSTEM_TEMPLATE = """\
You are **Ghost**, a persistent AI assistant with long-term memory.

Your memory is loaded below.  Use it to maintain continuity across sessions.
When you learn new facts about the user, their projects, or decisions, note them
clearly so the dream engine can consolidate them later.

If you're unsure about something in memory, say so — don't fabricate.

{memory_context}

Current time: {now}
"""


# ── Commands ──────────────────────────────────────────────

def cmd_init(config: dict):
    """Initialize the .ghost/ state directory."""
    state_dir = Path(config.get("state_dir", ".ghost"))
    if state_dir.exists():
        print(f"State directory already exists: {state_dir}")
        print("  MEMORY.md:       ", (state_dir / "MEMORY.md").exists())
        print("  transcript.jsonl: ", (state_dir / "transcript.jsonl").exists())
        print("  topics/:          ", (state_dir / "topics").exists())
        return

    mem = Memory(state_dir)
    mem.transcript.append(
        role="system",
        content="Ghost Agent initialized.",
        event="init",
    )
    print(f"✓ Initialized state directory: {state_dir.resolve()}")
    print(f"  MEMORY.md, topics/, transcript.jsonl created.")


def cmd_status(config: dict):
    """Print memory system status."""
    mem = Memory(Path(config.get("state_dir", ".ghost")))
    s = mem.status()

    daemon_file = Path(config.get("state_dir", ".ghost")) / "daemon.json"
    daemon_state = None
    if daemon_file.exists():
        try:
            daemon_state = json.loads(daemon_file.read_text())
        except Exception:
            pass

    print("╔══════════════════════════════════════╗")
    print("║         GHOST AGENT STATUS           ║")
    print("╠══════════════════════════════════════╣")
    print(f"║ Topics:             {s['topic_count']:>14} ║")
    for t in s["topics"]:
        print(f"║   - {t:<32} ║")
    print(f"║ Transcript entries: {s['transcript_entries']:>14} ║")
    print(f"║ Transcript size:    {s['transcript_bytes']:>11} B  ║")
    print(f"║ Dream cursor:       {s['dream_cursor']:>14} ║")
    print(f"║ Undreamed entries:  {s['undreamed_entries']:>14} ║")
    if daemon_state:
        last_tick = daemon_state.get("last_tick", "never")
        ticks = daemon_state.get("tick_count", 0)
        dreams = daemon_state.get("dream_count", 0)
        print(f"║ Daemon last tick:   {str(last_tick)[:14]:>14} ║")
        print(f"║ Daemon ticks:       {ticks:>14} ║")
        print(f"║ Daemon dreams:      {dreams:>14} ║")
    else:
        print(f"║ Daemon:             {'not running':>14} ║")
    print("╚══════════════════════════════════════╝")


def cmd_recall(config: dict, topic: str):
    """Print a topic file."""
    mem = Memory(Path(config.get("state_dir", ".ghost")))
    content = mem.topics.read(topic)
    if content:
        print(f"=== {topic} ===\n")
        print(content)
    else:
        print(f"Topic not found: {topic}")
        print(f"Available: {', '.join(mem.topics.list_topics()) or '(none)'}")


def cmd_inject(config: dict, text: str):
    """Inject a raw observation into the transcript."""
    mem = Memory(Path(config.get("state_dir", ".ghost")))
    mem.transcript.append(role="user", content=text, event="manual_inject")
    print(f"✓ Injected into transcript ({len(text)} chars)")


def cmd_dream(config: dict):
    """Run one dream consolidation cycle."""
    mem = Memory(Path(config.get("state_dir", ".ghost")))
    llm = LLMClient(config["llm"])
    workspace = Path(config["workspace_root"]) if config.get("workspace_root") else None
    engine = DreamEngine(mem, llm, workspace)

    print("Running dream cycle…")
    result = engine.dream()
    print(f"Result: {json.dumps(result, indent=2)}")


def cmd_compact(config: dict):
    """Compact old transcript entries."""
    mem = Memory(Path(config.get("state_dir", ".ghost")))
    llm = LLMClient(config["llm"])
    workspace = Path(config["workspace_root"]) if config.get("workspace_root") else None
    engine = DreamEngine(mem, llm, workspace)

    threshold = config.get("dream", {}).get("compact_threshold", 200)
    print(f"Running compaction (keep recent {threshold // 2})…")
    result = engine.compact(keep_recent=threshold // 2)
    print(f"Result: {json.dumps(result, indent=2)}")


def cmd_chat(config: dict):
    """Interactive chat loop with persistent memory context."""
    mem = Memory(Path(config.get("state_dir", ".ghost")))
    llm = LLMClient(config["llm"])
    workspace = Path(config["workspace_root"]) if config.get("workspace_root") else None
    engine = DreamEngine(mem, llm, workspace)

    session_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    messages = []  # Running conversation for this session

    print("╔══════════════════════════════════════╗")
    print("║          GHOST AGENT CHAT            ║")
    print("║  Type /quit to exit                  ║")
    print("║  Type /dream to trigger dream cycle  ║")
    print("║  Type /status for memory stats       ║")
    print("║  Type /recall <topic> to read a topic║")
    print("╚══════════════════════════════════════╝")
    print()

    while True:
        try:
            user_input = input("\033[36myou>\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue

        # Slash commands
        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()

            if cmd == "/quit":
                print("Goodbye.")
                break
            elif cmd == "/dream":
                result = engine.dream()
                print(f"Dream result: {result.get('dream_log', result)}")
                continue
            elif cmd == "/status":
                cmd_status(config)
                continue
            elif cmd == "/recall":
                topic = parts[1].strip() if len(parts) > 1 else ""
                if topic:
                    cmd_recall(config, topic)
                else:
                    topics = mem.topics.list_topics()
                    print(f"Topics: {', '.join(topics) or '(none)'}")
                continue
            elif cmd == "/compact":
                result = engine.compact()
                print(f"Compact result: {result}")
                continue
            elif cmd == "/context":
                print(mem.build_context())
                continue
            else:
                print(f"Unknown command: {cmd}")
                continue

        # Log user message to transcript
        mem.transcript.append(role="user", content=user_input, session=session_id)

        # Build system prompt with full memory context
        memory_context = mem.build_context()
        system_prompt = CHAT_SYSTEM_TEMPLATE.format(
            memory_context=memory_context,
            now=datetime.now(timezone.utc).isoformat(),
        )

        # Add to running messages
        messages.append({"role": "user", "content": user_input})

        # Keep conversation window reasonable (last 20 turns)
        window = messages[-40:]

        try:
            response = llm.chat(messages=window, system=system_prompt)
        except Exception as exc:
            print(f"\033[31mLLM error: {exc}\033[0m")
            messages.pop()  # Remove the failed user message from history
            continue

        messages.append({"role": "assistant", "content": response})

        # Log assistant response to transcript
        mem.transcript.append(role="assistant", content=response, session=session_id)

        print(f"\n\033[33mghost>\033[0m {response}\n")

        # Auto-dream check (non-blocking suggestion)
        min_entries = config.get("dream", {}).get("min_new_entries", 5)
        if engine.should_dream(min_entries):
            undreamed = mem.status()["undreamed_entries"]
            print(f"\033[90m  [{undreamed} undreamed entries — type /dream to consolidate]\033[0m\n")


# ── KAIROS DAEMON ─────────────────────────────────────────

class KairosDaemon:
    """Always-on daemon with tick loop, autoDream, and crash-resume."""

    def __init__(self, config: dict):
        self.config = config
        self.state_dir = Path(config.get("state_dir", ".ghost"))
        self.mem = Memory(self.state_dir)
        self.llm = LLMClient(config["llm"])
        workspace = Path(config["workspace_root"]) if config.get("workspace_root") else None
        self.dream_engine = DreamEngine(self.mem, self.llm, workspace)

        self.checkpoint_path = self.state_dir / "daemon.json"
        self.running = True

        # Config
        dc = config.get("daemon", {})
        self.tick_interval = dc.get("tick_interval_seconds", 60)
        self.watch_paths = [Path(p) for p in dc.get("watch_paths", [])]

        drc = config.get("dream", {})
        self.dream_min_entries = drc.get("min_new_entries", 5)
        self.dream_interval = drc.get("auto_interval_minutes", 30) * 60
        self.compact_threshold = drc.get("compact_threshold", 200)

        # State
        self.state = self._load_checkpoint()

    def _load_checkpoint(self) -> dict:
        if self.checkpoint_path.exists():
            try:
                s = json.loads(self.checkpoint_path.read_text())
                logger.info("Resuming from checkpoint: tick %d, %d dreams",
                           s.get("tick_count", 0), s.get("dream_count", 0))
                return s
            except Exception:
                pass
        return {
            "started": datetime.now(timezone.utc).isoformat(),
            "last_tick": None,
            "tick_count": 0,
            "dream_count": 0,
            "last_dream": None,
            "last_compact": None,
            "watch_hashes": {},
        }

    def _save_checkpoint(self):
        self.checkpoint_path.write_text(json.dumps(self.state, indent=2))

    def _file_mtime(self, path: Path) -> float:
        try:
            return path.stat().st_mtime if path.exists() else 0.0
        except Exception:
            return 0.0

    def run(self):
        """Main tick loop — runs until SIGINT/SIGTERM."""
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        logger.info("KAIROS daemon starting (tick every %ds, dream every %ds)",
                    self.tick_interval, self.dream_interval)

        self.mem.transcript.append(
            role="system",
            content=f"KAIROS daemon started (tick={self.tick_interval}s, dream={self.dream_interval}s)",
            event="daemon_start",
        )

        while self.running:
            try:
                self._tick()
            except Exception as exc:
                logger.error("Tick error: %s", exc, exc_info=True)
                self.mem.transcript.append(
                    role="system",
                    content=f"[KAIROS] Tick error: {exc}",
                    event="error",
                )

            self._save_checkpoint()

            # Sleep in small increments so we can catch signals
            for _ in range(self.tick_interval):
                if not self.running:
                    break
                time.sleep(1)

        # Clean shutdown
        self.mem.transcript.append(
            role="system",
            content=f"KAIROS daemon stopped after {self.state['tick_count']} ticks",
            event="daemon_stop",
        )
        self._save_checkpoint()
        logger.info("KAIROS daemon stopped.")

    def _tick(self):
        """One daemon tick — check watches, maybe dream, maybe compact."""
        now = datetime.now(timezone.utc)
        self.state["tick_count"] += 1
        self.state["last_tick"] = now.isoformat()

        logger.debug("Tick #%d", self.state["tick_count"])

        # ── 1. Check watched files for changes ───────────
        for wp in self.watch_paths:
            key = str(wp)
            current_mtime = self._file_mtime(wp)
            prev_mtime = self.state.get("watch_hashes", {}).get(key, 0.0)

            if current_mtime > prev_mtime and prev_mtime > 0:
                logger.info("Watch triggered: %s changed", wp)
                self.mem.transcript.append(
                    role="system",
                    content=f"[KAIROS] Watched file changed: {wp}",
                    event="file_changed",
                )
                # Could trigger further actions here
                # e.g., re-read registry, notify user, etc.

            self.state.setdefault("watch_hashes", {})[key] = current_mtime

        # ── 2. autoDream if enough time has passed ────────
        last_dream_ts = self.state.get("last_dream")
        seconds_since_dream = float("inf")
        if last_dream_ts:
            try:
                last_dt = datetime.fromisoformat(last_dream_ts)
                seconds_since_dream = (now - last_dt).total_seconds()
            except Exception:
                pass

        if seconds_since_dream >= self.dream_interval:
            if self.dream_engine.should_dream(self.dream_min_entries):
                logger.info("autoDream triggered (%.0f seconds since last dream)",
                           seconds_since_dream)
                result = self.dream_engine.dream()
                self.state["dream_count"] += 1
                self.state["last_dream"] = now.isoformat()
                logger.info("autoDream result: %s", result.get("dream_log", result))
            else:
                logger.debug("autoDream: not enough new entries")

        # ── 3. Auto-compact if transcript is large ────────
        entry_count = self.mem.transcript.entry_count()
        if entry_count > self.compact_threshold:
            last_compact = self.state.get("last_compact")
            should_compact = True
            if last_compact:
                try:
                    last_c = datetime.fromisoformat(last_compact)
                    # Only compact once per 6 hours
                    should_compact = (now - last_c).total_seconds() > 21600
                except Exception:
                    pass

            if should_compact:
                logger.info("Auto-compact triggered (%d entries)", entry_count)
                result = self.dream_engine.compact(keep_recent=self.compact_threshold // 2)
                self.state["last_compact"] = now.isoformat()
                logger.info("Compact result: %s", result)

        # ── 4. Heartbeat log (every 10 ticks) ────────────
        if self.state["tick_count"] % 10 == 0:
            status = self.mem.status()
            logger.info(
                "Heartbeat: tick=%d dreams=%d topics=%d undreamed=%d transcript=%d",
                self.state["tick_count"],
                self.state["dream_count"],
                status["topic_count"],
                status["undreamed_entries"],
                status["transcript_entries"],
            )

    def _shutdown(self, signum, frame):
        logger.info("Shutdown signal received (%s)", signum)
        self.running = False


def cmd_daemon(config: dict):
    """Start the KAIROS always-on daemon."""
    print("╔══════════════════════════════════════╗")
    print("║       KAIROS DAEMON STARTING         ║")
    print("║  Press Ctrl+C to stop                ║")
    print("╚══════════════════════════════════════╝")

    daemon = KairosDaemon(config)
    daemon.run()


# ── Entry point ───────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Ghost Agent — local persistent memory + dream + daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Initialize .ghost/ state directory")
    sub.add_parser("chat", help="Interactive chat with persistent memory")
    sub.add_parser("dream", help="Run one dream consolidation cycle")
    sub.add_parser("compact", help="Compact old transcript entries")
    sub.add_parser("status", help="Show memory status")
    sub.add_parser("daemon", help="Start KAIROS always-on daemon")

    recall_p = sub.add_parser("recall", help="Print a topic file")
    recall_p.add_argument("topic", help="Topic slug name")

    inject_p = sub.add_parser("inject", help="Inject text into transcript")
    inject_p.add_argument("text", nargs="+", help="Text to inject")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    config = load_config(args.config)

    dispatch = {
        "init": lambda: cmd_init(config),
        "chat": lambda: cmd_chat(config),
        "dream": lambda: cmd_dream(config),
        "compact": lambda: cmd_compact(config),
        "status": lambda: cmd_status(config),
        "daemon": lambda: cmd_daemon(config),
        "recall": lambda: cmd_recall(config, args.topic),
        "inject": lambda: cmd_inject(config, " ".join(args.text)),
    }

    dispatch[args.command]()


if __name__ == "__main__":
    main()