---
name: odoo-15
description: Odoo 15 API reference for code, review, and migration work. Covers tree views, category_id groups, _sql_constraints, OWL 1.x, recordset sudo patterns, copy() defaults, multi-company rules, and 15→19 migration deltas. Load before writing or reviewing any Odoo 15 code; do NOT apply Odoo 17+ patterns (list views, privilege_id, models.Constraint, OWL2).
---

# Odoo 15 Reference

Project-local skill for `matia.odoobulut.com` (Odoo 15.0, XML-RPC, no SSH, no staging).
If this skill conflicts with another skill's suggestion, the Odoo 15 rule here wins.
When in doubt about any field/API name, verify with `fields_get` or a small `search_read` before using.

## 1. Views — `tree`, never `list`

- List views are `<tree>`. The `<list>` tag does NOT exist in 15 (it arrived in 16+).
- Editable trees: `<tree editable="top">` / `editable="bottom"`.
- Other view types: `form`, `kanban`, `search`, `graph`, `pivot`, `calendar`, `activity`, `qweb`.
- `widget="numbercall"`, `widget="phone"`, statusbar, `oe_chatter` in form — all valid 15 patterns, do not "modernize" them.

## 2. Security — `category_id`, CSV, record rules

- Groups: `res.groups` with `category_id` (Many2one to `ir.module.category`). `privilege_id` does NOT exist in 15.
- Model ACLs live in `security/ir.model.access.csv`: `id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink`.
- Record rules: `ir.rule` records with `domain_force`, `perm_read/write/create/unlink`, `groups` M2M. Empty groups = global rule.
- Manifest `data` order matters: `security/*.csv` + `security/*.xml` BEFORE `views/*.xml`.

## 3. Constraints — `_sql_constraints`, not classes

- SQL constraints: `_sql_constraints = [('name_uniq', 'unique(name)', 'Message!')]` — list of `(name, sql, message)` tuples.
- Python constraints: `@api.constrains('field')` methods raising `ValidationError`.
- `models.Constraint` / `models.Index` do NOT exist in 15. Do not suggest them.

## 4. ORM essentials

- `self.env['model'].sudo()` on a recordset/model is FINE. What does NOT exist is `self.env.sudo()`.
  Multi-company-safe pattern: `self.with_context(allowed_company_ids=[...], active_test=False).sudo().env`.
- `record.copy(default)` takes a plain dict of overrides. Multi-company phantom-BOM trap:
  `copy(id, {'default': {'company_id': 1}})` instead of relying on `company_id=False`.
- `active_test=False` in context to include archived records; always scope `allowed_company_ids` explicitly (TR=1, US=2 are independent roots).
- Computed fields: `@api.depends`, `store=True` only when needed; `related=` fields are non-stored by default.
- Chatter: inherit `mail.thread`, `mail.activity.mixin`; `tracking=True` on fields.

## 5. Frontend — OWL 1.x

- Odoo 15 ships OWL **1.x** (`@odoo/owl` 1.x API): `Component`, `tags.xml`, `useState`, `onMounted`/`onWillUnmount`, props validation.
- Do NOT use OWL2 patterns: `useService`, `useEffect` dependency semantics, `App`/`mount` from `@odoo/owl` 2.x, `*.xml` template auto-loading conventions from 16+.
- Asset bundles (`web.assets_backend`, `web.assets_frontend`, `web.assets_qweb`) are declared via template `inherit_id` — valid in 15.

## 6. Controllers & routes

- `@http.route('/path', type='http'|'json', auth='public'|'user'|'none', website=True, csrf=...)`.
- Portal ownership MUST be enforced in code (search with partner domain, `AccessError` on mismatch) — never trust an ID from the URL alone.
- `sudo()` in controllers only after an explicit access check, never as a shortcut around record rules.

## 7. Reports (QWeb/PDF)

- `<template id="report_x">` with `t-call="web.html_container"`, paperformat via `report.paperformat` record.
- Keep print-safe inline styles; multi-company logo/address via `res.company` of the record, not `request.env.company` in scheduled jobs.

## 8. Tests

- `TransactionCase`, `SingleTransactionCase`, `HttpCase`; `Form` helper for onchange flows; `tagged('post_install', '-at_install')`.
- Access tests: create users with specific groups, assert `AccessError` where expected.

## 9. Manifest conventions

- `depends`, `data` (ordered: security → data → views → reports → demo), `demo`, `license`, `version`, `installable`, `application`.
- XML IDs: `module_name.record_name`; `noupdate="1"` on `data/noupdate/` records users may edit.

## 10. 15 → 19 migration deltas (for `odoo-migration` planning)

| Odoo 15 (keep) | Odoo 19 (target only) |
|---|---|
| `<tree>` views | `<list>` views |
| `res.groups` `category_id` | `privilege_id` |
| `_sql_constraints` tuples | `models.Constraint` |
| OWL 1.x components | OWL 2 (`useService`, new lifecycle) |
| `@api.constrains` + `ValidationError` | same (stable) |
| `copy(default)` dict | same (stable) |

Never apply the right column while editing 15 code. During migration planning the right column is the goal, the left column is what you will find.

## 11. This project's gotchas (from `docs/discovery.md`)

- Live instance only — XML-RPC via `odoo_matia_*` tools; Python changes need Git Deploy/restart (mesai dışı + backup), `button_immediate_upgrade` does not reload Python.
- Net availability: `avail_qty = quantity - reserved_quantity` on `stock.quant`; NCR locations (TR 333, US 332) excluded.
- Outbound mail (SMTP/OAuth) may be broken — check `mail.mail` exception counts when mail flows misbehave.
- 3745 negative `stock.quant` rows are known; do not move quants 1:1 before count cleanup (migration note).
