# Ghost Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Status: Experimental](https://img.shields.io/badge/status-experimental-orange.svg)]()
[![No GPU Required](https://img.shields.io/badge/GPU-not%20required-green.svg)]()
[![API: Bring Your Own](https://img.shields.io/badge/LLM-bring%20your%20own-purple.svg)]()

**Ghost Agent** is a local, lightweight, API-driven agent harness. It implements the core architectural patterns derived from the March 2026 Claude Code leak: a 3-layer persistent memory system, background "dream" consolidation, and a crash-resilient daemon.

## Why Ghost?
- **Zero GPU Required**: Optimized for external APIs (Groq, Anthropic, OpenAI). Works perfectly on a light machine.
- **Zero Framework Bloat**: No LangChain, no heavy abstractions. Just Python, `requests`, and `pyyaml`.
- **File-Based State**: Your agent's memory is a directory of Markdown and JSONL files. Human-readable, grep-able, and version-controllable.
- **Data Injection**: Seamlessly bulk-load context (like `CO_PM.json` or `BLUEPRINT.md`) into the transcript for the engine to consolidate.
- **Verification Gate**: Ghost doesn't just "hallucinate" file states; it verifies claims against your filesystem before committing them to long-term memory.
- **Anti-Hallucination Logic**: Assistant responses are tagged as `unverified` by default, forcing the engine to corroborate speculation vs. user-provided facts.

---

## 1. Architecture

```text
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
└──────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│              Verification Gate                           │
│  file_exists · file_contains · registry_lookup           │
└──────────────────────────────────────────────────────────┘
```

### The 3-Layer Memory System
1.  **Index (`MEMORY.md`)**: A high-level summary of everything the agent knows. Always injected into the system prompt.
2.  **Topics (`topics/*.md`)**: Detailed knowledge files for specific projects, people, or technical domains.
3.  **Transcript (`transcript.jsonl`)**: An append-only log of every interaction. This is the "raw input" for the Dream Engine.

---

## 2. Quick Start

### Prerequisites
- Python 3.13+
- An API key (Groq is recommended for the free tier, but OpenAI/Anthropic work too).

### Setup
1.  **Clone and install**:
    ```bash
    git clone https://github.com/your-repo/ghost-agent.git
    cd ghost-agent
    pip install -r requirements.txt
    ```
2.  **Configure**:
    Create a `.env` file from the template:
    ```bash
    cp .env.example .env
    # Edit .env and add your GHOST_LLM_API_KEY
    ```
3.  **Initialize**:
    ```bash
    python ghost.py init
    ```

### Usage
- **Chat**: `python ghost.py chat` (Persistent, context-aware loop)
- **Inject**: `python ghost.py inject -f path/to/file.json` (Bulk load context)
- **Dream**: `python ghost.py dream` (Consolidate history into knowledge)
- **Status**: `python ghost.py status` (Memory health and stats)
- **Daemon**: `python ghost.py daemon` (KAIROS process for background autoDream)
- **Recall**: `python ghost.py recall <topic>` (Read specific topic knowledge)

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
