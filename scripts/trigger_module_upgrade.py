"""Headless module upgrade via XML-RPC (odoobulut has no SSH).

Use when the Apps UI is unreachable. NOTE: this only applies schema/data
for code ALREADY loaded in memory (server restarted after Git Deploy).
It can NOT load new Python code -- that needs Git Deploy + restart first.
ALSO NOTE: if logins themselves crash (e.g. missing column on res.users),
XML-RPC auth crashes too and this script cannot help; fix code + redeploy.

Credentials ONLY from process env. Without flags it uses the prod vars
(ODOO_URL/ODOO_DB/ODOO_USERNAME/ODOO_PASSWORD); with --staging it uses
ODOO_STAGING_URL/ODOO_STAGING_DB/ODOO_STAGING_USERNAME/
ODOO_STAGING_PASSWORD. Never prints secrets.
Default is dry-run (reports state only); --apply triggers the upgrade.

Usage:
    python scripts/trigger_module_upgrade.py [--staging] [--module NAME] [--apply]
Exit: 0 = installed/upgrade done, 1 = env/auth/trigger failure,
      2 = dry-run info only, 3 = poll timeout.
"""
import os
import sys
import time
import xmlrpc.client

POLL_TRIES = 40
POLL_WAIT = 15


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    try:
        name = args[args.index("--module") + 1]
    except (ValueError, IndexError):
        name = "matia_stock_planning"
    prefix = "ODOO_STAGING_" if "--staging" in args else "ODOO_"
    url = os.environ.get(prefix + "URL", "").rstrip("/")
    db = os.environ.get(prefix + "DB", "")
    user = os.environ.get(prefix + "USERNAME", "")
    pw = os.environ.get(prefix + "PASSWORD", "")
    if not all([url, db, user, pw]):
        print("ENV-MISSING: %sURL/%sDB/%sUSERNAME/%sPASSWORD"
              % (prefix, prefix, prefix, prefix))
        return 1
    print("target instance: %s" % url)
    common = xmlrpc.client.ServerProxy("%s/xmlrpc/2/common" % url)
    try:
        uid = common.authenticate(db, user, pw, {})
    except Exception as e:
        print("AUTH-FAILED: %s: %s" % (type(e).__name__, e))
        return 1
    if not uid:
        print("AUTH-FAILED: bad credentials")
        return 1
    models = xmlrpc.client.ServerProxy("%s/xmlrpc/2/object" % url)

    def mod_info():
        r = models.execute_kw(db, uid, pw, "ir.module.module", "search_read",
                              [[["name", "=", name]]],
                              {"fields": ["state"], "limit": 1})
        return (r[0]["id"], r[0]["state"]) if r else (None, "unknown")

    mod_id, state = mod_info()
    if not mod_id:
        print("MODULE-NOT-FOUND: %s" % name)
        return 1
    print("module %s (id %d) state: %s" % (name, mod_id, state))
    if not apply:
        print("dry-run: pass --apply to trigger button_immediate_upgrade")
        return 2
    try:
        models.execute_kw(db, uid, pw, "ir.module.module",
                          "button_immediate_upgrade", [[mod_id]])
        print("upgrade-triggered")
    except Exception as e:
        print("TRIGGER-FAILED: %s: %s" % (type(e).__name__, e))
        return 1
    for i in range(POLL_TRIES):
        time.sleep(POLL_WAIT)
        _, state = mod_info()
        print("poll %d: %s" % (i + 1, state))
        if state == "installed":
            print("UPGRADE-DONE")
            return 0
    print("POLL-TIMEOUT")
    return 3


if __name__ == "__main__":
    sys.exit(main())
