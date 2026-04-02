# Ghost — Shared Memory Filesystem (Integration Spec)

## For AI Assistants / IDEs / Agents

This directory is a **Shared Memory Filesystem**. It contains persistent, synthesized knowledge for the entire workspace.

### 1. The Anti-API Advantage
Ghost follows the Unix philosophy: *Everything is a file.* There are no proprietary SDKs or hidden databases. Any tool that can read markdown can now use your long-term memory.

### 2. How to Integrate
Paste this into your AI chat or add it to your project's `.claude/instructions.md`, `.windsurf`, or Cursor rules:

> *Before starting work, read .ghost/MEMORY.md (index) and relevant .ghost/topics/*.md files to understand project context, recent decisions, and the "Shared Memory Standard".*

### 3. File Structure
- `MEMORY.md` — The graph-indexed entry point.
- `topics/*.md` — Distilled, authoritative knowledge files per domain.
- `transcript.jsonl` — The short-term interaction log.
- `sources.json` — External files linked to this memory ecosystem.

### 4. Writing Convention
- **READING**: Any external tool (IDE, Agent) can READ freely at any time.
- **WRITING**: Only Ghost's **Dream Engine** (Active Synthesis) writes to `topics/` and `MEMORY.md`.
- **CONTRIBUTING**: To add new facts, use `ghost inject` or append a JSON entry to `transcript.jsonl`.

### 5. Standard Implementation
For more details on the "Hippocampus" active synthesis model or the KAIROS watchdog, see the [README.md](../README.md).

---
*Version 1.1.0 — 2026-04-02*
