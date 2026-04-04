# Ghost Agent — User Manual

**Version:** 1.6  
**Last updated:** April 2026

---

## Table of Contents

1. [What Is Ghost?](#what-is-ghost)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Core Concepts](#core-concepts)
5. [Commands Reference](#commands-reference)
6. [Source Linking](#source-linking)
7. [The Dream Engine](#the-dream-engine)
8. [The KAIROS Daemon](#the-kairos-daemon)
9. [Ghost Bridge (HTTP API)](#ghost-bridge)
10. [Multi-Workspace](#multi-workspace)
11. [ULTRAPLAN](#ultraplan)
12. [Continuous Context Management](#continuous-context-management)
13. [IDE Integration](#ide-integration)
14. [Provider Setup](#provider-setup)
15. [Troubleshooting](#troubleshooting)
16. [Architecture Reference](#architecture-reference)

---

## What Is Ghost?

Ghost is a **shared memory filesystem** for AI-assisted development.
It maintains persistent knowledge about your projects, decisions, and
context in plain markdown files that any tool can read.

Ghost is **not** a chatbot, not a RAG system, not an agent framework.
It is a memory layer. You work. Ghost remembers. Every AI tool you
use — Claude Code, Cursor, Windsurf, a shell script — reads the
same files and starts with full context.

### How It Works (30-Second Version)
```
You work on projects
↓
You inject observations ("GRID hit 900 tests")
↓
Ghost appends to transcript.jsonl (raw log)
↓
Dream engine runs (on schedule or manually)
↓
Observations are consolidated into topics/*.md
↓
MEMORY.md index is updated with a knowledge graph
↓
Any AI tool reads MEMORY.md and knows everything
```

### What Makes Ghost Different

| Feature | Ghost | mem0 / Zep / MemGPT |
|---|---|---|
| Interface | Files (`cat .ghost/MEMORY.md`) | API / SDK |
| Storage | Markdown on disk | Vector DB / Cloud |
| Memory type | Active synthesis (rewrites knowledge) | Retrieval (searches past conversations) |
| Dependencies | `requests`, `pyyaml`, `python-dotenv` | Embeddings, servers, databases |
| Integration | Any tool that reads files | Custom plugins per tool |
| GPU required | No | Often yes (embeddings) |

---

## Installation

### Requirements
- Python 3.10+
- An LLM API key (free options available) OR local Ollama

### Setup

```bash
git clone https://github.com/AhmedFSadek/ghost-agent.git
cd ghost-agent
pip install -r requirements.txt

# Configure
cp config.yaml.example config.yaml
cp .env.example .env
# Edit both files with your API keys and preferences

# Initialize
python ghost.py init

# Verify
python ghost.py ping
```
### Minimal Free Setup (No Credit Card)
```bash
# Option 1: Groq (free, cloud, rate-limited)
# Get key: https://console.groq.com
# Set GROQ_API_KEY in .env

# Option 2: Ollama (free, local, unlimited)
# Install: https://ollama.ai
ollama pull llama3.1:8b
# Set base_url to http://localhost:11434/v1 in config.yaml

# Option 3: DeepSeek (free, cloud, generous limits)
# Get key: https://platform.deepseek.com
# Set DEEPSEEK_API_KEY in .env
```
### Configuration

- Configuration
```yaml
# Primary model for interactive chat
llm:
  provider: "openai"          # or "anthropic"
  base_url: "https://api.groq.com/openai/v1"
  api_key: "${GROQ_API_KEY}"  # Resolved from .env
  model: "llama-3.3-70b-versatile"
  max_tokens: 4096
  temperature: 0.3
  min_interval: 3.0           # Seconds between API calls
  json_mode_supported: true   # Set false for models that reject it

# Optional: dedicated model for dream consolidation
# If omitted, dreams use the chat model
dream_llm:
  provider: "openai"
  base_url: "https://api.deepseek.com/v1"
  api_key: "${DEEPSEEK_API_KEY}"
  model: "deepseek-chat"
  max_tokens: 8192
  temperature: 0.2
  min_interval: 1.0

# State directory (created by ghost init)
state_dir: ".ghost"

# Your workspace root (for file verification)
workspace_root: "E:\\co"      # Adjust to your path

# Dream settings
dream:
  min_new_entries: 5          # Entries before auto-dream triggers
  auto_interval_minutes: 15   # Minutes between daemon dreams
  compact_threshold: 200      # Entries before auto-compaction

# Daemon settings
daemon:
  tick_interval_seconds: 60   # Daemon wake-up frequency
  watch_paths:                # Files to monitor for changes
    - "path/to/important/file.csv"
```

- .env File
```bash
GROQ_API_KEY=gsk_your_key_here
DEEPSEEK_API_KEY=sk-your_key_here
GEMINI_API_KEY=your_key_here
ANTHROPIC_API_KEY=sk-ant-your_key_here
OPENAI_API_KEY=sk-your_key_here
```

### Provider Cascade

- Ghost can try multiple providers in order, falling back on failure:
```yaml
llm:
  providers:
    - provider: "openai"
      base_url: "http://localhost:11434/v1"
      api_key: "ollama"
      model: "llama3.1:8b"
    - provider: "openai"
      base_url: "https://api.groq.com/openai/v1"
      api_key: "${GROQ_API_KEY}"
      model: "llama-3.3-70b-versatile"
    - provider: "openai"
      base_url: "https://api.deepseek.com/v1"
      api_key: "${DEEPSEEK_API_KEY}"
      model: "deepseek-chat"
```
- This tries Ollama first (free, local), then Groq, then DeepSeek.

## Core Concepts

### The 3-Layer Memory
```
Layer 1: MEMORY.md          Always loaded. Graph index of all knowledge.
Layer 2: topics/*.md         Per-topic knowledge files. Detailed markdown.
Layer 3: transcript.jsonl    Append-only raw log. Hidden from chat context.
```

#### Layer 1 (MEMORY.md) is what AI tools read first. It contains a
graph of nodes (topics) and edges (relationships). Think of it as a
table of contents for your entire knowledge base.

#### Layer 2 (topics/) contains the actual knowledge. Each file is a
self-contained reference document on one subject. Written and
maintained by the dream engine.

#### Layer 3 (transcript.jsonl) is the raw firehose. Every
observation, chat message, dream result, and daemon event is appended
here. The dream engine reads new entries and consolidates them into
topics. You rarely read this directly.

### Confidence Levels

- Every piece of information has a trust level:

| Source | Confidence | Why |
|---|---|---|
| ghost inject (manual) | verified | You said it |
| ghost inject -f (file) | verified | You provided the file |
| ghost link (source) | verified | Read from your filesystem |
| LLM chat response | unverified | Model might hallucinate |
| Dream consolidation | Depends | Verified against filesystem when possible |

- The dream engine treats unverified data with skepticism. It will
not promote LLM speculation to topic-level knowledge without
corroboration from user input or filesystem verification.

### Verification Gate

- Before writing claims about files or projects to memory, the dream
engine checks the real filesystem:
    - file_exists: Does the path actually exist?
    - file_contains: Does the file contain the claimed content?
    - registry: Is the project in co-registry.csv?
- Claims that fail verification are marked low-confidence and may be demoted during the Prune phase.

## Commands Reference

### Initialization & Status

| Command | Description |
|---|---|
| `ghost init` | Create .ghost/ state directory |
| `ghost status` | Show memory stats, topic count, daemon state |
| `ghost ping` | Test LLM connectivity and pacing |

### Memory Operations

| Command | Description |
|---|---|
| `ghost inject "text"` | Add an observation to the transcript |
| `ghost inject -f path` | Inject a file's contents |
| `ghost link path` | Register a file as a persistent source |
| `ghost unlink path` | Remove a linked source |
| `ghost sources` | List all linked sources with status |
| `ghost recall <topic>` | Print a topic file |


### Dream & Maintenance

| Command | Description |
|---|---|
| `ghost dream` | Run one dream consolidation cycle |
| `ghost diff` | Show what changed in the last dream |
| `ghost compact` | Summarize old transcript entries |

### Interactive

| Command | Description |
|---|---|
| `ghost chat` | Interactive chat with memory context |
| `ghost plan <goal>` | ULTRAPLAN: deep strategic planning |

### Infrastructure

| Command | Description |
|---|---|
| `ghost daemon` | Start the KAIROS always-on daemon |
| `ghost bridge` | Start the HTTP API server |
| `ghost context` | Debug: show the exact string being sent to LLM |
| `ghost workspace list` | List registered workspaces |
| `ghost workspace search <query>` | Search across workspaces |

### Chat Slash Commands

- Inside ghost chat, these commands are available:

| Command | Description |
|---|---|
| `/dream` | Trigger a dream cycle |
| `/status` | Show memory stats |
| `/recall <topic>` | Read a topic |
| `/compact` | Compact transcript |
| `/context` | Show full context being sent to LLM (budget-aware) |
| `/verify <claim>` | Check a claim against filesystem |
| `/add <text>` | Inject a fact with high confidence |
| `/quit` | Exit chat |

### Source Linking

Source linking is Ghost's most important feature. Instead of
copying file contents into the transcript (which loses structure),
you link files. The dream engine reads them directly from disk.

#### Why Link Instead of Inject?

```bash
# BAD: Copies 23KB into transcript, dream summarizes, loses 95%
ghost inject -f DOXASCOPE_PM.json

# GOOD: Registers the file, dream reads it fresh every cycle
ghost link DOXASCOPE_PM.json
```
- When you link a file:

1- Ghost records its path in sources.json
2- Each dream cycle, the engine checks if the file changed (by mtime)
3- If changed, it reads the file and includes it in consolidation
4- The file is never copied — Ghost always reads the latest version

#### Round-Robin Processing

- The dream engine processes sources in a round-robin fashion:
When you have many linked sources, Ghost processes ONE source per
dream cycle, picking the most stale or most recently changed. This
prevents context overflow. A full rotation through N sources takes
N dream cycles.

#### Supported File Types

- Ghost reads any text file. The dream engine handles:
    - `.json` — Extracts key fields, counts, statuses
    - `.csv` — Extracts column names, row counts, key values
    - `.md` — Preserves structure, extracts headings and lists
    - `.txt` — Treats as plain observations
    - Any other text format — Best effort extraction

### Example Workflow

```bash
# Link your project management files
ghost link ~/projects/CO_PM.json
ghost link ~/projects/registry.csv
ghost link ~/projects/doxascope/DOXASCOPE_PM.json

# Check status
ghost sources

# Dream — processes the most stale source
ghost dream

# Edit CO_PM.json in any editor...
# Next dream automatically detects the change
ghost dream  # Picks up CO_PM.json changes
```
---

## The Dream Engine

- The dream engine is Ghost's core intelligence. It reads raw
observations and consolidates them into structured knowledge.

### 4-Phase Pipeline
```
Phase 1: ORIENT   — What changed? Diff new entries against memory.
Phase 2: GATHER   — Which topics and sources are relevant?
Phase 3: CONSOLIDATE — Merge new data into topics. Verify claims.
Phase 4: PRUNE    — Remove stale data, demote low-confidence claims.
```
- Each phase is a separate LLM call with a focused prompt. This is cheaper and more reliable than a single monolithic call.

### Data Preservation Rules

- The dream engine follows strict rules to prevent data loss:
1. Never generalize. If the source says "107 projects", the
topic says "107 projects" — not "many projects."
2. Preserve numbers, names, versions, dates, paths.
3. Extract structured data into bullet points or tables.
4. Topic files are reference documents, not summaries.

### Quality Scoring

- After each dream, the engine scores its own output:
    - Healthy: All data preserved, no regressions
    - Degraded: Some terms lost from existing topics (flagged with warnings)
    - Failed: JSON parsing failed, no changes written
- Use `ghost diff` to see exactly what changed and verify quality.

### Manual vs Automatic Dreams

```bash
# Manual: run whenever you want
ghost dream

# Automatic: the daemon runs dreams on a schedule
ghost daemon
# Dreams trigger every auto_interval_minutes (default: 15)
# Only if min_new_entries threshold is met (default: 5)
```

---

## The KAIROS Daemon

- KAIROS is Ghost's always-on background process. It watches your workspace and triggers dreams automatically.

### Starting
```bash
python ghost.py daemon
# Runs until Ctrl+C or SIGTERM
```

### What It Does Each Tick

1. Watches configured files for mtime changes
2. Checks linked sources for modifications
3. Triggers autoDream if enough time and entries have accumulated
4. Auto-compacts transcript if it exceeds the threshold
5. Logs heartbeat every 10 ticks

### Crash Recovery

- The daemon saves its state to daemon.json after every tick:
    - Tick count, dream count, last dream time
    - File watch hashes (mtime tracking)
    - Last compact time
- If the daemon crashes or is stopped, it resumes from the last
checkpoint on next start. No data is lost — the transcript is
append-only.

### Recommended Setup

- Run the daemon in a dedicated terminal or as a background process:

```bash
# Dedicated terminal (recommended during development)
python ghost.py daemon

# Background (Linux/Mac)
nohup python ghost.py daemon > ghost-daemon.log 2>&1 &

# Background (Windows PowerShell)
Start-Process -NoNewWindow python "ghost.py daemon"
```
---

## Ghost Bridge

- The Ghost Bridge exposes memory operations via a local HTTP API.

### Starting

```bash
python ghost.py bridge
# Runs on http://127.0.0.1:8000
```

### Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /health | Health check |
| GET | /status | Memory stats (same as CLI) |
| GET | /recall/<topic> | Read a topic file |
| POST | /inject | Add observation {"text": "..."} |
| POST | /chat | Chat with memory {"message": "..."} |
| POST | /dream | Trigger a dream cycle |

### Use Cases

```bash
# Inject from a CI pipeline
curl -X POST http://localhost:8000/inject \
  -H "Content-Type: application/json" \
  -d '{"text": "CI: Deploy succeeded, version 2.3.1"}'

# Read context from any script
curl http://localhost:8000/recall/co-workspace

# Trigger a dream from a webhook
curl -X POST http://localhost:8000/dream
```

### Multi-Workspace

- Ghost can track multiple project roots, each with its own
`.ghost/` directory.

### Setup

```bash
# Register workspaces
ghost workspace add ~/projects/main
ghost workspace add ~/projects/client-work

# List all registered workspaces
ghost workspace list

# Search across all workspaces
ghost workspace search "authentication"
```

### Master Index

- A central registry at `~/.ghost/master.json` links all workspace
`.ghost/` directories. Cross-workspace searches traverse this index.

---

## ULTRAPLAN

- For complex architectural decisions, ULTRAPLAN offloads deep
thinking to a high-capability model.
```bash
ghost plan "Design the authentication system for The Artifact game"
```
This
    1. Gathers all relevant context from memory
    2. Sends it to the configured planning model (e.g., Claude Opus)
    3. Allows extended thinking time
    4. Saves the result as a `plan-<slug>` topic in `.ghost/topics/`

## Continuous Context Management

As your knowledge base grows, sending every topic to the LLM for every chat would exceed context windows and increase latency. Ghost v1.6+ solves this with iterative, multi-layer context management.

### TOKEN_BUDGET
By setting `context.token_budget` in `config.yaml`, Ghost restricts the total characters sent to the LLM (Layer 1 + Layer 2).
- **Expanded Topics**: Most recent or relevant topics are included in full.
- **Collapsed Topics**: Topics that exceed the budget but are still in the index are collapsed to a single line: `[COLLAPSED: 1200 chars, /recall topic-name]`.
- This ensures the model knows *what* it knows, without wasting tokens on irrelevant details.

### CONTEXT_COLLAPSE (Topic Prioritization)
Ghost tracks which topics were mentioned in your last 30 minutes of interaction.
- **Priority**: Recently referenced topics stay Expanded.
- **Stale**: Topics not mentioned recently are candidates for Collapse if the budget is reached.

### HISTORY_SNIP (Smart Windowing)
Instead of a blind "last 40 messages" window, `HISTORY_SNIP` analyzes the current turn's keywords and searches the transcript for relevant past interactions.
- It keeps messages that share a "semantic bridge" to the current topic.
- It drops irrelevant tangents, keeping the conversation focused even after thousands of turns.

### REACTIVE_COMPACT
When the transcript grows too large (e.g., > 100 entries), Ghost automatically triggers a **Micro-Compaction** cycle:
- The oldest 50% of the transcript is summarized inline.
- Your history becomes: `[PREVIOUSLY: Summarized details of setup phase...]` followed by fresh interactions.

### CONFIGURATION
```yaml
context:
  token_budget: 4096          # Total characters (approx) to send to LLM. 0 = unlimited.
  max_entries: 50             # Max transcript entries before reactive compaction starts.
  snip_overlap_threshold: 0.2 # Term overlap required for history snipping.
```

---

## Continuous Context Management

As your project grows, your knowledge base can exceed the context window of even the largest LLMs. Ghost 1.6.0 introduces a multi-layered context management system to keep your agents focused.

### TOKEN_BUDGET (The Hard Limit)
Configurable via `context.token_budget` in `config.yaml`.
- When set (e.g., `4096`), Ghost automatically calculates the priority of all topics and index data.
- Topics that exceed the budget are **collapsed** into one-line headers:
  `[COLLAPSED: 1200 chars, /recall topic-name]`
- This ensures the model knows the topic exists but doesn't waste tokens on irrelevant details.

### CONTEXT_COLLAPSE (Smart Prioritization)
Ghost tracks which topics you've mentioned recently (via `ghost chat` or `ghost recall`).
- **High Priority**: Recently referenced topics and the global index (`MEMORY.md`).
- **Low Priority**: Stale topics not mentioned in the last 30 minutes.
- When the budget is hit, stale topics are collapsed first.

### HISTORY_SNIP (Relevant Windowing)
Ghost 1.6.0 replaces the static "last 40 messages" window with a semantic sniper.
- It analyzes the term overlap between early messages and the current turn.
- If a message from 100 turns ago is semantically linked to your current task, it is **kept**.
- Irrelevant filler messages are snipped, even if they were more recent.

### REACTIVE_COMPACT & CACHED_MICROCOMPACT
When your interaction transcript grows too large for the `max_entries` threshold:
- Ghost triggers an inline **micro-compaction**.
- The oldest half of the transcript is summarized into a few dense paragraphs.
- These summaries are cached in `.ghost/compact_cache.json` to prevent re-summarizing the same blocks repeatedly, saving both time and tokens.

---

## IDE Integration

- Claude Code
Add to your `.claude/` memory file
```markdown
Before starting work, read these files for context:
- /path/to/ghost-agent/.ghost/MEMORY.md
- /path/to/ghost-agent/.ghost/topics/*.md
```

### Cursor / Windsurf

- Add to your project's AI instructions file:
```markdown
Read .ghost/MEMORY.md for project context and recent decisions.
For detailed topic knowledge, read .ghost/topics/<name>.md
```
### Any AI Chat Session

- Paste this at the start:
```
Read these files for my project context:
- .ghost/MEMORY.md (knowledge graph index)
- .ghost/topics/*.md (detailed topic files)
```

### Shell Integration

```bash
# Add to ~/.bashrc or PowerShell $PROFILE

# Quick inject from anywhere
alias ghost-inject="python /path/to/ghost-agent/ghost.py inject"

# View full context
alias ghost-ctx="cat /path/to/.ghost/MEMORY.md /path/to/.ghost/topics/*.md"

# Pipe context to clipboard (Mac)
alias ghost-copy="ghost-ctx | pbcopy"

# Pipe context to clipboard (Windows)
# function ghost-copy { ghost-ctx | Set-Clipboard }
```

### Git Hooks

- Auto-log commits to Ghost:

```bash
# .git/hooks/post-commit
#!/bin/sh
MSG=$(git log -1 --format="%s")
python /path/to/ghost-agent/ghost.py inject "Commit: $MSG"
```

### Provider Setup

- Free Providers

| Provider | Setup | Limits | Best For |
|---|---|---|---|
| Ollama | ollama pull llama3.1:8b | None (local) | Chat (unlimited) |
| Groq | console.groq.com | 100K tokens/day | Chat + Dream |
| DeepSeek | platform.deepseek.com | Generous free tier | Dream (128K context) |

**Or bring yours**

### Recommended Split
```yaml
# Chat: fast and free
llm:
  model: "llama3.1:8b"  # Ollama local
  # or Groq llama-3.3-70b-versatile

# Dream: smart and generous
dream_llm:
  model: "deepseek-chat"  # Free, 128K context
  # or gemini-2.0-flash
  # or claude-sonnet
```

- Chat happens frequently — keep it fast and free.
Dreams happen every 15-30 minutes — use a smarter model.

---

## Troubleshooting

### "429 Too Many Requests"
You hit a provider's rate limit.

- Quick fix: Wait for the cooldown period shown in the error.
- Permanent fix:
    - Increase min_interval in config (3-5s for free tiers)
    - Switch to a provider with higher limits
    - Use provider cascade for automatic failover
    - Use Ollama for chat (zero rate limits)

### Dream produces vague topics

- The model is generalizing instead of extracting.

**Symptoms:** "The user works on multiple projects" instead of
"107 registered projects."

**Fix:**

- Use a larger model for dream_llm (70B+, or DeepSeek/Gemini)
- Small models (< 7B) struggle with structured extraction
- The dream prompts include contrastive examples — smarter models
follow them better

### "Unparseable JSON" in dream

- The model returned prose instead of JSON.

**Symptoms:** Dream fails at Consolidate or Prune phase.

**Fix:**

- Set json_mode_supported: true if your provider supports it
- If not, the parser tries to extract JSON from markdown fences
and raw text — but small models may still fail
- Use a larger model for dreams

### Topics are duplicated   

- Two topics contain overlapping information.

**Fix:**

- This self-corrects over time. The Prune phase detects
and removes duplicates. You can also manually delete the duplicate
from .ghost/topics/ and the next dream will rebuild the index.

### Daemon stops unexpectedly

- Check: cat .ghost/daemon.json — shows last tick and state.

**Common causes:**

- Rate limit exhaustion during autoDream
- Provider connection timeout
- System sleep/hibernate

- The daemon saves state after every tick. Restart it and it
resumes from where it left off:

```bash
python ghost.py daemon
```

### Memory seems stale

- Check: ghost status — look at "undreamed entries."

If entries are accumulating but not being dreamed:

- min_new_entries threshold not met (default: 5)
- Provider is rate-limited
- Daemon isn't running

**Manual fix:** `ghost dream` to force a cycle.

---

## Architecture Reference

### File Structure

```text
.ghost/
├── MEMORY.md           # Graph index (Layer 1)
├── GHOST_SPEC.md       # Integration contract
├── topics/             # Knowledge files (Layer 2)
│   ├── co-workspace.md
│   ├── doxascope.md
│   └── ...
├── transcript.jsonl    # Raw log (Layer 3)
├── sources.json        # Linked file registry
├── daemon.json         # KAIROS checkpoint
├── dream_state.json    # Phase-level crash recovery
└── .dream_cursor       # Byte offset of last dreamed entry
```

### Data Flow

```text
Source files ──→ ghost link ──→ sources.json
                                    │
User observations ──→ ghost inject ──→ transcript.jsonl
                                          │
Chat interactions ──→ ghost chat ──→ transcript.jsonl
                                          │
                                    KAIROS daemon
                                     (tick every 120s)
                                          │
                                    4-Phase Dream
                                    Orient → Gather
                                    Consolidate → Prune
                                           │
                                     Context Manager
                                     (Token Budget/Snip)
                                           │
                                 ┌─────────┼─────────┐
                                 ▼         ▼         ▼
                           MEMORY.md  topics/  dream_state
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
               Claude Code   Cursor    Shell scripts
               reads files   reads     read files
```

### Design Principles

- 1. Files are the API. No server required for basic usage.
- 2. Synthesis over retrieval. Dreams rewrite, not index.
- 3. Sources are authoritative. Linked files are read, not copied.
- 4. Verify before trust. Claims checked against filesystem.
- 5. Provider-agnostic. Any LLM. Local or cloud. Free or paid.
- 6. Crash-safe. Append-only transcript, phase-level checkpoints.

---