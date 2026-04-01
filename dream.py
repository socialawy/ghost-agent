"""autoDream — background memory consolidation engine.

Reads new transcript entries, sends them to the LLM with current memory state,
and applies verified updates back to the topic store and index.
"""

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from llm_client import LLMClient
from memory import Memory

logger = logging.getLogger("ghost.dream")

# ── System prompt for the dream LLM call ─────────────────

DREAM_SYSTEM = """\
You are a **memory consolidation agent**.  Your only job is to process new
observations from an interaction transcript and update the agent's long-term
memory.

OUTPUT FORMAT — respond with **only** valid JSON (no markdown fences):
{
  "topic_updates": [
    {
      "topic": "slug-name",
      "action": "create" | "update",
      "content": "Full markdown content for the topic file."
    }
  ],
  "index_summary": {
    "active_context": "One-line summary of current user focus",
    "topic_list": ["slug-1", "slug-2"],
    "pending_observations": ["Things that don't fit a topic yet"]
  },
  "verifications": [
    {
      "claim": "Human-readable claim",
      "check_type": "file_exists" | "file_contains" | "registry" | "none",
      "check_path": "path or null",
      "confidence": "high" | "medium" | "low"
    }
  ],
  "contradictions": [
    {
      "existing": "What memory says now",
      "new_info": "What new evidence says",
      "resolution": "Which wins and why"
    }
  ],
  "dream_log": "≤2 sentence human-readable summary of this dream cycle"
}

RULES:
1. Only touch topics that actually changed.
2. When updating a topic, output its COMPLETE new content (not a diff).
3. Prefer merging into existing topics over creating new ones.
4. Never fabricate — only consolidate what the transcript actually says.
5. Flag low-confidence claims for verification.
6. Compress redundancy, preserve important detail.
"""

COMPACT_SYSTEM = """\
Summarize these interaction log entries into a concise summary (max 400 words).
Preserve: key decisions, facts, user preferences, project states, action items.
Discard: greetings, filler, verbose tool output, repeated info.
Output only the summary text, no preamble.
"""


