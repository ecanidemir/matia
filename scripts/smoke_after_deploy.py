"""Deploy smoke test: detect code-vs-DB schema drift after Git Deploy+restart.

Catches the 'Internal Server Error everywhere' class of outage where new
Python code (registry) references stored fields whose DB columns were
never created because the module Upgrade step was skipped.

Read-only. Credentials ONLY from process env. Without flags it uses the
prod vars (ODOO_URL/ODOO_DB/ODOO_USERNAME/ODOO_PASSWORD); with --staging
it uses ODOO_STAGING_URL/ODOO_STAGING_DB/ODOO_STAGING_USERNAME/
ODOO_STAGING_PASSWORD. Never prints secrets.

Usage:
    python scripts/smoke_after_deploy.py [--staging]
Exit: 0 = green, 1 = env/auth failure, 2 = DRIFT DETECTED (run Upgrade).
"""
import os
import sys
import xmlrpc.client

MODULE_NAME = "matia_stock_planning"
# (model, field) pairs current main-branch code requires. NOTE: res.users
# matia_capacity_targets was REVERTED (commit 4905308) after it caused a
# total staging outage — it must NOT be listed here.
REQUIRED_FIELDS = [
    ("matia.procurement.plan.line", "retained_total_usd"),
]


def fail(msg):
    print("SMOKE-FAIL: %s" % msg)
    return 2


def main():
    prefix = "ODOO_STAGING_" if "--staging" in sys.argv[1:] else "ODOO_"
    url = os.environ.get(prefix + "URL", "").rstrip("/")
    db = os.environ.get(prefix + "DB", "")
    user = os.environ.get(prefix + "USERNAME", "")
    pw = os.environ.get(prefix + "PASSWORD", "")
    if not all([url, db, user, pw]):
        print("SMOKE-ERROR: missing %sURL/%sDB/%sUSERNAME/%sPASSWORD"
              % (prefix, prefix, prefix, prefix))
        return 1
    print("SMOKE: target instance %s" % url)
    common = xmlrpc.client.ServerProxy("%s/xmlrpc/2/common" % url)
    try:
        uid = common.authenticate(db, user, pw, {})
    except Exception as e:
        print("SMOKE-ERROR: auth exception %s: %s" % (type(e).__name__, e))
        return 1
    if not uid:
        print("SMOKE-ERROR: authentication failed")
        return 1
    models = xmlrpc.client.ServerProxy("%s/xmlrpc/2/object" % url)

    def search_read(model, domain, fields, limit=10):
        return models.execute_kw(db, uid, pw, model, "search_read",
                                 [domain], {"fields": fields, "limit": limit})

    mods = search_read("ir.module.module",
                       [["name", "=", MODULE_NAME]], ["state"], limit=1)
    if not mods:
        return fail("module %s not found" % MODULE_NAME)
    if mods[0]["state"] != "installed":
        return fail("module state=%s (expected installed — run Upgrade)"
                    % mods[0]["state"])

    missing = []
    for model, fname in REQUIRED_FIELDS:
        # NOTE: ir.model.fields 'model' is a non-stored related field and
        # cannot be trusted in search domains; use the stored dotted path.
        hits = search_read("ir.model.fields",
                           [["model_id.model", "=", model],
                            ["name", "=", fname]],
                           ["name"], limit=1)
        if not hits:
            missing.append("%s.%s" % (model, fname))
    if missing:
        return fail("missing field records (Upgrade not run?): %s"
                    % ", ".join(missing))

    try:
        probe = search_read("res.users", [], ["display_name"], limit=1)
        if not probe:
            return fail("res.users probe returned no rows")
    except Exception as e:
        return fail("res.users read crashed (%s: %s) — classic missing-column "
                    "drift, run Upgrade" % (type(e).__name__, e))
    print("SMOKE-OK: module installed, %d required fields present, "
          "res.users probe green" % len(REQUIRED_FIELDS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
