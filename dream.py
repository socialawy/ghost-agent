"""autoDream v1.1 — 4-phase memory consolidation.

Phase 1: Orient  — What changed? Diff new entries against existing knowledge.
Phase 2: Gather  — Pull only the topic files that are relevant to the changes.
Phase 3: Consolidate — Merge, resolve contradictions, update topics.
Phase 4: Prune   — Demote stale claims, remove redundancy, compact if needed.

Each phase is a separate, cheap LLM call with a tight prompt.
"""

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from llm_client import LLMClient, RateLimitError
from memory import Memory

logger = logging.getLogger("ghost.dream")


# ═══════════════════════════════════════════════════════════
#  Phase system prompts
# ═══════════════════════════════════════════════════════════

ORIENT_SYSTEM = """\
You are a memory ORIENT agent. Your job is to read new interaction entries and
produce a structured diff against the current memory index.

OUTPUT FORMAT — respond with **only** valid JSON (no markdown fences):
{
  "deltas": [
    {
      "type": "new_fact" | "updated_fact" | "contradiction" | "action_item" | "preference",
      "summary": "One-line description of what changed",
      "confidence": "high" | "medium" | "low",
      "relevant_topics": ["existing-topic-slug"],
      "source_role": "user" | "assistant" | "system"
    }
  ],
  "topics_to_load": ["existing-topic-slug-that-needs-updating"],
  "topics_to_create": ["new-topic-slug-only-if-truly-new-domain"],
  "orient_summary": "≤1 sentence: what happened since last dream"
}

RULES:
1. Only report ACTUAL changes — not things already in the memory index.
2. User statements and injected files (event:inject) are HIGH confidence.
3. Assistant responses (confidence:unverified) are LOW confidence.
4. Be CONSERVATIVE with topics_to_create. A new topic is warranted only when
   the information doesn't fit ANY existing topic. Typical threshold: ≤3 topics
   for a workspace with <20 knowledge items.
5. Group related deltas under the SAME relevant_topics entry.
   "User identity + workspace location + project count" is ONE delta about the user,
   not three separate deltas.
6. If nothing meaningful changed, return empty deltas.

VERBATIM PRESERVATION:
7. The `summary` field MUST contain exact numbers, names, versions, and paths.
8. NEVER generalize. "Updated project count" is BAD. "Updated project count to 107+" is GOOD.
9. If an injected file contains structured data (e.g. CSV), the summary should list the key-value pairs or totals.
"""

GATHER_SYSTEM = """\
You are a memory GATHER agent. Given an orient report and the full topic list,
decide exactly which topic file contents are needed for consolidation.

OUTPUT FORMAT — respond with **only** valid JSON:
{
  "load": ["topic-slug-1", "topic-slug-2"],
  "skip": ["topic-slug-not-relevant"],
  "reasoning": "≤2 sentences explaining the selection"
}

RULES:
1. Load the MINIMUM set of topics needed to process the deltas.
2. If a delta references a topic by name, load it.
3. If a delta could contradict an existing topic, load it.
4. If no topics are relevant, return empty load array.
"""

