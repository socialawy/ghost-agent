# Ghost Agent — Local Memory/Dream/Daemon System


## 1. Architecture Overview

```
┌────────────────────────────────────────────────────────────┐
│                     ghost CLI / daemon                     │
│  ghost chat │ ghost dream │ ghost daemon │ ghost status    │
└──────┬───────────┬──────────────┬──────────────────────────┘
       │           │              │
       ▼           ▼              ▼
┌─────────────┐ ┌──────────┐ ┌───────────────────────────────┐
│   Chat      │ │  Dream   │ │   KAIROS Daemon               │
│   Loop      │ │  Engine  │ │   ┌──────────────────────┐    │
│             │ │          │ │   │ tick loop            │    │
│  user ←→ LLM│ │ consoli- │ │   │ file watcher         │    │
│  + memory   │ │ date     │ │   │ autoDream on idle    │    │
│  context    │ │ verify   │ │   │ checkpoint & resume  │    │
│             │ │ compact  │ │   └──────────────────────┘    │
└──────┬──────┘ └────┬─────┘ └──────────────┬────────────────┘
       │             │                      │
       ▼             ▼                      ▼
┌──────────────────────────────────────────────────────────┐
│                  3-Layer Memory                          │
│                                                          │
│  Layer 1: MEMORY.md          (index — always in context) │
│  Layer 2: topics/*.md        (deep knowledge per topic)  │
│  Layer 3: transcript.jsonl   (append-only full log)      │
│                                                          │
│  + .dream_cursor   (byte offset of last dreamed entry)   │
│  + daemon.json     (KAIROS checkpoint state)             │
└──────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│              Verification Gate                           │
│  file_exists · file_contains · registry_lookup           │
│  Only verified claims get "high" confidence in memory    │
└──────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│              LLM Client (pluggable)                      │
│  OpenAI-compatible: Groq, Together, Ollama, LM Studio    │
│  Anthropic: Claude via API                               │
└──────────────────────────────────────────────────────────┘
```

### Key design decisions:

- Zero GPU — everything calls external APIs (Groq free tier works great)
- Zero framework — just requests + pyyaml + stdlib
- File-based state — survives crashes, easy to inspect and debug
- Verification gate — claims about files/projects are checked against your real filesystem (if you have any, mine is E:\co) before being trusted
Cursor-based dreaming — the dream engine reads only new transcript entries, using a byte-offset cursor, so it never reprocesses old data

## 2. File Structure

```
ghost-agent/
├── requirements.txt        # 2 dependencies
├── config.yaml             # Your API keys + settings
├── llm_client.py           # Unified LLM API client (~80 lines)
├── memory.py               # 3-layer memory system (~190 lines)
├── dream.py                # autoDream consolidation engine (~260 lines)
├── ghost.py                # Main CLI + KAIROS daemon (~320 lines)
└── .ghost/                 # Created on `ghost init` (state directory)
    ├── MEMORY.md
    ├── topics/
    ├── transcript.jsonl
    ├── .dream_cursor
    └── daemon.json
```

## 3. Full Implementation

- requirements.txt

```txt
requests>=2.31
pyyaml>=6.0
```

- config.yaml
```yaml
# Ghost Agent Configuration
# Copy this to config.yaml and fill in your API key.
...
```

- memory.py
```python
"""3-layer persistent memory system.

Layer 1 — MEMORY.md        Lightweight index, always loaded into LLM context.
Layer 2 — topics/*.md      Deep per-topic knowledge files.
Layer 3 — transcript.jsonl  Append-only interaction log (hidden from main context
                            unless explicitly recalled).
"""

import ...
```

- dream.py

- ghost.py: Full CLI + KAIROS Daemon

## 4. Quick Start
```bash
# 1. Create the project
mkdir ghost-agent && cd ghost-agent

# 2. Save the four .py files + config.yaml + requirements.txt above

# 3. Install (just 2 deps)
pip install -r requirements.txt

# 4. Edit config.yaml with your Groq (free) or other API key

# 5. Initialize
python ghost.py init

# 6. Chat (memory persists automatically)
python ghost.py chat

# 7. Trigger a dream manually (or let the daemon do it)
python ghost.py dream

# 8. Run the daemon in a separate terminal
python ghost.py daemon

# 9. Inject your CO_PM.json as starting context
python ghost.py inject "$(cat CO_PM.json)"
python ghost.py dream
```

## 5. Current state vs. The Leaked Architecture

| Claude Code Pattern | Ghost Implementation | Status |
|---|---|---|
| 3-layer memory (MEMORY.md + topics + transcript) | memory.py — identical structure | ✅ |
| Write discipline (verify before trust) | dream.py _verify() — file_exists, file_contains, registry | ✅ |
| autoDream (background consolidation) | dream.py dream() — LLM-driven merge/resolve/compact | ✅ |
| KAIROS daemon (tick loop + resume) | ghost.py KairosDaemon — checkpoint JSON, signal handling | ✅ |
| Compaction (prevent context entropy) | dream.py compact() — LLM-summarized, atomic rewrite | ✅ |
| File watchers | Daemon watches configured paths by mtime | ✅ |
| Crash resume | daemon.json checkpoint, byte-offset cursor | ✅ |
| Prompt-cache-aware boundaries | System prompt template with stable memory prefix | ✅ partial |
| ULTRAPLAN (offload to Opus) | Not yet — easy to add as a second LLM config | 🔲 |
| Multi-agent orchestration | Not yet — but the dream engine is already a "sub-agent" | 🔲 |
| 40 tool plugins | Not yet — modular by design, add tool functions | 🔲 |

## 6. Next Steps

### Immediate improvements

1. ghost bridge — a local HTTP server that accepts /chat POSTs and can call Ghost from other scripts, VS Code extensions, or webhooks

2. Topic auto-retrieval — before each chat turn, use embedding similarity or keyword match to pull only relevant topics instead of all of them

3. Dual-LLM config — cheap model (Groq Llama) for chat, expensive model (Claude/GPT/Any paid/quota limited) for dream cycles that need deeper reasoning

4. ghost inject --file — bulk-load your master project file (if you have any, mine is E:\co\CO_PM.json), or registry CSVs, etc.

### Medium-term (the really interesting stuff):

5. ULTRAPLAN module — when the user types /plan <goal>, fork a long-thinking call to Opus/o3 with extended budget, stream results back into a topic file

6. GitHub webhook listener — the daemon subscribes to repo events and auto-logs them (PR merged, issue opened, CI failed)

7. Multi-workspace — point Ghost at multiple project roots, each with its own topic namespace

---

### Auto-tab/IDE suggestions

- [ ] Add file watchers for the project directory (not just memory files)
- [ ] Add a web UI (optional, but nice to have)
