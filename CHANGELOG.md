# Changelog

All notable changes to **Ghost Agent** will be documented in this file.

## [1.1.0] - 2026-04-01

### Added
- **UI: Standardized ASCII Boxes**: New `_print_box` utility ensures all CLI tables (status, chat, init) have consistent borders, centering, and truncation.
- **CLI: `inject --file` flag**: Support for `-f` or `--file` in the `inject` command for cleaner, cross-platform context loading.
- **Anti-Hallucination: Confidence Tags**: Assistant responses are now tagged with `confidence: unverified`, and user-injected data with `confidence: verified`.
- **Anti-Hallucination: Rule 7**: Updated the Dream Engine to treat unverified entries as speculation, preventing LLM hallucinations from corrupting topic memory.

### Fixed
- **CLI: Shell Interception**: The chat loop now intercepts shell-like commands (e.g., `python ghost`, `git `, `ls `) to prevent user/LLM confusion.
- **Git: Security Hardening**: Ensured `config.yaml` is untracked and correctly ignored by Git.

## [1.0.0] - 2026-04-01

### Added
- **Core Architecture**: Initial implementation of the 3-layer persistent memory (Index, Topics, Transcript).
- **autoDream Engine**: Background consolidation logic with file verification and compaction.
- **KAIROS Daemon**: Always-on daemon with tick-based processing, file watching, and crash recovery.
- **Unified LLM Client**: Support for OpenAI-compatible (Groq, Ollama) and Anthropic APIs.
- **GitHub Readiness**: Standardized community healthy files (`LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`).
- **Environment Security**: Added `.env` support and `.env.example` template.
- **CLI Interface**: Robust command-set for `init`, `chat`, `dream`, `status`, `daemon`, and more.

### Fixed
- Fixed context entropy via transcript compaction.
- Improved crash resilience with `daemon.json` checkpointing.
- Secured secret management by moving API keys out of tracked `config.yaml`.

---
*Inspired by the 2026 Claude Code Architecture.*
