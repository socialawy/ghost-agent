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
