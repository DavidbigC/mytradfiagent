# Project Guidelines

## Architecture Reference

Before writing any code, read `structure.md` in the project root. It documents every module, the full request/response flows for both agent and debate modes, all tool files and their data sources, key constants, and common gotchas. Reading it means you will not need to open most source files just to understand how the system fits together.

## Change Log

After completing every task, append a summary to `changes.md` in the project root. Each entry should include:

- **Date** (YYYY-MM-DD)
- **What changed** — brief description of the task
- **Files modified** — list of files created, modified, or deleted
- **Key details** — any important implementation notes, new dependencies, or breaking changes

Format:

```
## YYYY-MM-DD — Short task title

**What:** One-sentence summary of what was done.

**Files:**
- `path/to/file.py` — created / modified / deleted (brief note)

**Details:**
- Bullet points with key implementation details if needed
```

Create `changes.md` if it doesn't exist. Always append — never overwrite previous entries.

make sure you think about how to implement this on a server