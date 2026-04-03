## [1.2.0] - 2026-04-03

### Scaling & High Availability
- **Provider Cascade (Hardened)**: Implemented multi-tier failover logic in `llm_client.py`.
    - **Instant Failover**: Authentication failures (401/403) and misconfigurations now trigger an immediate switch to the next backup provider.
    - **Resourceful Retries**: Enhanced `429 (Resource Exhausted)` handling with robust `Retry-After` parsing (supporting Gemini-style list-wrapped JSON and Groq-style strings) and exponential backoff.
- **Round-Robin Digestion**: The Dream Engine now intelligently rotates through linked source files, processing one source per cycle based on priority (changed first, then stale). This prevents LLM context exhaustion on large codebases.
- **Topic Auto-Splitting**: Large topic files (over 3000 characters) are automatically split into focused sub-topics with summaries. Parent topics become indices, maintaining structural clarity and LLM focus.

### Reliability & Concurrent Access
- **Advisory File Locking**: Implemented robust file locking using `msvcrt` (Windows) and `fcntl` (Unix). This allows multiple tools (e.g. Ghost + IDE agents) to safely read and write to the Shared Memory simultaneously without corruption.
- **Resilient Dreaming**: The Dream Engine now persists its state. If a consolidation cycle is interrupted (by rate limits or errors), it will resume from the exact phase it left off during the next run.

### CLI Enhancements
- **`ghost sources`**: List all linked files with their current status (exists/missing) and last-read timestamps.
- **`ghost unlink`**: Easily remove source tracking to keep the focus tight.
- **`ghost ping` (DREAM)**: Added direct testing for the configured Dream Engine provider, including the cascade chain.

## [1.1.0] - 2026-04-02

### Identity & Standards
- **Pivot: Shared Memory Filesystem**: Rebranded Ghost from an "agent harness" to a **Shared Memory Filesystem** standard. The focus is now on the `.ghost/` directory as a universal, file-based API for any AI tool.
- **The Anti-API Advantage**: Formalized the concept of using the filesystem as the interface, eliminating the need for proprietary SDKs and ensuring infinite integration with tools like Claude Code, Cursor, and Windsurf.
- **Hippocampus Model**: Shifted architectural focus from passive retrieval to **Active Synthesis** via the Dream Engine, which distills raw interaction logs into authoritative knowledge.

### Integration
- **`GHOST_SPEC.md`**: Added a machine-readable memory integration contract. This tells any AI agent (Claude Code, Windsurf, Antigravity) how to safely read the `.ghost/` topics for workspace context.
- **`ghost link` Command**: New CLI command to register external files (JSON, CSV, etc.) as **authoritative memory sources**.
- **Daemon Source Monitor**: KAIROS now watches linked source files for `mtime` changes and logs `source_changed` events, which automatically triggers a dream cycle.
- **Direct Source Gathering**: The dream engine reads linked sources directly from disk during consolidation, ensuring structured data is preserved even when the transcript summarization threshold is met.

### Architecture
- **4-Phase Dream Engine**: Replaced single-pass consolidation with
  Orient → Gather → Consolidate → Prune pipeline. Each phase is a
  separate LLM call with a focused prompt. Consolidate now receives
  raw transcript entries (not just Orient summaries) to prevent data loss.
- **Graph-Routed Memory Index**: MEMORY.md now contains a typed node/edge
  graph instead of a flat topic list. Nodes map 1:1 to topic files.
  Edges use specific verb relations (owned_by, uses, tracks).
- **Dual-LLM Support**: Separate `dream_llm` config for consolidation.
  Fast/free model for chat, smarter model for dreams.

### Resilience
- **Rate-Limit Handling**: Custom `RateLimitError` exception with
  `retry_after_seconds`. Parses both standard `Retry-After` header
  and Groq's body-embedded retry timings.
- **API Pacing**: Configurable `min_interval` between calls (default 3s).
  Prevents burst-triggered 429s on free-tier providers.
- **Exponential Backoff**: 4 retries with 3s/6s/12s/24s delays on
  429/5xx errors.
- **`json_mode_supported` Flag**: Gracefully degrades for providers
  that don't support `response_format`.

### Data Fidelity
- **Verbatim Preservation Prompts**: Orient and Consolidate enforce
  exact numbers, names, versions, paths. Contrastive BAD/GOOD examples
  in system prompts.
- **Prune Guards**: Blocks demotion of placeholder text ("not specified").
  Prevents double-append of demotion markers.
- **Confidence Tagging**: Assistant responses tagged `unverified`.
  Injected files tagged `verified` with source filename.

### CLI
- `ghost ping` — Test LLM connectivity, JSON mode, and pacing.
- `ghost inject -f <path>` — Cross-platform file injection.
- `ghost-inject.ps1` — Quick inject from anywhere in workspace.
- Shell command interception in chat mode.

### Daemon
- KAIROS watches configured file paths by mtime.
- `auto_interval_minutes` configurable (default 15 for active work).
- Dream and compact thresholds tunable in config.

## [1.0.0] - 2026-04-01

### Initial Release
- 3-layer memory: MEMORY.md index + topics/*.md + transcript.jsonl
- Single-pass dream consolidation with verification gate
- KAIROS daemon with tick loop and crash-resume checkpoint
- CLI: init, chat, dream, compact, status, recall, inject
- Provider support: OpenAI-compatible (Groq, Ollama, LM Studio) + Anthropic
