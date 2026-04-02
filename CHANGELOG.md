# Changelog

## [1.1.0] - 2026-04-02

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
