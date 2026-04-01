# Contributing to Ghost Agent

We welcome contributions! Ghost is a community-driven, clean-room implementation of advanced agentic architecture.

## How to Contribute
1.  **Bug Reports**: If you find a crash or a memory corruption issue, please open a GitHub issue.
2.  **Feature Requests**: Want to add a new verification gate or a bridge for a specific IDE? Open a discussion or an issue.
3.  **Pull Requests**:
    -   Keep it lightweight. Ghost's philosophy is "Minimal framework, maximum logic."
    -   Ensure any new features are file-based and daemon-aware.
    -   Don't add large dependencies unless absolutely necessary.

## Development Checklist
-   **Add tools**: Modify `DreamEngine` in `dream.py` to add new `verify()` capabilities.
-   **Improve Memory**: Extend `Memory` in `memory.py` for advanced retrieval (e.g., embeddings).
-   **Daemon Features**: Update `KairosDaemon` in `ghost.py` for more sophisticated file matching or webhook integration.

## Style Guide
-   Follow PEP 8.
-   Keep functions focused and modular.
-   Use descriptive names for topic slugs.

---

### Recognition
Contributors to Ghost Agent are part of a clean-room effort to democratize high-performance agent harnesses. Thank you for your help.
