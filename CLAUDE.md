# CLAUDE.md - Matia Odoo Hub

This repository is for AI-assisted Odoo 15 troubleshooting and configuration
(`matia.odoobulut.com` — single live instance, XML-RPC, no SSH, no staging).

To ensure consistent logic, version-safe API usage, and proper environment workflows:
👉 **You MUST read and follow the master guidelines file: [AGENTS.md](file:///C:/Users/TKA/Desktop/antigravity/odoo/odoo_matia/AGENTS.md)**

## Key Directives

1. Refer to [AGENTS.md](file:///C:/Users/TKA/Desktop/antigravity/odoo/odoo_matia/AGENTS.md) for full directory mappings and skill policy.
2. Follow `.agents/workflows/diagnose_flow.md` for every question/bug (recall → read-only query → analyze → document → memory flush).
3. Connect to Odoo 15 via `odoo_matia_*` MCP tools; verify suspicious fields with `fields_get`.
4. Do NOT use Odoo 19 patterns (`list` views, `privilege_id`, JSON-2, Constraint/Index) or the `odoo-19`/`odoo-owl` skills.
5. Keep audit scripts inside `scripts/`, one-off experiments inside `scratch/`, lasting findings in `docs/discovery.md`.
6. Respect live-DB rules: read first, ask before writes (no staging).

---

Reference: @AGENTS.md
