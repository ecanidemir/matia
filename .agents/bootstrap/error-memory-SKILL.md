---
name: error-memory
description: Any dev error (code, SSH, MCP, pasted traceback) gets logged in 1-2 lines with root cause to Mem0 + project error log, and HOT.md is checked first. Use whenever an error is fixed or a repeated failure is diagnosed.
---

# Error Memory (Global)

Two-layer ritual. Project files live at `.agents/memory/` (HOT.md = promoted patterns, errors-log.md = raw log).

## 1. Recall first (before fixing)

- Read `.agents/memory/HOT.md` if the project has one (max ~30 lines, cheap).
- Mem0 semantic search: `search_memories` with the error fingerprint (e.g. `WinError 10061 odoo MCP`, `company_id phantom BOM copy`, `odoo_matia empty env`).
- If a match exists → apply the known fix first, do not re-derive from scratch.

## 2. Log after fixing (max 2 lines per error)

Write to BOTH, briefly:

**a) Project file** — append one line to `.agents/memory/errors-log.md`:

```
YYYY-MM-DD | fingerprint (tool + symptom, e.g. odoo_matia/empty env) | root cause -> fix
```

Rules: no pasted traceback, no secrets (`ODOO_PASSWORD`, API keys, key material NEVER logged). Same fingerprint twice = update count, 3rd repeat → promote to HOT.md.

**b) Mem0** — `add_memory` with scope:

- `project` (default): repo-specific (Odoo 15 quirks, odoobulut paths, multi-company bugs).
- `global`: only for tool-generic lessons valid in every repo (e.g. `uvx` cache clear, PowerShell quoting). Prefer `project`.

Text format: `fingerprint | cause -> fix` (one sentence).

## 3. Promote (3x rule)

An error seen 3+ times moves to `.agents/memory/HOT.md` as one line. HOT.md stays ≤30 lines; drop stale entries older than 30 days.

## 4. Mem0 401 triage (don't blame the key first)

1. Run `powershell -File scripts/check_mem0.ps1` (read-only, prints only HTTP codes).
2. Exit 2 = key missing from opencode process env → start opencode via `scripts/start-opencode.ps1` (direct `opencode` command never loads workspace `.env`).
3. Exit 1 = key genuinely invalid → rotate at the Mem0 dashboard (only then).
4. Hand-rolled Mem0 REST must use trailing slashes (`/v1/memories/search/`); slash-less paths 301-redirect and drop the auth header, producing a bogus 401.

## 5. Secret-safe commands

Never embed `$env:SECRET` inside a double-quoted `-Command "..."` (outer shell expands it into error output). Use `cmd /c "(set VAR= && ...)"` for env-clear tests. A leaked key is rotated immediately.
