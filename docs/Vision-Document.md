# Ghost Agent — Vision & Architecture Blueprint

## What Ghost Is
A **shared memory filesystem** that any AI tool can read.
- `.ghost/MEMORY.md` is the index. Any tool reads it.
- `.ghost/topics/*.md` is the knowledge. Pure markdown.
- `.ghost/transcript.jsonl` is the raw log. Append-only.
- `.ghost/sources.json` links to authoritative files on disk.
- The **dream engine** consolidates raw observations into
  structured knowledge on a schedule. It synthesizes, not retrieves.
- The **KAIROS daemon** runs 24/7, watches for changes, triggers dreams.

**Ghost is personal infrastructure.** It is not B2B SaaS, not a LangChain-style developer tool, and not something you sell to teams. It is the layer that lets a solo developer or researcher operate with the memory and continuity of an entire team. Like git for your knowledge — simple, local, file-based, and timeless. The .ghost/ directory becomes your second brain, and any AI tool (Claude Code, Cursor, Windsurf, a shell script) can read it without plugins, SDKs, or network calls.

## What Ghost Is Not
- Not an agent framework (no tool plugins, no action chains)
- Not a RAG system (no embeddings, no vector DB, no retrieval)
- Not an API service (no server, no SDK, no auth)
- Not tied to any model or provider

## Core Principles
1. **Files are the API.** If you can `cat` a file, you can use Ghost.
2. **Synthesis over retrieval.** Dreams rewrite knowledge, not index it.
3. **Sources are authoritative.** Linked files are read directly, not
   copied into the transcript. PM files, registries, configs — Ghost
   reads them from disk every dream cycle.
4. **Verification before trust.** Claims are checked against the real
   filesystem before being written to memory.
5. **Provider-agnostic.** Any LLM works. Local Ollama, free Groq,
   paid Claude. The memory outlives every provider.

## Architecture
Source files (PM.json, registry.csv, etc.)
│
│ ghost link ← registers, doesn't copy
│
▼
┌─────────────────────────────────┐
│ KAIROS Daemon                   │
│ tick loop → watch sources       │
│ → watch workspace               │
│ → trigger autoDream             │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│ 4-Phase Dream Engine            │
│                                 │
│ 1. Orient: what changed?        │
│ 2. Gather: load relevant        │
│ topics + sources                │
│ 3. Consolidate: merge, verify,  │
│ write topics                    │
│ 4. Prune: clean stale data      │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│ .ghost/ (shared memory)         │
│                                 │
│ MEMORY.md ← graph index         │
│ topics/*.md ← knowledge         │
│ GHOST_SPEC.md ← integration     │
│ sources.json ← file links       │
│ transcript.jsonl ← raw log      │
└──────────────┬──────────────────┘
               │
    ┌──────────┼──────────┐
    ▼          ▼          ▼
    Claude     Cursor     Shell
    Code       /Windsurf script
    reads      reads      reads
    MEMORY.md  topics/    MEMORY.md

## Provider Strategy
- **Chat:** Fastest available (Ollama local → Groq free → paid)
- **Dream:** Smartest available (DeepSeek free → Gemini → Claude)
- **Chat is cheap, dreams are valuable.** Optimize accordingly.
- Future: provider cascade (try local, fall back to cloud)

## Scaling Strategy (v1.2+)

### Round-Robin Source Digestion
When linked sources exceed what fits in one dream call:
- Daemon maintains a source queue ordered by last_read time
- Each dream cycle processes ONE source (most stale first)
- Full rotation across N sources takes N dream cycles
- Changed sources get priority (jump to front of queue)

### Topic Splitting
When a topic exceeds ~3000 chars:
- Dream engine splits into sub-topics automatically
- MEMORY.md graph gains new nodes and edges
- Parent topic becomes a summary pointing to children

### Multi-Workspace
Ghost can serve multiple project roots:
- Each root gets its own `.ghost/` directory
- A master index at `~/.ghost/` links them all
- Cross-workspace queries traverse the master index

## Integration Patterns

### Any AI Chat (paste this)
Read .ghost/MEMORY.md for my project context.
For details on a topic, read .ghost/topics/.md


### Claude Code / Windsurf / Cursor
.claude/instructions.md (or equivalent)
Before starting, read these files for full context:

../../ghost-agent/.ghost/MEMORY.md
../../ghost-agent/.ghost/topics/*.md


### GitHub Actions / CI
```yaml
# .github/workflows/ghost-sync.yml
- name: Update Ghost memory
  run: |
    echo "CI: Tests passed, coverage at 94%" >> .ghost/transcript.jsonl
```

### Shell Alias
```bash
alias ghost-ctx="cat .ghost/MEMORY.md .ghost/topics/*.md"
# Pipe into any tool: ghost-ctx | pbcopy
```

---

## Roadmap

### v1.1 ✓ (shipped)
- 4-phase dream, rate-limit resilience, dual-LLM, source linking

### v1.2 ✓ (shipped)
- Round-robin source digestion
- Provider cascade (local → free → paid)
- Topic auto-splitting at size threshold
- File locking for transcript (belt-and-suspenders)
- ghost unlink, ghost sources commands

### v1.3
- Cross-project graph (edges between topics from different sources)
- Dream quality scoring (detect when a dream degraded a topic)
- ghost diff — show what changed between dream cycles

### v2.0
- Multi-workspace with master index
- Webhook listener (GitHub, Linear, etc.)
- ULTRAPLAN: long-think planning offloaded to expensive model
- Optional web dashboard (read-only view of .ghost/)