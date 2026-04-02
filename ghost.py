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
    python ghost.py ping                   Test LLM connectivity and pacing
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
from dotenv import load_dotenv

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
    load_dotenv()  # Load .env if it exists
    p = Path(path)
    if not p.exists():
        logger.error("Config file not found: %s", path)
        logger.error("Copy config.yaml.example to config.yaml and fill in your API key.")
        sys.exit(1)
    with open(p, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Resolve `${VAR}` placeholders in config values
    def resolve_env_vars(data):
        if isinstance(data, dict):
            return {k: resolve_env_vars(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [resolve_env_vars(i) for i in data]
        elif isinstance(data, str) and data.startswith("${") and data.endswith("}"):
            var_name = data[2:-1]
            return os.getenv(var_name, data)
        return data

    config = resolve_env_vars(config)

    # Environment variable overrides
    def apply_overrides(cfg_key, env_prefix):
        if os.getenv(f"{env_prefix}_API_KEY"):
            config.setdefault(cfg_key, {})["api_key"] = os.getenv(f"{env_prefix}_API_KEY")
        if os.getenv(f"{env_prefix}_BASE_URL"):
            config.setdefault(cfg_key, {})["base_url"] = os.getenv(f"{env_prefix}_BASE_URL")
        if os.getenv(f"{env_prefix}_PROVIDER"):
            config.setdefault(cfg_key, {})["provider"] = os.getenv(f"{env_prefix}_PROVIDER")
        if os.getenv(f"{env_prefix}_MODEL"):
            config.setdefault(cfg_key, {})["model"] = os.getenv(f"{env_prefix}_MODEL")

    apply_overrides("llm", "GHOST_LLM")
    apply_overrides("dream_llm", "GHOST_DREAM_LLM")

    return config


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


# ── UI Utilities ──────────────────────────────────────────

def _print_box(rows: list, title: str = None, width: int = 46):
    """Draw a standardized ASCII box with border and title alignment."""
    inner_w = width - 4
    header = "╔" + "═" * (width - 2) + "╗"
    footer = "╚" + "═" * (width - 2) + "╝"
    sep = "╠" + "═" * (width - 2) + "╣"

    print(header)
    if title:
        print(f"║ {title.center(width - 4)} ║")
        print(sep)

    for r in rows:
        if r == "---":
            print(sep)
            continue
        # Truncate content that exceeds width
        content = str(r)
        if len(content) > inner_w:
            content = content[:inner_w - 3] + "..."
        print(f"║ {content.ljust(inner_w)} ║")

    print(footer)


# ── Commands ──────────────────────────────────────────────

def cmd_init(config: dict):
    """Initialize the .ghost/ state directory."""
    state_dir = Path(config.get("state_dir", ".ghost"))
    if state_dir.exists():
        rows = [
            f"MEMORY.md:       {str((state_dir / 'MEMORY.md').exists()):>14}",
            f"transcript.jsonl: {str((state_dir / 'transcript.jsonl').exists()):>14}",
            f"topics/:          {str((state_dir / 'topics').exists()):>14}"
        ]
        _print_box(rows, title=f"STATE ALREADY EXISTS: {state_dir.name}")
        return

    mem = Memory(state_dir)
    mem.transcript.append(
        role="system",
        content="Ghost Agent initialized.",
        event="init",
    )
    _print_box([
        f"Path: {state_dir.resolve()}",
        "---",
        "✓ MEMORY.md created",
        "✓ transcript.jsonl created",
        "✓ topics/ directory ready",
        "✓ GHOST_SPEC.md written"
    ], title="INITIALIZED GHOST STATE")


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

    rows = [
        f"Topics:             {s['topic_count']:>14}",
        "---"
    ]
    for t in s["topics"]:
        rows.append(f"  - {t}")
    
    rows.extend([
        "---",
        f"Transcript entries: {s['transcript_entries']:>14}",
        f"Transcript size:    {s['transcript_bytes']:>11} B",
        f"Dream cursor:       {s['dream_cursor']:>14}",
        f"Undreamed entries:  {s['undreamed_entries']:>14}",
        "---"
    ])

    if daemon_state:
        last_tick = daemon_state.get("last_tick", "never")
        ticks = daemon_state.get("tick_count", 0)
        dreams = daemon_state.get("dream_count", 0)
        rows.extend([
            f"Daemon last tick:   {str(last_tick)[:14]:>14}",
            f"Daemon ticks:       {ticks:>14}",
            f"Daemon dreams:      {dreams:>14}"
        ])
    else:
        rows.append(f"Daemon:             {'not running':>14}")

    _print_box(rows, title="GHOST AGENT STATUS")


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


def cmd_inject(config: dict, text: str = "", file_path: str = None):
    """Inject a raw observation into the transcript."""
    mem = Memory(Path(config.get("state_dir", ".ghost")))

    if file_path:
        p = Path(file_path)
        if not p.exists():
            print(f"\033[31m✗ File not found: {p.resolve()}\033[0m")
            return
        content = p.read_text(encoding="utf-8")
        source = p.name
        print(f"Reading {p.resolve()} ({len(content)} chars)…")
    elif text:
        content = text
        source = "manual"
    else:
        print("Nothing to inject. Use: ghost inject 'some text' or ghost inject -f path/to/file")
        return

    mem.transcript.append(
        role="user",
        content=content,
        event="inject",
        source=source,
        confidence="verified",  # User-provided data is trusted
    )
    print(f"✓ Injected into transcript ({len(content)} chars, source: {source})")


def cmd_dream(config: dict):
    """Run one dream consolidation cycle."""
    mem = Memory(Path(config.get("state_dir", ".ghost")))
    llm = LLMClient(config["llm"])
    
    # Support optional dedicated dream LLM
    dream_llm = None
    if "dream_llm" in config:
        dream_llm = LLMClient(config["dream_llm"])
    
    workspace = Path(config["workspace_root"]) if config.get("workspace_root") else None
    engine = DreamEngine(mem, llm, workspace, dream_llm=dream_llm)

    print("Running 4-phase dream cycle…")
    result = engine.dream()
    
    status = result.get("status", "?")
    if status == "ok":
        print(f"\n\033[32m✓ Dream #{result['cycle']} complete\033[0m")
        print(f"  {result.get('dream_log', '')}")
        phases = result.get("phases", {})
        for name, summary in phases.items():
            print(f"  Phase [{name}]: {summary}")
    elif status == "skipped":
        print(f"\033[33m⊘ Skipped: {result.get('reason', '?')}\033[0m")
    else:
        print(f"\033[31m✗ Error: {result.get('error', '?')}\033[0m")


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


def cmd_ping(config: dict):
    """Test LLM connectivity and pacing for both Chat and Dream models."""
    
    def test_client(label, cfg):
        if not cfg:
            return
        
        llm = LLMClient(cfg)
        pacing = cfg.get("min_interval", 0)

        _print_box([
            f"Provider:  {cfg.get('provider', 'openai')}",
            f"Model:     {cfg.get('model', 'unknown')}",
            f"Base URL:  {cfg.get('base_url', 'default')}",
            f"Pacing:    {pacing}s",
            "---",
            "Testing Connectivity...",
        ], title=f"LLM PING TEST: {label}")

        # Call 1: Simple JSON test
        start_1 = time.time()
        try:
            resp_1 = llm.chat(
                messages=[{"role": "user", "content": "Respond with JSON: {\"status\": \"ok\"}"}],
                system="You are a connectivity tester. Always respond in valid JSON."
            )
            dur_1 = time.time() - start_1
            print(f"  [✓] Call 1 success ({dur_1:.2f}s)")
            print(f"      Response: {resp_1}")
        except Exception as e:
            print(f"  [✗] Call 1 failed: {e}")
            return

        # Call 2: Pacing test
        if pacing > 0:
            print(f"  Testing pacing (expecting ~{pacing}s delay)...")
            start_2 = time.time()
            try:
                resp_2 = llm.chat(
                    messages=[{"role": "user", "content": "Respond with JSON: {\"status\": \"pong\"}"}],
                    system="You are a connectivity tester."
                )
                dur_2 = time.time() - start_2
                print(f"  [✓] Call 2 success ({dur_2:.2f}s)")
                if dur_2 >= pacing:
                    print(f"      Pacing verified: {dur_2:.2f}s >= {pacing}s")
                else:
                    print(f"      Pacing WARNING: {dur_2:.2f}s < {pacing}s")
            except Exception as e:
                print(f"  [✗] Call 2 failed: {e}")
        print()

    # Test main Chat LLM
    test_client("CHAT", config.get("llm"))
    
    # Test optional Dream LLM
    if "dream_llm" in config:
        test_client("DREAM", config.get("dream_llm"))
    else:
        print("Note: Dedicated dream_llm not configured. Consolidation will use Chat LLM.\n")


def cmd_chat(config: dict):
    """Interactive chat loop with persistent memory context."""
    mem = Memory(Path(config.get("state_dir", ".ghost")))
    llm = LLMClient(config["llm"])

    # Support optional dedicated dream LLM
    dream_llm = None
    if "dream_llm" in config:
        dream_llm = LLMClient(config["dream_llm"])

    workspace = Path(config["workspace_root"]) if config.get("workspace_root") else None
    engine = DreamEngine(mem, llm, workspace, dream_llm=dream_llm)

    session_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    messages = []  # Running conversation for this session

    _print_box([
        "Type /quit to exit",
        "Type /dream to trigger dream cycle",
        "Type /status for memory stats",
        "Type /recall <topic> to read topic",
        "Type /verify <claim> to test logic",
        "Type /add <text> to inject fact"
    ], title="GHOST AGENT CHAT")
    print()

    while True:
        try:
            user_input = input("\033[36myou>\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue

        # Shell command interception
        SHELL_PATTERNS = [
            "python ghost.py", "python ghost", "./ghost.py", "ghost.py",
            "git ", "ls ", "dir ", "cd ", "mkdir ", "rm ", "cp ", "mv ", "cat "
        ]
        if any(user_input.lower().startswith(p) for p in SHELL_PATTERNS):
            print("\033[93m⚠️ Intercepted shell-like command.\033[0m")
            print("  This chat loop is for interaction, not CLI execution.")
            print("  To run Ghost Agent commands, use the actual terminal.")
            print("  This prevents the LLM from hallucinating command execution.\n")
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
            elif cmd == "/verify":
                claim = parts[1].strip() if len(parts) > 1 else ""
                if not claim:
                    print("Usage: /verify <claim string>")
                    continue
                print(f"Verifying claim: {claim}...")
                v_results = engine._verify([{"claim": claim, "check_type": "none"}])
                # Note: This is a basic check. Actual verification uses types.
                # Let's try to be smarter and guess check types.
                checks = []
                if "registry" in claim.lower() or "project" in claim.lower():
                    checks.append({"claim": claim, "check_type": "registry"})
                if "/" in claim or "\\" in claim or "." in claim:
                    checks.append({"claim": claim, "check_type": "file_exists", "check_path": claim.split()[-1]})
                
                if not checks:
                    checks.append({"claim": claim, "check_type": "none"})
                
                final_v = engine._verify(checks)
                for res in final_v:
                    status = "✓" if res.get("verified") else "✗"
                    print(f"  [{status}] {res.get('check_type')}: {res.get('claim')} (conf: {res.get('confidence')})")
                continue
            elif cmd == "/add":
                text = parts[1].strip() if len(parts) > 1 else ""
                if not text:
                    print("Usage: /add <fact text>")
                    continue
                mem.transcript.append(role="user", content=text, event="manual_add", confidence="high")
                print(f"✓ Observation added with HIGH confidence.")
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
        mem.transcript.append(role="assistant", content=response, session=session_id, confidence="unverified")

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
        
        # Support optional dedicated dream LLM
        dream_llm = None
        if "dream_llm" in config:
            dream_llm = LLMClient(config["dream_llm"])

        workspace = Path(config["workspace_root"]) if config.get("workspace_root") else None
        self.dream_engine = DreamEngine(self.mem, self.llm, workspace, dream_llm=dream_llm)

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

        # ── 1.1 Check linked sources for changes ────────
        sources_file = self.state_dir / "sources.json"
        if sources_file.exists():
            try:
                sources = json.loads(sources_file.read_text())
                changed_sources = False
                for _key, meta in sources.items():
                    path = Path(meta["path"])
                    if path.exists():
                        current = path.stat().st_mtime
                        if current > meta.get("last_seen_mtime", 0):
                            logger.info("Source changed: %s", path.name)
                            self.mem.transcript.append(
                                role="system",
                                content=f"[SOURCE CHANGED] {path.name} modified",
                                event="source_changed",
                                source=str(path),
                            )
                            # Update mtime here to prevent multiple logs before dream
                            meta["last_seen_mtime"] = current
                            changed_sources = True
                
                if changed_sources:
                    sources_file.write_text(json.dumps(sources, indent=2))
            except Exception:
                pass

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


def cmd_link(config: dict, path: str):
    """Register a file as a persistent memory source."""
    mem = Memory(Path(config.get("state_dir", ".ghost")))
    target = Path(path).resolve()

    if not target.exists():
        print(f"\033[31m✗ File not found: {target}\033[0m")
        return

    sources_file = mem.base_dir / "sources.json"
    sources = {}
    if sources_file.exists():
        try:
            sources = json.loads(sources_file.read_text())
        except Exception:
            pass

    key = str(target)
    sources[key] = {
        "path": str(target),
        "name": target.stem,
        "type": target.suffix.lstrip("."),
        "linked": datetime.now(timezone.utc).isoformat(),
        "last_seen_mtime": 0,
        "last_read_mtime": 0,
    }

    sources_file.write_text(json.dumps(sources, indent=2))

    # Log the linking, not the content
    mem.transcript.append(
        role="system",
        content=f"[SOURCE LINKED] {target.name} ({target.stat().st_size} bytes) at {target}",
        event="source_link",
        source=str(target),
        confidence="verified",
    )

    print(f"✓ Linked: {target.name} ({target.stat().st_size:,} bytes)")
    print(f"  Dream engine will read this file directly during Gather phase.")
    print(f"  Changes to the file will be detected automatically.")




# ── Entry point ───────────────────────────────────────────

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

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
    sub.add_parser("ping", help="Test LLM connectivity and pacing")

    link_p = sub.add_parser("link", help="Link a file as persistent memory source")
    link_p.add_argument("path", help="Path to file")

    recall_p = sub.add_parser("recall", help="Print a topic file")
    recall_p.add_argument("topic", help="Topic slug name")

    inject_p = sub.add_parser("inject", help="Inject text into transcript")
    inject_p.add_argument("text", nargs="*", default=[], help="Text to inject")
    inject_p.add_argument(
        "-f", "--file",
        type=str,
        default=None,
        help="Path to a file to inject (reads entire contents)",
    )

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
        "inject": lambda: cmd_inject(
            config,
            text=" ".join(args.text) if args.text else "",
            file_path=args.file,
        ),
        "ping": lambda: cmd_ping(config),
        "link": lambda: cmd_link(config, args.path),
    }

    dispatch[args.command]()


if __name__ == "__main__":
    main()