# Ghost Agent 👻
> **The Shared Memory Filesystem for AI Agents.**
> Ghost is a local, continuously synthesizing "second brain" inspired by the [March 2026 Claude Code leaks](local-files/BLUEPRINT.md). It turns your LLM from a stateful chat into a long-context, self-maintaining agent that never forgets your project's scale.

> [!IMPORTANT]
> **Ghost is not an orchestrator; it is a shared memory standard.** By making the filesystem the API, Ghost achieves infinite, friction-less integration with any tool—Claude Code, Cursor, Windsurf, or a basic shell script.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Status: Experimental](https://img.shields.io/badge/status-experimental-orange.svg)]()
[![No GPU Required](https://img.shields.io/badge/GPU-not%20required-green.svg)]()

## Why Ghost?

### 1. The Anti-API Advantage
Modern AI memory systems (Zep, MemGPT, etc.) trap knowledge behind their own abstraction layers and SDKs. Ghost aligns with the **Unix Philosophy**: *Everything is a file.*
By formalizing the memory directory in [GHOST_SPEC.md](.ghost/GHOST_SPEC.md), we've made the filesystem the universal interface. Any tool that can `cat` a file can now use Ghost's knowledge.

### 2. The Hippocampus Model (Synthesis vs. Retrieval)
Vector DBs are "semantic garbage dumps"—they retrieve exact fragments but never truly *learn* or reconcile data.
Ghost's **Dream Engine** acts as an active synthesizer. It doesn't just index; it reads raw interaction logs (`transcript.jsonl`) and distills them into structured, authoritative markdown (`topics/*.md`) on a schedule.

### 3. File-Linked Memory
Ghost can "link" to external source files (like project registries or blueprints) without copying them. It monitors these files for changes and automatically incorporates them into its long-term state.

---

## Features

### Scaling & High Availability (v1.2+)
- **Provider Cascade**: Multi-tier failover (`llm.providers` or `dream_llm.providers`). Auth errors cascade immediately; rate limits retry then cascade. Parses Gemini/Groq error formats.
- **Proxy-Safe Defaults**: Providers ignore shell proxy environment variables by default unless `trust_env: true` is set. This avoids false "provider unreachable" failures caused by broken desktop proxy settings.
- **Round-Robin Digestion**: Processes one linked source per dream cycle, rotating by priority (changed → stale). Prevents context overflow.
- **Topic Auto-Splitting**: Topics over 3,000 chars are split into focused sub-topics with parent summaries.
- **File Locking**: Platform-aware advisory locks (`msvcrt`/`fcntl`) for safe concurrent access.
- **Safe Resume**: Saved `dream_state.json` is resumed only when it is recent and structurally valid. Stale or unsafe recovery state is discarded instead of being allowed to damage memory.
- **Conservative Prune**: Topic deletion is scoped to the topics touched by the current dream. Ghost now prefers preserving standalone project knowledge over opportunistic cleanup.

### Dream Quality & Feedback (v1.3+)
- **Quality Scoring**: Compares topics before/after each dream — detects shrinkage, lost key terms, deleted topics.
- **`ghost diff`**: Shows unified diff of what changed in the last dream cycle. Keeps 5 snapshots.
- **Cross-Project Graph Edges**: Automatically detects topic relationships via term co-occurrence.

### Ghost Bridge — HTTP API (v1.4+)
- Local REST API on `127.0.0.1:7701` — any tool that can `curl` can feed Ghost.
- `GET /health /status /memory /topics /recall/{topic}`
- `POST /inject /chat /dream`
- Embeddable in KAIROS daemon via `daemon.bridge_enabled: true`.

### ULTRAPLAN (v1.4.1+)
- `ghost plan <goal>` — deep strategic planning offloaded to expensive model.
- Asymmetric routing: `plan_llm` → `dream_llm` → `llm` fallback chain.
- Plans saved as topic files for future reference.

### Multi-Workspace (v1.5+)
- Master index at `~/.ghost/master.json` tracks multiple workspace `.ghost/` directories.
- `ghost workspace add/list/search/remove` — register, browse, and cross-workspace text search.
- KAIROS auto-registers on startup.

### Continuous Context Management (v1.6+)
- **TOKEN_BUDGET**: `context.token_budget` in config collapses overflow topics to one-line headers.
- **CONTEXT_COLLAPSE**: Recently referenced topics stay expanded; stale topics collapse first.
- **HISTORY_SNIP**: Smart conversation windowing — drops irrelevant early messages, keeps relevant ones.
- **MICRO_COMPACT**: Summarizes oldest transcript entries inline when they exceed budget.
- **CACHED_MICROCOMPACT**: Caches compacted regions to avoid re-summarizing.

---

## Architecture
```
ghost chat/inject ──→ transcript.jsonl (append-only log)
│
KAIROS daemon (watchman loop)
│
┌────────┴───────────┐
│  The Dream Engine  │        Ghost Bridge (HTTP :7701)
│ (Active Synthesis) │        ├─ GET  /status /memory /topics /recall/{t}
│ 1. Orient          │──→ What changed?
│ 2. Gather          │──→ Which sources/topics to load?
│ 3. Consolidate     │──→ Merge + Verify + Reconcile
│ 4. Prune           │──→ Demote stale, compact
│ 4.5 Quality Score  │──→ Detect data loss
│ 4.6 Cross-Link     │──→ Heuristic graph edges
└────────┬───────────┘        ├─ POST /inject /chat /dream
         │                    └─ curl → any tool feeds Ghost
┌────────┼──────────────┐
▼        ▼              ▼
MEMORY.md  topics/*.md  sources.json
(Index)    (Knowledge)  (Linked Files)
         │
    ~/.ghost/master.json ──→ Multi-workspace registry
```

### The 3-Layer Memory System
1.  **Index (`MEMORY.md`)**: A graph-indexed summary of the entire workspace.
2.  **Topics (`topics/*.md`)**: Detailed, distilled knowledge files per domain.
3.  **Transcript (`transcript.jsonl`)**: The "short-term memory" log of interactions.

---

## Quick Start
```bash
pip install -r requirements.txt
cp config.yaml.example config.yaml
cp .env.example .env
# Edit both with your API keys

# Initialize the memory filesystem
python ghost.py init

# Test LLM connectivity
python ghost.py ping

# Link an external source (registry, project plan, etc.)
python ghost.py link path/to/source.md

# Run the dream engine (Active Synthesis)
python ghost.py dream

# See what changed
python ghost.py diff

# Interactive chat with persistent memory
python ghost.py chat

# Start the HTTP API (any tool can curl)
python ghost.py bridge

# Deep strategic planning
python ghost.py plan "migrate auth to OAuth2"

# Multi-workspace management
python ghost.py workspace add /path/to/project
python ghost.py workspace search "authentication"

# Always-on daemon (dreams + watches + optional bridge)
python ghost.py daemon
```

### Recommended Resilient Routing
```yaml
llm:
  providers:
    - provider: "openai"
      base_url: "http://localhost:11434/v1"
      api_key: "ollama"
      model: "phi4-mini"
      min_interval: 0
      json_mode_supported: false
      trust_env: false
    - provider: "openai"
      base_url: "https://api.groq.com/openai/v1"
      api_key: "${GROQ_API_KEY}"
      model: "llama-3.3-70b-versatile"
      min_interval: 1.0
      json_mode_supported: true
      trust_env: false
    - provider: "openai"
      base_url: "https://api.deepseek.com/v1"
      api_key: "${DEEPSEEK_API_KEY}"
      model: "deepseek-chat"
      min_interval: 2.0
      json_mode_supported: true
      trust_env: false

dream_llm:
  providers:
    - provider: "openai"
      base_url: "https://generativelanguage.googleapis.com/v1beta/openai"
      api_key: "${GEMINI_API_KEY}"
      model: "gemini-2.0-flash"
      min_interval: 2.0
      json_mode_supported: true
      trust_env: false
    - provider: "openai"
      base_url: "https://api.openai.com/v1"
      api_key: "${OPENAI_API_KEY}"
      model: "gpt-4.1-mini"
      min_interval: 2.0
      json_mode_supported: true
      trust_env: false
```

Ghost will try providers in order. For local models, make sure the local server is actually running before expecting the first hop to succeed.

### Operator Note
The first real Ghost operator run exposed a live regression: a resumed dream plus global prune could delete valid leaf topics like `prim-1-math`. Ghost now treats resume and prune as safety-critical paths:
- resume is validated before use
- prune is scoped to touched topics
- destructive deletions are rolled back if quality checks detect data loss
- `ghost status` surfaces when a saved dream state is pending

## Integration Contract: [GHOST_SPEC.md](.ghost/GHOST_SPEC.md)
Ghost provides a formal contract for any AI assistant (Claude Code, Windsurf, Cursor) to read and respect your workspace memory.
Add this to your project's `.claude/instructions.md` or equivalent:
> *Before starting work, read .ghost/MEMORY.md and relevant .ghost/topics/*.md files to understand project context and recent decisions.*

---

## Hardening & Security
Ghost is designed for reliable long-term persistence.
- **Verification Gates**: The engine verifies claims against your filesystem before promoting them to long-term knowledge.
- **Confidence Metadata**: Interactions are tagged as `verified` (user/facts) or `unverified` (assistant speculation), ensuring a clean source of truth.
- **Proxy Isolation**: By default, provider requests do not inherit shell proxy env vars. Set `trust_env: true` per provider only if you intentionally need a corporate or local proxy.
- **Recovery Guardrails**: KAIROS validates saved dream state on startup and logs whether it will resume or discard it.
- **Memory Preservation First**: Topic removals must survive local validation and quality scoring; Ghost now defaults to keeping knowledge unless redundancy is clearly proven.
- **128 Tests**: Comprehensive test suite covering memory, dream engine, prune/resume safety, LLM cascade, bridge HTTP, multi-workspace, and context management.

---

## Contributing
We're building a **standard for agentic memory**, not just a tool. We welcome contributors who align with the Unix philosophy of file-based, minimal frameworks.

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License
MIT - See [LICENSE](LICENSE) for details.
