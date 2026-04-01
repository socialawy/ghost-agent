# MEMORY/DREAM for AGENTS

**Briefing**

Fresh information from April 1 2026 about a major Anthropic event that happened.

On March 31 2026, Anthropic accidentally published a 59.8 MB source-map file (`cli.js.map`) inside their official npm package `@anthropic-ai/claude-code@2.1.88`. This file contained the **complete unobfuscated TypeScript source** of their flagship Claude Code agent harness — 512,000+ lines across ~1,900 files.

Anthropic issued DMCA takedowns on direct mirrors, but the community immediately created clean-room rewrites. The leading one is **claw-code** (https://github.com/instructkr/claw-code), now the fastest-growing GitHub repo in history (110k stars in ~24 hours). It started as a Python clean-room reimplementation and is now heavily focused on a Rust port.

The truly valuable part is **not** the model weights (which were never leaked), but the **agent harness architecture** — especially the memory system, background orchestration, and long-running reliability patterns. These are the parts Anthropic treated as their real “moat”.

Key elements revealed (directly relevant to what we want to build locally):

1. **Multi-layer self-healing memory**  
   - Lightweight index (MEMORY.md style) + topic-specific files + full append-only transcript (hidden from the main context).  
   - Strict “write discipline”: the agent only trusts changes it has verified against real files.  
   - Automatic compaction to prevent context entropy.

2. **autoDream**  
   - When idle, it forks a background sub-agent that:  
     - Merges observations  
     - Resolves contradictions  
     - Turns tentative ideas into verified facts  
     - Runs read-only bash access for self-inspection  
   - This is the “context dream” mechanism — the agent literally cleans and consolidates its own memory in the background.

3. **KAIROS mode**  
   - Fully autonomous always-on daemon.  
   - Uses `<tick>` prompts, GitHub webhook subscriptions, append-only logs.  
   - Keeps working proactively even while the user is offline, resumes exactly where it left off.

4. **ULTRAPLAN** (bonus)  
   - Offloads deep planning to a remote Opus 4.6 instance with up to 30 minutes of uninterrupted thinking time.

Other notable patterns: prompt-cache-aware boundaries, modular tool plugins (~40 tools), permission-gated execution, and multi-agent orchestration done purely via structured prompts (no external framework).

**Idea:**  
Using only the patterns above (and the public claw-code Python/Rust code as reference if needed), that should be enough to design a **local, lightweight, API-driven version** of this memory/context dream system. No need for a strong GPU, it can run on ordinary hardware and call external LLM APIs (any model, including any model, chat if it can be bridged).

## Goal:
- Persistent disk-based memory (3-layer style)
- Background autoDream consolidation loop
- KAIROS-style daemon that can run 24/7 and resume
- Strict verification-before-write
- Simple CLI or Python script I can run locally today

