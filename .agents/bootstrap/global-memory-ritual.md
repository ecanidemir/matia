<!-- ODOO-HUB-MEMORY-RITUAL-START (scripts/setup_new_machine.ps1 yönetir, elle silme) -->

## Memory & Error Logging (MANDATORY, non-skippable)

Every session with Mem0 available MUST follow this ritual — it is not optional:

1. **Recall:** on session start and before debugging any error, run `search_memories` with the task/error fingerprint and read the project's `.agents/memory/HOT.md` if present.
2. **Log:** after fixing ANY dev error (code, SSH, MCP, user-pasted traceback), write 1-2 lines max: `fingerprint | root cause -> fix`. Dual-write: `add_memory` (scope `project` default, `global` only for tool-generic lessons) + append to `.agents/memory/errors-log.md`.
3. **Promote:** an error recurring 3+ times goes to `HOT.md` (≤30 lines, 30-day expiry).
4. **Never log secrets:** no passwords, API keys, or key material — in Mem0 or files.

Load the `error-memory` skill whenever an error is fixed or a repeated failure is diagnosed. Mem0 default scope is `project`; pass scope `global` to the `log_error` tool (or `/log-error`) only for cross-repo lessons.

<!-- ODOO-HUB-MEMORY-RITUAL-END -->
