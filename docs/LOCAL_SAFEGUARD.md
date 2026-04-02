# Local Safeguard: Private Context Hook

Ghost Agent is designed to be a "Second Brain," and sometimes the most valuable research (blueprints, leaked source analysis, or project maps) is too personal or sensitive to be pushed to a public remote like GitHub.

To enable **Local-Only Tracking** for the `local-files/` directory, we have implemented a Git safeguard.

## How it Works

We use a Git `pre-push` hook located at `.git/hooks/pre-push`. 

Every time you run `git push`, this script:
1.  Scans the commits you are about to push.
2.  Checks for any file modifications inside the `local-files/` directory.
3.  If detected, the **Push is ABORTED** and a warning is displayed.

## Why this is useful
-   **Local Versioning**: You can `git commit` changes to `BLUEPRINT.md` or `CO_PM.json` locally. This gives you undo/redo support and a history of your thoughts.
-   **Safety**: You don't have to worry about `git add .` or `git commit -a` accidentally leaking your private blueprints to the remote.

## How to Bypass (Use Caution!)
If you **intentionally** want to push these files to the remote, you can skip the check using the `--no-verify` flag:
```bash
git push --no-verify
```

> [!CAUTION]
> This hook only exists on your local machine. If you clone this repository to another machine, you must recreate the hook (`.git/hooks/pre-push`) to maintain the safeguard.
