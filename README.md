# Ghost Agent 👻
> **TL;DR:** A persistent, clean-room memory harness inspired by the [March 2026 Claude Code leaks](local-files/BLUEPRINT.md). It turns your LLM from a stateful chat into a long-context, self-maintaining agent that never forgets your project's scale.

> [!IMPORTANT]
> **This is not just another wrapper.** Ghost implements a 3-layer memory architecture (Index → Topics → Transcript) and an autonomous **Dream Engine** that consolidates, verifies, and prunes context while you sleep.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Status: Experimental](https://img.shields.io/badge/status-experimental-orange.svg)]()
[![No GPU Required](https://img.shields.io/badge/GPU-not%20required-green.svg)]()
[![API: Bring Your Own](https://img.shields.io/badge/LLM-bring%20your%20own-purple.svg)]()

**Ghost Agent** is a local, lightweight, API-driven agent harness. It implements the core architectural patterns derived from the March 2026 Claude Code leak: a 3-layer persistent memory system, background "dream" consolidation, and a crash-resilient daemon.

### TL;DR
- 🎯 **Objective**: Reliable long-term persistence in complex workspaces.
- 🧠 **Architecture**: 3-layer memory (Index → Topics → Transcript).
- 🛡️ **Hardened**: Active shell interception and verification gates to kill hallucinations.
- ⚡ **Zero Bloat**: No LangChain, no heavy abstractions. Just Python, `requests`, and `pyyaml`.

## Why Ghost?
- **Zero GPU Required**: Optimized for external APIs (Groq, Anthropic, OpenAI). Works perfectly on a light machine.
- **Zero Framework Bloat**: No LangChain, no heavy abstractions. Just Python, `requests`, and `pyyaml`.
- **File-Based State**: Your agent's memory is a directory of Markdown and JSONL files. Human-readable, grep-able, and version-controllable.
- **File-Linked Memory**: Ghost can track external source files (like `BLUEPRINT.md` or `REPORTS.csv`) without copying them, reading them only when they change.
- **Verification Gate**: Ghost doesn't just "hallucinate" file states; it verifies claims against your filesystem before committing them to long-term memory.
- **Anti-Hallucination Logic**: Assistant responses are tagged as `unverified` by default, forcing the engine to corroborate speculation vs. user-provided facts.

---

## Architecture
```
ghost chat/inject ──→ transcript.jsonl (append-only log)
│
KAIROS daemon (tick loop)
│
┌──────┴─────────┐
│ autoDream      │
│ 4 phases:      │
│ 1. Orient      │──→ What changed?
│ 2. Gather      │──→ Which topics to load?
│ 3. Consolidate |──→ Merge + verify
│ 4. Prune       │──→ Clean stale data
└──────┬─────────┘
│
┌────────────┼────────────┐
▼            ▼            ▼
MEMORY.md   topics/*.md  daemon.json
(graph index) (knowledge) (checkpoint)
```

### The 3-Layer Memory System
1.  **Index (`MEMORY.md`)**: A high-level summary of everything the agent knows. Always injected into the system prompt.
2.  **Topics (`topics/*.md`)**: Detailed knowledge files for specific projects, people, or technical domains.
3.  **Transcript (`transcript.jsonl`)**: An append-only log of every interaction. This is the "raw input" for the Dream Engine.

---

## Quick Start

```bash
pip install -r requirements.txt  # requests, pyyaml, python-dotenv
cp config.yaml.example config.yaml
cp .env.example .env
# Edit config.yaml with your provider (Groq free tier works)

python ghost.py init
python ghost.py ping              # Verify connectivity
python ghost.py link -f path/to/file.md  # Track external source natively
python ghost.py inject -f your-context.json
python ghost.py dream             # 4-phase consolidation
python ghost.py chat              # Interactive with memory
python ghost.py daemon            # Always-on background agent
```

## Provider Support
| Provider | Cost | Rate Limits | Config |
| :--- | :--- | :--- | :--- |
| **Groq** | Free | 30 req/min, daily token cap | `min_interval: 3.0` |
| **Ollama** | Free | None (local) | `min_interval: 0` |
| **LM Studio** | Free | None (local) | `min_interval: 0` |
| **OpenAI** | Paid | Generous | `min_interval: 0` |
| **Anthropic** | Paid | Generous | `min_interval: 0` |

---

## 3. The Dream Engine (autoDream)
The Dream Engine is the background process that tidies up the agent's mind. It:
1.  Reads new entries from the `transcript.jsonl`.
2.  Identifies new facts, corrected decisions, or project updates.
3.  **Verifies** those facts (e.g., checking if a file actually exists).
4.  **Corroborates Speculation**: Treats `unverified` assistant responses as speculation and only promotes them if verified by file system checks or cross-referenced with user messages.
5.  Updates the `topics/` files and the `MEMORY.md` index.
6.  Compacts the transcript to keep context windows clean.

---

## 4. Hardening & Security
Ghost is designed for reliable long-term persistence in complex workspaces.

### Shell Interception
To prevent the agent from hallucinating CLI command execution, the chat loop intercepts common commands (e.g., `git`, `python ghost`, `ls`) and warns the user. This ensures the transcript remains a clean record of conversation rather than fake command output.

### Confidence Metadata
Entries in the `transcript.jsonl` are tagged with confidence levels:
- `verified`: Manually injected text or explicit user instructions.
- `unverified`: Assistant responses that require verification before being stored as permanent knowledge.

---

## 5. Contributing
Ghost is designed to be hackable. Want to add a new verification tool? Check out `dream.py`. Want to plug in a new LLM provider? See `llm_client.py`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## 6. License
MIT - See [LICENSE](LICENSE) for details.
