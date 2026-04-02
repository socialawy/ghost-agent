# Security Policy

## Persistence & Privacy
Ghost is a **Shared Memory Filesystem**. Your data lives locally on your disk.
- **API Keys**: Keys reside in your `.env` file and are never committed or logged.
- **State Directory**: The `.ghost/` directory contains your project's synthesized knowledge and interaction history. Treat it like a secure diary; **do not push it to public repositories.**

## Filesystem Access
- **Verification Gate**: Performs **read-only** access to your workspace to verify memory claims against the truth of your code.
- **Memory Boundary**: Ghost never writes outside the `.ghost/` directory.
- **Daemon Monitoring**: The KAIROS daemon monitors file `mtime` only. Content is only read during the "Gather" phase of the Dream Engine if a file has changed.

## Reporting
Please report security concerns via a GitHub Issue or private email.