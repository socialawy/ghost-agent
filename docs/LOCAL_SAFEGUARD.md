# Local Safeguard: Private Context Hook

Ghost is a **Shared Memory Filesystem**, and often the most valuable synthesized knowledge (blueprints, project maps, or private registries) is too sensitive for public remotes.

To enable **Local-Only Tracking** for the `local-files/` and `.ghost/` directories, we use a Git safeguard to ensure your private "second brain" stays on your machine.

## How it Works

We use a Git `pre-push` hook located at `.git/hooks/pre-push`. 

Every time you run `git push`, this script:
1.  Scans the commits you are about to push.
2.  Checks for any modifications inside the `local-files/` directory.
3.  If detected, the **Push is ABORTED** and a warning is displayed.

## Why this is useful
-   **Local Synthesis**: You can commit changes to `BLUEPRINT.md` or `CO_PM.json` locally, giving you full undo/redo support and a persistent history of your thoughts.
-   **Safety**: Even if you `git add .` or `git commit -a`, the safeguard prevents you from accidentally leaking your private knowledge to the remote.
-   **Standardized Separation**: By keeping `.ghost/` and `local-files/` separate from the core logic, we maintain a clean boundary between the "standard" and your specific "context".

## How to Bypass (Use Caution!)
If you **intentionally** want to push these files to the remote, you can skip the check:
```bash
git push --no-verify
```

> [!CAUTION]
> This hook is local to your machine. If you clone this repository elsewhere, you must recreate the hook (`.git/hooks/pre-push`) to maintain the safeguard.
