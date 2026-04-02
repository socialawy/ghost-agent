# Contributing to Ghost

We welcome contributions! Ghost is building a **Shared Memory Standard** for AI agents. Our goal is to move knowledge out of proprietary APIs and into the local filesystem.

## Our Philosophy
- **Unix Philosophy**: Everything is a file. The `.ghost/` directory is the API.
- **Active Synthesis**: We don't just "store" data; we consolidate and verify it.
- **Zero Bloat**: No LangChain, no heavy abstractions. Just pure Python and structured Markdown.

## How to Contribute
1.  **Imrove Synthesis**: Enhance `DreamEngine` in `dream.py` to better reconcile conflicting information.
2.  **Add Verification Gates**: Write new `verify()` methods to check facts against the filesystem.
3.  **Bridge Tools**: Create integrations or specs for new IDEs and agents using the [GHOST_SPEC.md](.ghost/GHOST_SPEC.md).

## Development Checklist
-   **File-Based Only**: Any new feature must store its state in the `.ghost/` directory.
-   **Async Synthesis**: Ensure new logic is compatible with the background `KAIROS` daemon.
-   **Performance**: Keep the memory footprint minimal. Ghost should run on a toaster.

## Style Guide
-   Follow PEP 8.
-   Use descriptive, slug-friendly names for topic files.
-   Keep functions focused and modular.

---

### Recognition
Contributors to Ghost are part of an effort to democratize high-performance agent memory. Thank you for your support.
