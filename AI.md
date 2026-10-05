# AI Instructions - Matia Odoo Hub

Welcome! This project is for AI-assisted Odoo 15 troubleshooting and configuration
(`matia.odoobulut.com` — single live instance, XML-RPC, no SSH, no staging).

To ensure consistent business logic, version-safe API usage, and memory rituals:
👉 **You MUST read and follow the master guidelines file: [AGENTS.md](file:///C:/Users/TKA/Desktop/antigravity/odoo/odoo_matia/AGENTS.md)**

## Codebase Organization Summary

- **`matia_stock_planning/`**: Capacity planning module (models, views, data, security, controllers, static).
- **`scripts/`**: Reusable XML-RPC audit/query scripts + env tooling (`start-opencode.ps1`, `load_env.ps1`, `check_mem0.ps1`, `lint_error_log.ps1`, `setup_new_machine.ps1`).
- **`plans/`**: Implementation plans for larger work (module changes, migration prep).
- **`docs/`**: `discovery.md` is the permanent knowledge store — READ every session, APPEND lasting findings.
- **`scratch/`**: One-off experiments (git-ignored).

## Odoo 15 Safety

Odoo 19 patterns DO NOT apply: no JSON-2 transport, `tree` views (not `list`),
`res.groups` `category_id` (not `privilege_id`), `_sql_constraints` (not `models.Constraint`).
Verify every suspicious field/API with `fields_get` before using. Skill policy in `AGENTS.md`
(`odoo-19` and `odoo-owl` skills are BANNED here).

Please refer to [AGENTS.md](file:///C:/Users/TKA/Desktop/antigravity/odoo/odoo_matia/AGENTS.md) for full layout rules, MCP policy, and operational gotchas.

---

Reference: @AGENTS.md