CONSOLIDATE_SYSTEM = """\
You are a memory CONSOLIDATE agent. You receive:
- A list of deltas (summaries of changes detected)
- The raw source entries (the original transcript logic)
- The current content of relevant topic files
- The current memory index

Your job: produce updated topic files that incorporate the new information with 100% fidelity.

OUTPUT FORMAT — respond with **only** valid JSON:
{
  "topic_updates": [
    {
      "topic": "slug-name",
      "action": "create" | "update",
      "content": "Full markdown content for the topic file."
    }
  ],
  "index_graph": {
    "nodes": [
      {"id": "topic-slug", "label": "Human-readable name", "type": "project|system|person|concept"}
    ],
    "edges": [
      {"from": "topic-a", "to": "topic-b", "relation": "verb phrase describing relationship"}
    ]
  },
  "active_context": "One-line summary of current user focus",
  "pending_observations": ["Things that don't fit a topic yet"],
  "verifications": [
    {
      "claim": "Human-readable claim",
      "check_type": "file_exists" | "file_contains" | "registry" | "none",
      "check_path": "path or null"
    }
  ],
  "consolidate_log": "≤2 sentence summary of changes made"
}

CRITICAL RULES:

TOPIC QUALITY:
1. Each topic file MUST be at least 200 characters.
2. Maximum 7 topics total. Prefer fewer, richer topics.
3. Group related information into single topics.
4. When updating a topic, output its COMPLETE new content.

DATA PRESERVATION (most important):
5. NEVER generalize specific data. If the input says "107 registered projects",
   the output MUST say "107 registered projects" — NOT "multiple projects".
6. ALWAYS preserve: numbers, names, versions, dates, tool names, status values.
7. Structured data (JSON fields, CSV columns, config values) must be extracted
   into bullet points or tables, keeping the actual values.
8. A topic file is a REFERENCE DOCUMENT that someone reads to recall exact facts.
   Write it like a wiki page with specifics, not like a press release with vague claims.

EXAMPLE — BAD:
  "The user works on several active projects with various tools."

EXAMPLE — GOOD:
  "## Registry: 107 registered, ~110 on disk
   - Active: 5 | Idle: 50 | Frozen: 27 | Archived: 6
   ## Hot Projects (March 2026)
   - GRID: 865+ tests, Gemini AI features, export suite
   - parallaxin: Astro site, Arabic i18n, GitHub Pages
   - tiny-museum: Kids art app (Mira's Museum), Supabase
   - Audio-Formation: Chapter01_Scene01, Session 8 bugfixes"

GRAPH QUALITY:
9. Every node MUST correspond to a topic file that exists.
10. Edge relations must be SPECIFIC verbs — not just "contains".
11. If two things aren't meaningfully related, don't force an edge.

GENERAL:
12. Never fabricate — only consolidate what the deltas actually say.
13. Prefer updating existing topics over creating new ones.
"""

PRUNE_SYSTEM = """\
You are a memory PRUNE agent. You review the current memory state after
consolidation and clean it up.

OUTPUT FORMAT — respond with **only** valid JSON:
{
  "demotions": [
    {"topic": "slug", "claim": "what to demote", "reason": "why"}
  ],
  "removals": [
    {"topic": "slug", "reason": "why this topic should be deleted"}
  ],
  "stale_observations": ["pending observations to remove from index"],
  "prune_log": "≤2 sentence summary"
}

RULES:
1. Demote claims that have confidence:low and no corroborating evidence.
2. Remove topics that are empty, duplicated, or superseded.
3. Remove pending observations that have been incorporated into topics.
4. If nothing needs pruning, return empty arrays.
5. Be conservative — when in doubt, keep it.
6. FORBID: Never demote claims containing "not specified", "unknown", or model placeholders.
7. PERSISTENCE: If a fact was consolidated in the last 2 cycles, protect it from demotion unless explicitly contradicted.
"""

COMPACT_SYSTEM = """\
Summarize these interaction log entries into a concise summary (max 400 words).
Preserve: key decisions, facts, user preferences, project states, action items.
Discard: greetings, filler, verbose tool output, repeated info.
Output only the summary text, no preamble.
"""


# ═══════════════════════════════════════════════════════════
#  Dream Engine
# ═══════════════════════════════════════════════════════════

