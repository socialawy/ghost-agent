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

## Scaling & High Availability (v1.2+)

Ghost is built to manage massive, high-decibel workspaces without overwhelming LLM context or failing due to API outages.

### 1. Provider Cascade (Hardened)
Configure a list of `providers` in `config.yaml`. Ghost implements a multi-tier failover strategy:
- **Immediate Cascade**: Authentication errors (401/403) trigger an instant switch to the next provider.
- **Retry-then-Cascade**: Rate limits (429) and server errors (5xx) attempt exponential backoff retries before failing over.
- **`ghost ping` (DREAM)**: Added direct testing for the configured Dream Engine provider, including the cascade chain and real-time retry feedback.
- **Hardened Error Parsing**: Robust handling of list-wrapped API error responses (Gemini) and complex retry-after strings (Groq) ensures reliable failover.

### 2. Round-Robin Digestion
Instead of loading every linked file simultaneously—which wastes tokens and risks context fragmentation—Ghost uses a round-robin rotation. Each dream cycle picks **one** high-priority source (stale or changed) to digest, ensuring your entire codebase is refreshed incrementally.

### 3. Topic Auto-Splitting
To maintain high retrieval accuracy, Ghost automatically detects topics that exceed 3,000 characters. These are intelligently split into focused sub-topics with a parent index summary, preventing "knowledge bloat" and keeping LLM focus razor-sharp.

### 4. Concurrent Safe (File Locking)
Ghost uses platform-aware advisory file locking (`msvcrt` on Windows, `fcntl` on Unix). This allows you to run the KAIROS daemon in the background while multiple IDE agents or CLI tools safely append to the transcript simultaneously.

---

## Architecture
```
ghost chat/inject ──→ transcript.jsonl (append-only log)
│
KAIROS daemon (watchman loop)
│
┌────────┴───────────┐
│  The Dream Engine  │
│ (Active Synthesis) │
│ 1. Orient          │──→ What changed?   
│ 2. Gather          │──→ Which sources/topics to load?
│ 3. Synthesize      │──→ Merge + Verify + Reconcile
│ 4. Prune           │──→ Compact interaction logs
└────────┬───────────┘
│
┌────────────┼────────────┐
▼            ▼            ▼
MEMORY.md   topics/*.md  sources.json
(Index)     (Knowledge)  (Linked Files)
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

# Initialize the memory filesystem
python ghost.py init

# Link an external source (registry, project plan, etc.)
python ghost.py link -f path/to/source.md

# Run the 'Hippocampus' (Active Synthesis)
python ghost.py dream

# Interact via standard CLI
python ghost.py chat
```

## Integration Contract: [GHOST_SPEC.md](.ghost/GHOST_SPEC.md)
Ghost provides a formal contract for any AI assistant (Claude Code, Windsurf, Cursor) to read and respect your workspace memory.
Add this to your project's `.claude/instructions.md` or equivalent:
> *Before starting work, read .ghost/MEMORY.md and relevant .ghost/topics/*.md files to understand project context and recent decisions.*

---

## Hardening & Security
Ghost is designed for reliable long-term persistence.
- **Verification Gates**: The engine verifies claims against your filesystem before promoting them to long-term knowledge.
- **Confidence Metadata**: Interactions are tagged as `verified` (user/facts) or `unverified` (assistant speculation), ensuring a clean source of truth.

---

## Contributing
We're building a **standard for agentic memory**, not just a tool. We welcome contributors who align with the Unix philosophy of file-based, minimal frameworks.

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License
MIT - See [LICENSE](LICENSE) for details.