class DreamEngine:
    """Runs dream consolidation cycles against the 3-layer memory."""

    def __init__(
        self,
        memory: Memory,
        llm: LLMClient,
        workspace_root: Optional[Path] = None,
    ):
        self.memory = memory
        self.llm = llm
        self.workspace_root = workspace_root
        self._cycle = 0

    # ── public API ────────────────────────────────────────

    def should_dream(self, min_entries: int = 5) -> bool:
        cursor = self.memory.get_dream_cursor()
        entries, _ = self.memory.transcript.read_since(cursor)
        return len(entries) >= min_entries

    def dream(self) -> dict:
        """Run one consolidation cycle.  Returns a status dict."""
        cursor = self.memory.get_dream_cursor()
        new_entries, new_cursor = self.memory.transcript.read_since(cursor)

        if not new_entries:
            logger.info("Dream: nothing new.")
            return {"status": "skipped", "reason": "no new entries"}

        logger.info("Dream: processing %d new entries…", len(new_entries))

        # ── 1. gather current state ──────────────────────
        current_index = self.memory.index.read()
        current_topics = self.memory.topics.read_all()

        # ── 2. call LLM ─────────────────────────────────
        user_prompt = self._build_prompt(current_index, current_topics, new_entries)
        try:
            raw = self.llm.chat(
                messages=[{"role": "user", "content": user_prompt}],
                system=DREAM_SYSTEM,
                json_mode=True,
            )
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("Dream: LLM returned invalid JSON: %s", exc)
            # Try to salvage — some models wrap in ```json fences
            try:
                cleaned = raw.strip().removeprefix("```json").removesuffix("```").strip()
                result = json.loads(cleaned)
            except Exception:
                return {"status": "error", "error": f"bad JSON: {exc}"}
        except Exception as exc:
            logger.error("Dream: LLM call failed: %s", exc)
            return {"status": "error", "error": str(exc)}

        # ── 3. verification gate ─────────────────────────
        verifications = result.get("verifications", [])
        if verifications:
            result["verifications"] = self._verify(verifications)

        # ── 4. apply updates ─────────────────────────────
        self._apply(result)

        # ── 5. advance cursor ────────────────────────────
        self.memory.set_dream_cursor(new_cursor)
        self._cycle += 1

        dream_log = result.get("dream_log", "cycle complete")
        self.memory.transcript.append(
            role="system",
            content=f"[DREAM #{self._cycle}] {dream_log}",
            event="dream",
        )

        logger.info("Dream #%d done: %s", self._cycle, dream_log)
        return {"status": "ok", "cycle": self._cycle, "dream_log": dream_log}

    def compact(self, keep_recent: int = 100) -> dict:
        """Summarize old transcript entries to prevent unbounded growth."""
        entries = self.memory.transcript.read_all()
        total = len(entries)

        if total <= keep_recent * 2:
            return {"status": "skipped", "reason": f"only {total} entries, threshold {keep_recent*2}"}

        old = entries[:-keep_recent]
        recent = entries[-keep_recent:]

        logger.info("Compacting %d old entries (keeping %d recent)…", len(old), len(recent))

        # Summarize via LLM
        summary_input = "\n".join(
            f"[{e.get('role','?')}] {e.get('content','')[:300]}" for e in old
        )
        try:
            summary = self.llm.chat(
                messages=[{"role": "user", "content": summary_input}],
                system=COMPACT_SYSTEM,
            )
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

        # Rewrite transcript atomically
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
        # Set cursor to end (everything already dreamed)
        self.memory.set_dream_cursor(self.memory.transcript.path.stat().st_size)

        logger.info("Compaction done: %d → %d entries", total, keep_recent + 1)
        return {"status": "ok", "removed": len(old), "kept": keep_recent}

    # ── internals ─────────────────────────────────────────

    def _build_prompt(self, index: str, topics: dict, entries: list) -> str:
        parts = ["## Current Memory Index", index, ""]
        parts.append("## Current Topic Files")
        if topics:
            for name, content in topics.items():
                parts.extend([f"### {name}", content, ""])
        else:
            parts.append("(no topics yet)\n")

        parts.append(f"## New Observations ({len(entries)} entries)")
        for e in entries:
            ts = e.get("ts", "?")[:19]
            role = e.get("role", "?")
            text = e.get("content", "")
            if len(text) > 2000:
                text = text[:2000] + " …[truncated]"
            parts.append(f"[{ts}] ({role}): {text}")

        return "\n".join(parts)

    def _verify(self, verifications: list) -> list:
        """Run read-only checks against the real filesystem."""
        for v in verifications:
            ctype = v.get("check_type", "none")
            cpath = v.get("check_path")

            if ctype == "none" or not cpath:
                v["verified"] = None
                continue

            try:
                target = Path(cpath)
                if self.workspace_root and not target.is_absolute():
                    target = self.workspace_root / target

                if ctype == "file_exists":
                    exists = target.exists()
                    v["verified"] = exists
                    if exists:
                        v["confidence"] = "high"
                    else:
                        v["confidence"] = "low"
                        logger.warning("Verification FAILED: %s does not exist", target)

                elif ctype == "file_contains":
                    if target.exists():
                        content = target.read_text(encoding="utf-8", errors="replace")
                        needle = v.get("claim", "")
                        # Simple heuristic — check if any key phrase appears
                        v["verified"] = any(
                            word.lower() in content.lower()
                            for word in needle.split()[:5]
                            if len(word) > 3
                        )
                        v["confidence"] = "high" if v["verified"] else "medium"
                    else:
                        v["verified"] = False
                        v["confidence"] = "low"

                elif ctype == "registry":
                    # Check co-registry.csv for a project name
                    registry = self.workspace_root / "_meta" / "co-registry.csv" if self.workspace_root else None
                    if registry and registry.exists():
                        content = registry.read_text(encoding="utf-8", errors="replace").lower()
                        search = v.get("claim", "").lower().split()[0] if v.get("claim") else ""
                        v["verified"] = search in content
                        v["confidence"] = "high" if v["verified"] else "medium"
                    else:
                        v["verified"] = None
                        v["confidence"] = "low"
                else:
                    v["verified"] = None

            except Exception as exc:
                logger.warning("Verification error for %s: %s", cpath, exc)
                v["verified"] = None
                v["confidence"] = "low"

        return verifications

    def _apply(self, result: dict):
        """Apply dream results to memory layers 1 and 2."""

        # ── Topic updates ─────────────────────────────────
        for update in result.get("topic_updates", []):
            topic = update.get("topic", "").strip()
            content = update.get("content", "").strip()
            if not topic or not content:
                continue

            # Reject unverified topics that reference specific files
            # (conservative: only block if a verification explicitly failed)
            failed_verifications = [
                v for v in result.get("verifications", [])
                if v.get("verified") is False and v.get("confidence") == "low"
            ]
            failed_claims = {v.get("claim", "").lower() for v in failed_verifications}
            if any(claim_fragment in content.lower() for claim_fragment in failed_claims if claim_fragment):
                logger.warning(
                    "Skipping topic '%s' — contains unverified claims", topic
                )
                continue

            self.memory.topics.write(topic, content)

        # ── Index rebuild ─────────────────────────────────
        idx = result.get("index_summary")
        if idx:
            now = datetime.now(timezone.utc).isoformat()
            topic_list = idx.get("topic_list", self.memory.topics.list_topics())
            pending = idx.get("pending_observations", [])

            lines = [
                "# Ghost Agent Memory Index",
                f"Last updated: {now}",
                f"Dream cycle: {self._cycle + 1}",
                "",
                "## Active Context",
                f"- {idx.get('active_context', 'unknown')}",
                "",
                "## Topic Files",
            ]
            for t in topic_list:
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