class DreamEngine:
    """4-phase memory consolidation engine."""

    def __init__(
        self,
        memory: Memory,
        llm: LLMClient,
        workspace_root: Optional[Path] = None,
        dream_llm: Optional[LLMClient] = None,
    ):
        self.memory = memory
        self.llm = dream_llm or llm
        self.workspace_root = workspace_root
        self._cycle = self._read_cycle_count()

    def _read_cycle_count(self) -> int:
        """Read current dream cycle from MEMORY.md."""
        try:
            content = self.memory.index.read()
            for line in content.splitlines():
                if line.startswith("Dream cycle:"):
                    return int(line.split(":")[1].strip())
        except Exception:
            pass
        return 0

    # ── LLM call helper ──────────────────────────────────

    def _call(self, system: str, user_content: str, json_mode: bool = True) -> dict | str:
        """Make an LLM call. Returns parsed JSON dict or raw string."""
        try:
            raw = self.llm.chat(
                messages=[{"role": "user", "content": user_content}],
                system=system,
                json_mode=json_mode,
            )
            if not json_mode:
                return raw

            # Attempt 1: direct parse
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass

            # Attempt 2: strip markdown fences
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                cleaned = "\n".join(lines).strip()
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError:
                    pass

            # Attempt 3: extract first JSON object
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(cleaned[start:end + 1])
                except json.JSONDecodeError:
                    pass

            logger.error("Could not parse JSON from response:\n%s", raw[:500])
            raise ValueError(f"Unparseable JSON: {raw[:200]}")

        except Exception as exc:
            if not isinstance(exc, RateLimitError):
                logger.error("LLM call failed: %s", exc)
            raise

    # ── Trigger conditions ────────────────────────────────

    def should_dream(self, min_entries: int = 5) -> bool:
        cursor = self.memory.get_dream_cursor()
        entries, _ = self.memory.transcript.read_since(cursor)
        return len(entries) >= min_entries

    def should_dream_session_aware(self, min_entries: int = 5, min_sessions: int = 2) -> bool:
        """Trigger dream only if enough entries AND enough distinct sessions."""
        cursor = self.memory.get_dream_cursor()
        entries, _ = self.memory.transcript.read_since(cursor)
        if len(entries) < min_entries:
            return False
        sessions = set()
        for e in entries:
            s = e.get("session", "default")
            if s != "default":
                sessions.add(s)
        # If we can't determine sessions (all "default"), fall back to entry count
        if not sessions:
            return True
        return len(sessions) >= min_sessions

    # ── Main dream cycle ──────────────────────────────────

    def dream(self) -> dict:
        """Run one 4-phase consolidation cycle with persistence."""
        # ── 1. Load or initialize state ───────────────────
        state = self.memory.get_dream_state()
        
        if state:
            logger.info("Resuming dream from saved state (cursor: %d)", state["cursor"])
            cursor = state["cursor"]
            new_cursor = state["new_cursor"]
            # We don't re-read from transcript if resuming, use the entries from state
            new_entries = state["entries"]
        else:
            cursor = self.memory.get_dream_cursor()
            new_entries, new_cursor = self.memory.transcript.read_since(cursor)
            if not new_entries:
                logger.info("Dream: nothing new.")
                return {"status": "skipped", "reason": "no new entries"}
            
            state = {
                "cursor": cursor,
                "new_cursor": new_cursor,
                "entries": new_entries,
                "phases": {},
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            self.memory.set_dream_state(state)

        logger.info("Dream: processing %d entries (cursor %d -> %d)", 
                    len(new_entries), cursor, new_cursor)

        try:
            # ── PHASE 1: ORIENT ──────────────────────────
            if "orient" not in state["phases"]:
                logger.info("Phase 1/4: Orient")
                orient = self._phase_orient(new_entries)
                state["phases"]["orient"] = orient
                self.memory.set_dream_state(state)
            else:
                orient = state["phases"]["orient"]

            deltas = orient.get("deltas", [])
            if not deltas:
                logger.info("Orient found no meaningful changes. Skipping.")
                self.memory.set_dream_cursor(new_cursor)
                self.memory.set_dream_state(None)
                return {"status": "skipped", "reason": "no deltas", "phases": state["phases"]}

            # ── PHASE 2: GATHER ──────────────────────────
            if "gather" not in state["phases"]:
                logger.info("Phase 2/4: Gather")
                gather = self._phase_gather(orient)
                state["phases"]["gather"] = gather
                self.memory.set_dream_state(state)
            else:
                gather = state["phases"]["gather"]

            # ── PHASE 3: CONSOLIDATE ─────────────────────
            if "consolidate" not in state["phases"]:
                logger.info("Phase 3/4: Consolidate")
                consolidate = self._phase_consolidate(orient, gather, new_entries)
                state["phases"]["consolidate"] = consolidate
                self.memory.set_dream_state(state)
            else:
                consolidate = state["phases"]["consolidate"]

            # ── PHASE 4: PRUNE ───────────────────────────
            if "prune" not in state["phases"]:
                logger.info("Phase 4/4: Prune")
                prune = self._phase_prune()
                state["phases"]["prune"] = prune
                self.memory.set_dream_state(state)
            else:
                prune = state["phases"]["prune"]

        except RateLimitError as exc:
            logger.warning("Dream paused due to rate limits: %s", exc)
            return {
                "status": "paused",
                "reason": "rate_limit",
                "retry_after": exc.retry_after_seconds,
                "phases_completed": list(state["phases"].keys())
            }
        except Exception as exc:
            logger.error("Dream failed at phase: %s", exc, exc_info=True)
            return {"status": "error", "error": str(exc), "phases": state["phases"]}

        # ── 3. Finalize ──────────────────────────────────
        self.memory.set_dream_cursor(new_cursor)
        self._cycle += 1

        dream_log = consolidate.get("consolidate_log", "cycle complete")
        self.memory.transcript.append(
            role="system",
            content=f"[DREAM #{self._cycle}] {dream_log}",
            event="dream",
        )

        # Clear state on success
        self.memory.set_dream_state(None)

        logger.info("Dream #%d complete: %s", self._cycle, dream_log)
        return {
            "status": "ok",
            "cycle": self._cycle,
            "dream_log": dream_log,
            "phases": {k: _summarize_phase(v) for k, v in state["phases"].items()},
        }

    # ── Phase 1: Orient ──────────────────────────────────

    def _phase_orient(self, entries: list) -> dict:
        current_index = self.memory.index.read()

        entry_text = self._format_entries(entries)
        prompt = (
            f"## Current Memory Index\n{current_index}\n\n"
            f"## Existing Topics\n{', '.join(self.memory.topics.list_topics()) or '(none)'}\n\n"
            f"## New Entries ({len(entries)})\n{entry_text}"
        )

        return self._call(ORIENT_SYSTEM, prompt)

    # ── Phase 2: Gather ──────────────────────────────────

    def _phase_gather(self, orient: dict) -> dict:
        all_topics = self.memory.topics.list_topics()

        if not all_topics:
            return {"load": [], "skip": [], "reasoning": "No topics exist yet."}

        topics_to_load = set(orient.get("topics_to_load", []))
        topics_to_create = set(orient.get("topics_to_create", []))

        # If orient already told us exactly what to load, trust it
        if topics_to_load and len(all_topics) <= 10:
            # Small topic count — just load what orient says, skip LLM call
            valid = [t for t in topics_to_load if t in all_topics]
            return {
                "load": valid,
                "skip": [t for t in all_topics if t not in valid],
                "reasoning": f"Orient specified {len(valid)} topics directly (small topic set, skipped Gather LLM call).",
            }

        # Larger topic set — let LLM decide
        deltas_summary = json.dumps(orient.get("deltas", []), indent=2)
        prompt = (
            f"## Orient Deltas\n{deltas_summary}\n\n"
            f"## Available Topics ({len(all_topics)})\n"
            + "\n".join(f"- {t}" for t in all_topics)
            + f"\n\n## Orient Suggested Load: {list(topics_to_load)}"
            + f"\n## Orient Suggested Create: {list(topics_to_create)}"
        )

        return self._call(GATHER_SYSTEM, prompt)

    def _load_sources(self) -> dict[str, str]:
        """Read all linked source files that have changed since last read."""
        sources_file = self.memory.base_dir / "sources.json"
        if not sources_file.exists():
            return {}

        try:
            sources = json.loads(sources_file.read_text())
        except Exception:
            return {}

        updated = {}
        changed = False

        for key, meta in sources.items():
            path = Path(meta["path"])
            if not path.exists():
                logger.warning("Linked source missing: %s", path)
                continue

            current_mtime = path.stat().st_mtime
            last_read_mtime = meta.get("last_read_mtime", 0)

            if current_mtime > last_read_mtime:
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                    # Truncate very large files — give dream the first 8K
                    if len(content) > 8000:
                        content = content[:8000] + f"\n\n…[truncated, full file: {len(content)} chars]"
                    updated[meta["name"]] = content
                    meta["last_read"] = datetime.now(timezone.utc).isoformat()
                    meta["last_read_mtime"] = current_mtime
                    changed = True
                    logger.info("Source updated: %s (%d chars)", meta["name"], len(content))
                except Exception as exc:
                    logger.warning("Failed to read source %s: %s", path, exc)

        if changed:
            sources_file.write_text(json.dumps(sources, indent=2))

        return updated

    # ── Phase 3: Consolidate ─────────────────────────────

    def _phase_consolidate(self, orient: dict, gather: dict, raw_entries: list) -> dict:
        # Load gathered topics
        gathered_content = {}
        for topic_name in gather.get("load", []):
            content = self.memory.topics.read(topic_name)
            if content:
                gathered_content[topic_name] = content

        # Load changed source files
        source_data = self._load_sources()

        deltas = json.dumps(orient.get("deltas", []), indent=2)
        current_index = self.memory.index.read()

        topic_section = ""
        if gathered_content:
            for name, content in gathered_content.items():
                topic_section += f"\n### {name}\n{content}\n"
        else:
            topic_section = "(no existing topics loaded)\n"

        # Source files section
        source_section = ""
        if source_data:
            source_section = "\n## Linked Source Files (authoritative — extract key data)\n"
            for name, content in source_data.items():
                source_section += f"\n### SOURCE: {name}\n{content}\n"

        raw_section = self._format_entries(raw_entries)

        prompt = (
            f"## Deltas (what changed — use as a GUIDE)\n{deltas}\n\n"
            f"## Raw Source Entries (extract EXACT data from these)\n{raw_section}\n\n"
            f"{source_section}\n"
            f"## Current Memory Index\n{current_index}\n\n"
            f"## Loaded Topic Files\n{topic_section}\n\n"
            f"## All Existing Topics\n{', '.join(self.memory.topics.list_topics()) or '(none)'}"
        )

        result = self._call(CONSOLIDATE_SYSTEM, prompt)

        # Verification gate
        verifications = result.get("verifications", [])
        if verifications:
            result["verifications"] = self._verify(verifications)

        self._apply_topics(result)
        self._rebuild_index(result)

        return result

    # ── Phase 4: Prune ───────────────────────────────────

    def _phase_prune(self) -> dict:
        current_index = self.memory.index.read()
        all_topics = {}
        for t in self.memory.topics.list_topics():
            content = self.memory.topics.read(t)
            if content:
                all_topics[t] = content[:500]  # First 500 chars is enough for pruning

        topic_previews = ""
        for name, preview in all_topics.items():
            topic_previews += f"\n### {name}\n{preview}\n"

        prompt = (
            f"## Current Memory Index\n{current_index}\n\n"
            f"## Topic Previews (first 500 chars)\n{topic_previews}"
        )

        result = self._call(PRUNE_SYSTEM, prompt)

        # Apply removals
        for removal in result.get("removals", []):
            topic = removal.get("topic", "")
            topic_path = self.memory.topics.directory / f"{topic}.md"
            if topic_path.exists():
                topic_path.unlink()
                logger.info("Pruned topic: %s — %s", topic, removal.get("reason", ""))

        # Apply demotions (rewrite topic with demotion note)
        for demotion in result.get("demotions", []):
            topic = demotion.get("topic", "")
            claim = demotion.get("claim", "")
            reason = demotion.get("reason", "")
            
            # Guard: Placeholder text
            if any(p in claim.lower() for p in ["not specified", "unknown", "placeholder"]):
                continue
                
            content = self.memory.topics.read(topic)
            if content:
                note = f"\n\n> ⚠️ DEMOTED: \"{claim}\" — {reason}\n"
                # Guard: Double appending or near-duplicate notes
                if note in content or f"DEMOTED: \"{claim}\"" in content:
                    continue
                self.memory.topics.write(topic, content + note)
                logger.info("Demoted claim in %s: %s", topic, claim)

        return result

    # ── Compaction (standalone, called by daemon) ─────────

    def compact(self, keep_recent: int = 100) -> dict:
        entries = self.memory.transcript.read_all()
        total = len(entries)

        if total <= keep_recent * 2:
            return {"status": "skipped", "reason": f"only {total} entries"}

        old = entries[:-keep_recent]
        recent = entries[-keep_recent:]

        logger.info("Compacting %d old entries (keeping %d)…", len(old), len(recent))

        summary_input = "\n".join(
            f"[{e.get('role','?')}] {e.get('content','')[:300]}" for e in old
        )
        try:
            summary = self._call(COMPACT_SYSTEM, summary_input, json_mode=False)
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

        tmp = self.memory.transcript.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            compaction = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "role": "system",
                "content": f"[COMPACTED {len(old)} entries]\n{summary}",
                "event": "compaction",
            }
            f.write(json.dumps(compaction, ensure_ascii=False) + "\n")
            for e in recent:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

        shutil.move(str(tmp), str(self.memory.transcript.path))
        self.memory.set_dream_cursor(self.memory.transcript.path.stat().st_size)

        return {"status": "ok", "removed": len(old), "kept": keep_recent}

    # ── Internals ─────────────────────────────────────────

    def _format_entries(self, entries: list) -> str:
        lines = []
        for e in entries:
            ts = e.get("ts", "?")[:19]
            role = e.get("role", "?")
            text = e.get("content", "")
            conf = e.get("confidence", "")
            source = e.get("source", "")
            event = e.get("event", "")

            meta_parts = []
            if conf:
                meta_parts.append(f"confidence:{conf}")
            if source:
                meta_parts.append(f"source:{source}")
            if event:
                meta_parts.append(f"event:{event}")
            meta = f" [{', '.join(meta_parts)}]" if meta_parts else ""

            if len(text) > 2000:
                text = text[:2000] + " …[truncated]"
            lines.append(f"[{ts}] ({role}){meta}: {text}")
        return "\n".join(lines)

    def _verify(self, verifications: list) -> list:
        """Verify claims against local files or registry."""
        for v in verifications:
            ctype = v.get("check_type", "none")
            cpath = v.get("check_path")

            if ctype == "none" or not cpath:
                v["verified"] = None
                v["confidence"] = v.get("confidence", "medium")
                continue

            try:
                target = Path(cpath)
                if self.workspace_root and not target.is_absolute():
                    # Smart path resolution for workspace files
                    candidates = [
                        self.workspace_root / target,
                        self.workspace_root / "_meta" / target,
                        self.workspace_root / "local-files" / target,
                    ]
                    # Also try stripping parent dirs from cpath if it looks like a path from another machine
                    if "/" in cpath or "\\" in cpath:
                        candidates.append(self.workspace_root / target.name)
                        candidates.append(self.workspace_root / "_meta" / target.name)

                    resolved = None
                    for c in candidates:
                        if c.exists():
                            resolved = c
                            break
                    if resolved:
                        target = resolved
                    else:
                        target = self.workspace_root / target # Fallback

                if ctype == "file_exists":
                    exists = target.exists()
                    v["verified"] = exists
                    v["confidence"] = "high" if exists else "low"
                    if not exists:
                        logger.warning("Verification FAILED: %s does not exist", target)

                elif ctype == "file_contains":
                    if target.exists():
                        content = target.read_text(encoding="utf-8", errors="replace").lower()
                        needle = v.get("claim", "").lower()
                        
                        # Better keyword-based matching
                        import re
                        words = [w for w in re.split(r"\W+", needle) if len(w) > 3]
                        if not words:
                            v["verified"] = True # No keywords to check - assume OK?
                            v["confidence"] = "medium"
                        else:
                            # Verify if at least two key terms or the most unique one exist
                            # For simplicity, if ANY 2 words or ANY significant word exist
                            matches = [w for w in words if w in content]
                            v["verified"] = len(matches) >= 1 # Back to at least 1 match for now to be safe
                            v["confidence"] = "high" if len(matches) >= 2 else "medium"
                    else:
                        v["verified"] = False
                        v["confidence"] = "low"
                        logger.warning("Verification FAILED: target not found for file_contains: %s", target)

                elif ctype == "registry":
                    # Registry specifically checks the project map
                    registry = self.workspace_root / "_meta" / "co-registry.csv" if self.workspace_root else None
                    if not (registry and registry.exists()):
                        # Broad fallback for registry
                        paths = ["_meta/co-registry.csv", "registry.csv", "co-registry.csv"]
                        for p in paths:
                            p_target = self.workspace_root / p if self.workspace_root else Path(p)
                            if p_target.exists():
                                registry = p_target
                                break
                    
                    if registry and registry.exists():
                        content = registry.read_text(encoding="utf-8", errors="replace").lower()
                        # Extract project IDs or names from claim
                        import re
                        terms = [t for t in re.split(r"\W+", v.get("claim", "")) if len(t) > 3]
                        v["verified"] = any(t.lower() in content for t in terms)
                        v["confidence"] = "high" if v["verified"] else "medium"
                    else:
                        v["verified"] = None
                        v["confidence"] = "low"
                        logger.warning("Registry verification SKIPPED: no registry file found")
                else:
                    v["verified"] = None
            except Exception as exc:
                logger.warning("Verification error for %s: %s", cpath, exc)
                v["verified"] = None
                v["confidence"] = "low"

        return verifications

    def _apply_topics(self, result: dict):
        failed_claims = set()
        for v in result.get("verifications", []):
            if v.get("verified") is False and v.get("confidence") == "low":
                failed_claims.add(v.get("claim", "").lower())

        for update in result.get("topic_updates", []):
            topic = update.get("topic", "").strip()
            content = update.get("content", "").strip()
            if not topic or not content:
                continue

            if any(fc in content.lower() for fc in failed_claims if fc):
                logger.warning("Skipping topic '%s' — contains unverified claims", topic)
                continue

            # Topic Splitting Check
            if len(content) > 4000:
                logger.info("Topic '%s' is large (%d chars). Suggesting split in next cycle.", topic, len(content))
                # Future: Auto-split logic could go here. 
                # For now, we just tag it in the index or log it.

            self.memory.topics.write(topic, content)

    def _rebuild_index(self, result: dict):
        now = datetime.now(timezone.utc).isoformat()
        graph = result.get("index_graph", {})
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        pending = result.get("pending_observations", [])
        active = result.get("active_context", "unknown")

        lines = [
            "# Ghost Agent Memory Index",
            f"Last updated: {now}",
            f"Dream cycle: {self._cycle + 1}",
            "",
            "## Active Context",
            f"- {active}",
            "",
            "## Topic Graph",
        ]

        if nodes:
            lines.append("### Nodes")
            for n in nodes:
                nid = n.get("id", "?")
                label = n.get("label", nid)
                ntype = n.get("type", "")
                lines.append(f"- **[{nid}]** {label} `{ntype}`")

            if edges:
                lines.append("")
                lines.append("### Edges")
                for e in edges:
                    lines.append(f"- {e.get('from','')} --{e.get('relation','related')}--> {e.get('to','')}")
        else:
            # Fallback: flat topic list
            lines.append("### Topics")
            for t in self.memory.topics.list_topics():
                lines.append(f"- [{t}](topics/{t}.md)")

        lines.append("")
        lines.append("## Pending Observations")
        if pending:
            for p in pending:
                lines.append(f"- {p}")
        else:
            lines.append("(none)")
        lines.append("")

        self.memory.index.write("\n".join(lines))


# ── Utility ───────────────────────────────────────────────

def _summarize_phase(phase_result: dict) -> str:
    """One-line summary of a phase result for the dream log."""
    if isinstance(phase_result, str):
        return phase_result[:100]
    for key in ["orient_summary", "reasoning", "consolidate_log", "prune_log"]:
        if key in phase_result:
            return phase_result[key]
    return str(len(phase_result)) + " keys"