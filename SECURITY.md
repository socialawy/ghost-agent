# Security Policy

## API Keys
Ghost Agent calls external LLM APIs. Your keys live in `.env` (never committed).
The `.ghost/` state directory may contain conversation content — treat it like 
a diary. Don't push it to public repos.

## Filesystem Access
The verification gate performs **read-only** access to your workspace.
Ghost never writes outside `.ghost/` unless you explicitly extend it.
The daemon watches files by mtime only — no content is read during watch ticks.

## Reporting
Open a GitHub issue or email [EMAIL_ADDRESS] for security concerns.