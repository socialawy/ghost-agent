## [1.6.0] - 2026-04-04

### Continuous Context Management
- **TOKEN_BUDGET**: `build_context(token_budget=N)` in `memory.py` collapses topics that exceed the character budget into one-line headers (`[COLLAPSED: 1200 chars, /recall topic-name]`). Configurable via `context.token_budget` in `config.yaml`.
- **CONTEXT_COLLAPSE**: Recently referenced topics get priority for full inclusion. `Memory.track_reference()` in `memory.py` records which topics were mentioned in recent turns; stale topics are collapsed first.
- **HISTORY_SNIP**: `DreamEngine.snip_history()` in `dream.py` replaces the blind `messages[-40:]` window. Drops irrelevant early messages based on term overlap with the current turn — keeps relevant history even if old.
- **REACTIVE_COMPACT**: `DreamEngine.micro_compact()` in `dream.py` summarizes the oldest half of transcript entries inline during chat when the list exceeds `max_entries`.
- **CACHED_MICROCOMPACT**: `CompactCache` class in `memory.py` stores `(start, end) → summary` mappings in `.ghost/compact_cache.json` to avoid re-summarizing already-compacted transcript regions.

### Tests
- 22 new tests in `tests/test_context.py` covering CompactCache, topic reference tracking, budget-aware context building, history snipping, and micro-compaction.
- Fixed `test_400_does_not_cascade` → `test_400_cascades_to_next_provider` to match actual cascade behavior in `llm_client.py`.
- **122 tests total.**

---

## [1.5.0] - 2026-04-04

### Multi-Workspace Support
- **MasterIndex**: New `MasterIndex` class in `memory.py` maintains a cross-workspace registry at `~/.ghost/master.json`. Tracks all workspace `.ghost/` directories with existence checking and topic counts.
- **`ghost workspace add <path>`**: Register a workspace in the master index (`ghost.py`).
- **`ghost workspace list`**: Show all registered workspaces with status (ok/missing) and paths (`ghost.py`).
- **`ghost workspace search <query>`**: Full-text search across all workspace `MEMORY.md` and `topics/*.md` files (`ghost.py`).
- **`ghost workspace remove <name>`**: Unregister a workspace (`ghost.py`).
- **Auto-Registration**: KAIROS daemon automatically registers its workspace in the master index on startup (`ghost.py`).

### Tests
- 9 new tests in `tests/test_workspace.py`. **100 tests total** (at time of commit).

---

## [1.4.1] - 2026-04-04

### ULTRAPLAN & Asymmetric Routing
- **`ghost plan <goal>`**: Deep strategic planning offloaded to an expensive model (`ghost.py`). Builds full context from MEMORY.md + topics, sends to a specialized system prompt, and saves the result as a `plan-{slug}.md` topic file.
- **Routing**: Config supports `plan_llm` section for dedicated planning model. Falls back: `plan_llm` → `dream_llm` → `llm` (`ghost.py`).

---

## [1.4.0] - 2026-04-04

### Ghost Bridge — Local HTTP API
- **New file: `bridge.py`** (~240 lines). REST-like HTTP server on `127.0.0.1:7701` using stdlib `http.server` (zero new dependencies).
- **Endpoints**:
  - `GET /health` — health check with version
  - `GET /status` — memory stats JSON
  - `GET /memory` — raw MEMORY.md content
  - `GET /topics` — list of topic slugs
  - `GET /recall/{topic}` — topic file content
  - `POST /inject` — add observation `{"content": "...", "source": "..."}`
  - `POST /chat` — chat with memory context `{"message": "..."}`
  - `POST /dream` — trigger dream cycle, return result
- **`ghost bridge [-p PORT]`**: Standalone HTTP server command (`ghost.py`).
- **Daemon integration**: `daemon.bridge_enabled: true` starts the bridge in a background thread alongside KAIROS (`ghost.py`).
- **Thread-safe**: Dream endpoint uses a threading lock to prevent concurrent consolidation (`bridge.py`).

### Tests
- 15 new tests in `tests/test_bridge.py` (6 unit + 9 HTTP integration with real server). **91 tests total** (at time of commit).

---

## [1.3.0] - 2026-04-04

### Dream Quality Feedback Loop
- **Quality Scoring**: `DreamEngine._score_quality()` in `dream.py` snapshots all topic contents before consolidation. After consolidation, compares length deltas, key term preservation (numbers, proper nouns, file paths), and topic count changes. Warnings surface when data loss is detected (topic shrinkage >30%, deleted topics, lost key terms).
- **`_extract_key_terms()`** in `dream.py`: Static method to extract significant terms (numbers, CamelCase, capitalized words, file paths, slug-style names) for quality comparison.

### `ghost diff`
- **Topic Snapshots**: `TopicStore.snapshot()`, `get_snapshot()`, `list_snapshots()`, `prune_snapshots()` in `memory.py` save topic files to `.ghost/dream_history/cycle_N/` after each dream. Keeps last 5 cycles (configurable).
- **`ghost diff [--cycle N]`**: New CLI command in `ghost.py` using `difflib.unified_diff` with colored terminal output (green/red for additions/removals).

### Cross-Project Graph Edges
- **`DreamEngine._cross_link_graph()`** in `dream.py`: After each dream, detects topic pairs sharing 3+ significant terms via heuristic co-occurrence analysis. Adds relationship edges to MEMORY.md `### Edges` section. No extra LLM call — pure text matching.

### Tests
- 14 new tests in `tests/test_dream.py` covering quality scoring, key term extraction, cross-link graph, and topic snapshots. **76 tests total** (at time of commit).

---

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
