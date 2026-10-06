# -*- coding: utf-8 -*-
"""Matia Odoo 15 FULL archive backup -> static HTML. Read-only (search_read only).
Run: MatiaBackup.exe (reads .env next to the exe, writes archive_YYYYMMDD_HHMMSS next to the exe).
Test sample mode: BACKUP_SAMPLE=1 MatiaBackup.exe
"""
import os, re, sys, shutil, traceback, xmlrpc.client, html, base64, json
from collections import defaultdict
from datetime import datetime

def BASE():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.getcwd()

BASE = BASE()
SAMPLE = os.environ.get("BACKUP_SAMPLE") == "1"

def load_dotenv(path):
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def log(*a):
    print(*a, flush=True)

def main():
    envpath = os.path.join(BASE, ".env")
    if not os.path.exists(envpath):
        envpath = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(envpath):
        raise SystemExit("ERROR: .env not found next to the exe. Put ODOO_URL/ODOO_DB/ODOO_USERNAME/ODOO_PASSWORD in .env")
    env = load_dotenv(envpath)
    URL = env["ODOO_URL"].rstrip("/")
    DB, USER, PWD = env["ODOO_DB"], env["ODOO_USERNAME"], env["ODOO_PASSWORD"]
    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate(DB, USER, PWD, {})
    if not uid:
        raise SystemExit("ERROR: Odoo login failed. Check .env credentials.")
    obj = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)
    def kw(*a, **k):
        return obj.execute_kw(DB, uid, PWD, *a, **k)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUT = os.path.join(BASE, ("archive_SAMPLE_" if SAMPLE else "archive_") + stamp)

    def m2o(v):
        return v[1] if v else "-"
    def E(v):
        return html.escape("" if v in (None, False) else str(v))
    def safe(n):
        return re.sub(r"[^A-Za-z0-9_-]+", "_", n)
    def CO(cid):
        return "US" if cid == 2 else "TR"

    CSS = ("body{font-family:Segoe UI,Arial,sans-serif;max-width:1000px;margin:0 auto;padding:0 16px 24px;color:#1e293b;font-size:14px}"
     ".nav{background:#1e293b;color:#fff;margin:0 -16px 16px;padding:10px 16px;font-size:13px}"
     ".nav a{color:#bfdbfe;text-decoration:none}"
     "h1{font-size:20px}h2{font-size:15px;color:#1e40af;border-bottom:2px solid #dbeafe;padding-bottom:4px;margin-top:28px}"
     ".meta{background:#f1f5f9;border-radius:8px;padding:12px 16px;margin:16px 0;display:grid;grid-template-columns:1fr 1fr;gap:4px 24px}"
     "table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}th{background:#1e293b;color:#fff;padding:8px}"
     "td{border:1px solid #e2e8f0;padding:6px 8px}.num{text-align:right;white-space:nowrap}"
     ".tag{background:#dbeafe;color:#1e40af;border-radius:4px;padding:2px 8px;font-size:12px}"
     ".lot{background:#fef3c7;border-radius:4px;padding:1px 6px;font-family:Consolas,monospace;font-size:12px;white-space:nowrap}"
     ".notbox{background:#fffbeb;border:1px solid #f59e0b;border-radius:8px;padding:14px 16px;white-space:pre-wrap;margin:12px 0}"
     ".notehtml{background:#fff;border:1px solid #cbd5e1;border-radius:8px;padding:14px 16px;margin:12px 0;overflow-x:auto}"
     ".notehtml table{width:100%}.notehtml img{max-width:100%}"
     ".ncrhead{background:#7c2d12;color:#fff;border-radius:8px;padding:14px 16px}"
     ".gal{display:flex;flex-wrap:wrap;gap:10px}.gal a img{max-width:230px;border:1px solid #e2e8f0;border-radius:6px}"
     "#q{width:100%;font-size:16px;padding:10px 12px;border:2px solid #1e40af;border-radius:8px;margin:12px 0}"
     ".co{display:inline-block;width:44%;margin:0 2% 12px 0;padding:20px;border:2px solid #1e40af;border-radius:10px;text-align:center;font-size:20px;text-decoration:none}"
     ".co small{display:block;font-size:13px;color:#64748b;margin-top:6px}"
     "a{color:#1d4ed8}.foot{color:#64748b;font-size:12px;margin-top:24px}")

    SUBDIR = {"Sale Orders": "sales", "Manufacturing Orders": "manufacturing", "Purchase Orders": "purchases",
              "NCR Records": "ncr", "Scrap": "scrap"}
    XFRCOLS = ["Document", "Type", "Partner", "Date", "Status"]
    COLS = {"Sale Orders": ["Document", "Customer", "Date", "Total"],
            "Manufacturing Orders": ["Document", "Product", "Qty", "Lot", "Finished"],
            "Purchase Orders": ["Document", "Vendor", "Date", "Total"],
            "NCR Records": ["Document", "Source Receipt", "Date", "Photos"],
            "Scrap": ["Document", "Product", "Lot", "Qty", "Date"]}
    def sdir(g):
        return SUBDIR.get(g, "transfers_" + safe(g).lower())
    def gcols(g):
        return COLS.get(g, XFRCOLS)

    def clean_html(h):
        h = re.sub(r"<script.*?</script>", "", h, flags=re.S | re.I)
        h = re.sub(r"<iframe.*?</iframe>", "", h, flags=re.S | re.I)
        h = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", h, flags=re.I)
        return h
    def shownote(t):
        if not t:
            return ""
        if re.search(r"<(table|p|div|br|ul|ol|li|strong|font|span|h\d)[\s>]", t, re.I):
            return "<div class='notehtml'>" + clean_html(t) + "</div>"
        return "<div class='notbox'>" + E(t) + "</div>"

    REG, SEARCH, GROUPS = {}, [], defaultdict(list)
    def T(ctx, *vals):
        for v in vals:
            if v and v != "-":
                ctx["tok"].add(str(v))
    def link(name, frm):
        if name and name in REG:
            rel = os.path.relpath(REG[name], frm).replace(os.sep, "/")
            return f"<a href='{rel}'>{E(name)}</a>"
        return E(name or "-")
    def nav_rec(co, subdir, group):
        home = os.path.relpath("index.html", f"{co}/{subdir}").replace(os.sep, "/")
        coh = os.path.relpath(f"{co}/index.html", f"{co}/{subdir}").replace(os.sep, "/")
        return (f"<div class='nav'><a href='{home}'>← Home</a> &nbsp;|&nbsp; <a href='{coh}'>{E(co)}</a>"
                f" &nbsp;|&nbsp; <a href='index.html'>{E(group)}</a></div>")
    def grid(rows):
        return "<div class='meta'>" + "".join(f"<div><b>{E(k)}:</b> {v}</div>" for k, v in rows) + "</div>"
    def table(head, rows):
        return ("<table><thead><tr>" + "".join(f"<th>{E(h)}</th>" for h in head) + "</tr></thead><tbody>"
                + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table>")
    def page(co, subdir, fname, title, badge, body, rec_id, group, row, ctx, ncr=False):
        frm = f"{co}/{subdir}"
        head = (f"<div class='ncrhead'><h1 style='margin:0'>{E(title)} <span class='tag'>{E(badge)}</span></h1></div>"
                if ncr else f"<h1>{E(title)} <span class='tag'>{E(badge)}</span></h1>")
        h = (f"<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'><title>{E(title)}</title>"
             f"<style>{CSS}</style></head><body>{nav_rec(co, subdir, group)}"
             f"{head}{body}<div class='foot'>Legacy system (Odoo 15) archive copy — for reference only. Record ID: {rec_id}</div>"
             f"</body></html>")
        d = os.path.join(OUT, co, subdir)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, fname), "w", encoding="utf-8").write(h)
        rel = f"{frm}/{fname}"
        SEARCH.append({"t": title, "f": rel, "c": co, "y": group, "k": " ".join(sorted(ctx["tok"])).lower()})
        GROUPS[(co, group)].append({"t": title, "f": rel, "row": row})

    def move_rows(pid, ctx):
        mls = kw("stock.move.line", "search_read", [[["picking_id", "=", pid]]],
                 {"fields": ["product_id", "lot_id", "product_uom_qty", "qty_done", "location_id", "location_dest_id"],
                  "limit": 5000})
        rows = []
        for m in mls:
            T(ctx, m2o(m["product_id"]), m2o(m["lot_id"]))
            lot = f"<span class='lot'>{E(m2o(m['lot_id']))}</span>" if m["lot_id"] else "-"
            rows.append([E(m2o(m["product_id"])), lot,
                         f"<span class='num'>{m['product_uom_qty'] or 0}</span>",
                         f"<span class='num'>{m['qty_done'] or 0}</span>",
                         E(f"{m2o(m.get('location_id'))} → {m2o(m.get('location_dest_id'))}")])
        return rows

    def transfer_body(p, frm, ctx):
        T(ctx, p["name"], m2o(p.get("partner_id")), p.get("origin"))
        b = grid([
            ("Transfer No", E(p["name"])), ("Type", E(m2o(p.get("picking_type_id")))),
            ("Partner", E(m2o(p.get("partner_id")))), ("Source Document", link(p.get("origin"), frm)),
            ("Scheduled", E((p.get("scheduled_date") or "")[:10])), ("Done Date", E((p.get("date_done") or "")[:10])),
            ("Route", E(f"{m2o(p.get('location_id'))} → {m2o(p.get('location_dest_id'))}")), ("Status", E(p["state"])),
            ("Company", E(m2o(p.get("company_id")))),
        ])
        if p.get("note"):
            b += "<h2>Note</h2>" + shownote(p["note"])
        b += "<h2>Product Moves (lot/serial detail)</h2>" + table(
            ["Product", "Lot/Serial", "Demand", "Done", "Route"], move_rows(p["id"], ctx))
        return b

    PF = ["name", "partner_id", "scheduled_date", "date_done", "origin", "state",
          "location_id", "location_dest_id", "note", "picking_type_id", "company_id"]
    SOF = ["name", "date_order", "partner_id", "partner_invoice_id", "partner_shipping_id", "client_order_ref",
           "pricelist_id", "payment_term_id", "incoterm", "user_id", "team_id", "company_id", "origin", "state",
           "invoice_status", "commitment_date", "validity_date", "amount_untaxed", "amount_tax", "amount_total",
           "currency_id", "invoice_ids", "picking_ids"]
    MOF = ["name", "product_id", "product_qty", "product_uom_id", "bom_id", "company_id", "user_id", "priority",
           "origin", "state", "date_planned_start", "date_planned_finished", "date_start", "date_finished",
           "location_src_id", "location_dest_id", "production_location_id", "picking_type_id", "lot_producing_id",
           "picking_ids", "workorder_ids"]

    PCACHE = {}
    def addr(pid):
        if not pid:
            return "-"
        if pid[0] in PCACHE:
            return PCACHE[pid[0]]
        a = kw("res.partner", "search_read", [[["id", "=", pid[0]]]],
               {"fields": ["name", "street", "city", "country_id"], "limit": 1})[0]
        parts = [a["name"], a.get("street") or "", a.get("city") or "", m2o(a.get("country_id"))]
        r = E(", ".join(p for p in parts if p and p != "-"))
        PCACHE[pid[0]] = r
        return r

    def build_sale(so):
        co = CO(so["company_id"][0]); frm = f"{co}/sales"
        ctx = {"tok": set()}
        T(ctx, so["name"], m2o(so["partner_id"]), so.get("origin"))
        lines = kw("sale.order.line", "search_read", [[["order_id", "=", so["id"]]]],
                   {"fields": ["product_id", "name", "product_uom_qty", "qty_delivered", "qty_invoiced",
                               "price_unit", "tax_id", "price_subtotal"], "order": "id"})
        cur = m2o(so.get("currency_id"))
        b = "<h2>Document Details</h2>" + grid([
            ("Order No", E(so["name"])), ("Order Date", E(so["date_order"])),
            ("Customer", E(m2o(so["partner_id"]))), ("Customer Reference", E(so.get("client_order_ref") or "-")),
            ("Invoice Address", addr(so.get("partner_invoice_id"))), ("Delivery Address", addr(so.get("partner_shipping_id"))),
            ("Pricelist", E(m2o(so.get("pricelist_id")))), ("Payment Terms", E(m2o(so.get("payment_term_id")))),
            ("Incoterm", E(m2o(so.get("incoterm")))), ("Salesperson", E(m2o(so.get("user_id")))),
            ("Sales Team", E(m2o(so.get("team_id")))), ("Company", E(m2o(so.get("company_id")))),
            ("Source Document", link(so.get("origin"), frm)), ("Status", E(so["state"])),
            ("Invoice Status", E(so.get("invoice_status") or "-")), ("Delivery Date", E(so.get("commitment_date") or "-")),
            ("Expiration", E(so.get("validity_date") or "-")),
        ])
        b += "<h2>Order Lines</h2>" + table(
            ["Product", "Description", "Ordered", "Delivered", "Invoiced", "Unit Price", "Taxes", "Line Total"],
            [[E(m2o(l["product_id"])), E((l["name"] or "")[:80]),
              f"<span class='num'>{l['product_uom_qty']}</span>", f"<span class='num'>{l.get('qty_delivered', 0)}</span>",
              f"<span class='num'>{l.get('qty_invoiced', 0)}</span>", f"<span class='num'>{l['price_unit']}</span>",
              E(", ".join(t[1] for t in l.get("tax_id") or []) or "-"),
              f"<span class='num'>{l['price_subtotal']}</span>"] for l in lines])
        for l in lines:
            T(ctx, m2o(l["product_id"]))
        b += "<h2>Totals</h2>" + grid([
            ("Untaxed", E(f"{so['amount_untaxed']} {cur}")), ("Tax", E(f"{so.get('amount_tax', 0)} {cur}")),
            ("Total", E(f"{so['amount_total']} {cur}"))])
        sp = kw("stock.picking", "search_read", [[["id", "in", so.get("picking_ids") or []]]],
                {"fields": ["name", "date_done", "scheduled_date", "state"]})
        if sp:
            b += "<h2>Deliveries</h2>" + table(["Transfer", "Date", "Status"],
                [[link(p["name"], frm), E(((p.get("date_done") or p.get("scheduled_date")) or "")[:10]), E(p["state"])]
                 for p in sp])
            for p in sp:
                mls = kw("stock.move.line", "search_read", [[["picking_id", "=", p["id"]], ["lot_id", "!=", False]]],
                         {"fields": ["product_id", "lot_id", "qty_done"], "limit": 500})
                for m in mls:
                    T(ctx, m2o(m["lot_id"]))
                if mls:
                    b += f"<h2>Delivered Lots ({E(p['name'])})</h2>" + table(["Product", "Lot/Serial", "Qty"],
                        [[E(m2o(m["product_id"])), f"<span class='lot'>{E(m2o(m['lot_id']))}</span>",
                          f"<span class='num'>{m['qty_done']}</span>"] for m in mls])
        invs = kw("account.move", "search_read", [[["id", "in", so.get("invoice_ids") or []]]],
                  {"fields": ["name", "invoice_date", "amount_total", "state", "payment_state"]})
        if invs:
            b += "<h2>Invoices</h2>" + table(["Invoice", "Date", "Amount", "Status", "Payment"],
                [[E(i["name"]), E(i.get("invoice_date") or "-"), f"<span class='num'>{i['amount_total']}</span>",
                  E(i["state"]), E(i.get("payment_state") or "-")] for i in invs])
        row = [E(so["name"]), E(m2o(so["partner_id"])), E((so["date_order"] or "")[:10]),
               E(f"{so['amount_total']} {cur}")]
        page(co, "sales", safe(so["name"]) + ".html", f"Sale Order {so['name']}", "SALES / ARCHIVE",
             b, so["id"], "Sale Orders", row, ctx)

    def build_mo(mo):
        co = CO(mo["company_id"][0]); frm = f"{co}/manufacturing"
        ctx = {"tok": set()}
        T(ctx, mo["name"], m2o(mo["product_id"]), m2o(mo.get("lot_producing_id")), mo.get("origin"))
        b = "<h2>Order Details</h2>" + grid([
            ("MO No", E(mo["name"])), ("Status", E(mo["state"])),
            ("Product", E(m2o(mo["product_id"]))), ("Quantity", E(f"{mo['product_qty']} {m2o(mo.get('product_uom_id'))}")),
            ("Bill of Material", E(m2o(mo.get("bom_id")))),
            ("Company", E(m2o(mo.get("company_id")))), ("Responsible", E(m2o(mo.get("user_id")))),
            ("Priority", E(mo.get("priority") or "-")), ("Source", link(mo.get("origin"), frm)),
            ("Scheduled Start", E(mo.get("date_planned_start") or "-")),
            ("Scheduled End", E(mo.get("date_planned_finished") or "-")),
            ("Actual Start", E(mo.get("date_start") or "-")), ("Actual End", E(mo.get("date_finished") or "-")),
            ("Components Location", E(m2o(mo.get("location_src_id")))),
            ("Finished Location", E(m2o(mo.get("location_dest_id")))),
            ("Production Location", E(m2o(mo.get("production_location_id")))),
            ("Operation Type", E(m2o(mo.get("picking_type_id")))),
        ])
        fin = kw("stock.move.line", "search_read",
                 [[["production_id", "=", mo["id"]], ["lot_id", "!=", False]]],
                 {"fields": ["product_id", "lot_id", "qty_done", "location_dest_id"], "limit": 1000})
        for f in fin:
            T(ctx, m2o(f["lot_id"]))
        lot_main = m2o(mo.get("lot_producing_id"))
        b += "<h2>Finished Product & Serial/Lot Numbers</h2>" + grid(
            [("Primary Lot/Serial", f"<span class='lot'>{E(lot_main)}</span>")]) + table(
            ["Product", "Lot/Serial", "Qty", "Location"],
            [[E(m2o(f["product_id"])), f"<span class='lot'>{E(m2o(f['lot_id']))}</span>",
              f"<span class='num'>{f['qty_done']}</span>", E(m2o(f.get("location_dest_id")))] for f in fin])
        raw = kw("stock.move.line", "search_read", [[["production_id", "=", mo["id"]]]],
                 {"fields": ["product_id", "lot_id", "product_uom_qty", "qty_done", "location_id"], "limit": 5000})
        by_prod = defaultdict(list)
        for m in raw:
            by_prod[m2o(m["product_id"])].append(m)
        rows = []
        for prod, ms in sorted(by_prod.items()):
            T(ctx, prod)
            need = sum(m["product_uom_qty"] or 0 for m in ms)
            done = sum(m["qty_done"] or 0 for m in ms)
            lots = ", ".join(f"<span class='lot'>{E(m2o(m['lot_id']) + ' x' + str(m['qty_done']))}</span>"
                             for m in ms if m["lot_id"]) or "-"
            for m in ms:
                T(ctx, m2o(m["lot_id"]))
            locs = ", ".join(sorted({m2o(m.get("location_id")) for m in ms}))[:60]
            rows.append([E(prod), f"<span class='num'>{round(need, 2)}</span>", f"<span class='num'>{round(done, 2)}</span>", lots, E(locs)])
        b += f"<h2>Consumed Components ({len(by_prod)} items, with lots)</h2>" + table(
            ["Component", "Needed", "Consumed", "Used Lots/Serials", "Location"], rows)
        wos = kw("mrp.workorder", "search_read", [[["production_id", "=", mo["id"]]]],
                 {"fields": ["name", "workcenter_id", "state", "date_planned_start", "date_finished", "duration_expected"]})
        if wos:
            b += "<h2>Work Orders / Operations</h2>" + table(["Operation", "Work Center", "Status", "Planned", "Finished", "Expected (min)"],
                [[E(w["name"]), E(m2o(w.get("workcenter_id"))), E(w["state"]),
                  E((w.get("date_planned_start") or "-")[:16]), E((w.get("date_finished") or "-")[:16]),
                  f"<span class='num'>{w.get('duration_expected', 0)}</span>"] for w in wos])
        mp = kw("stock.picking", "search_read", [[["id", "in", mo.get("picking_ids") or []]]],
                {"fields": ["name", "date_done", "state"]})
        if mp:
            b += "<h2>Related Transfers</h2>" + table(["Transfer", "Date", "Status"],
                [[link(p["name"], frm), E((p.get("date_done") or "-")[:10]), E(p["state"])] for p in mp])
        row = [E(mo["name"]), E(m2o(mo["product_id"])), E(str(mo["product_qty"])),
               f"<span class='lot'>{E(lot_main)}</span>", E((mo.get("date_finished") or "")[:10])]
        page(co, "manufacturing", safe(mo["name"]) + ".html", f"Manufacturing Order {mo['name']}",
             "MANUFACTURING / ARCHIVE", b, mo["id"], "Manufacturing Orders", row, ctx)

    POLF = None
    def build_po(po):
        nonlocal POLF
        co = CO(po["company_id"][0]); frm = f"{co}/purchases"
        ctx = {"tok": set()}
        T(ctx, po["name"], m2o(po.get("partner_id")), po.get("origin"))
        if POLF is None:
            pfg = kw("purchase.order.line", "fields_get", [], {"attributes": []})
            POLF = [f for f in ["product_id", "name", "product_qty", "qty_received", "qty_invoiced", "price_unit",
                                "taxes_id", "price_subtotal"] if f in pfg]
        pls = kw("purchase.order.line", "search_read", [[["order_id", "=", po["id"]]]], {"fields": POLF, "order": "id"})
        cur = m2o(po.get("currency_id"))
        b = "<h2>Document Details</h2>" + grid([
            ("Order No", E(po["name"])), ("Order Date", E((po.get("date_order") or "")[:16])),
            ("Vendor", E(m2o(po.get("partner_id")))), ("Vendor Reference", E(po.get("partner_ref") or "-")),
            ("Planned Delivery", E((po.get("date_planned") or "")[:10] if po.get("date_planned") else "-")),
            ("Pricelist", E(m2o(po.get("pricelist_id")))), ("Payment Terms", E(m2o(po.get("payment_term_id")))),
            ("Incoterm", E(m2o(po.get("incoterm_id")))), ("Buyer", E(m2o(po.get("user_id")))),
            ("Company", E(m2o(po.get("company_id")))), ("Source", link(po.get("origin"), frm)), ("Status", E(po["state"])),
        ])
        b += "<h2>Order Lines</h2>" + table(
            ["Product", "Description", "Ordered", "Received", "Billed", "Unit Price", "Taxes", "Line Total"],
            [[E(m2o(l.get("product_id"))), E((l.get("name") or "")[:80]),
              f"<span class='num'>{l.get('product_qty', 0)}</span>", f"<span class='num'>{l.get('qty_received', 0)}</span>",
              f"<span class='num'>{l.get('qty_invoiced', 0)}</span>", f"<span class='num'>{l.get('price_unit', 0)}</span>",
              E(", ".join(t[1] for t in l.get("taxes_id") or []) or "-"),
              f"<span class='num'>{l.get('price_subtotal', 0)}</span>"] for l in pls])
        for l in pls:
            T(ctx, m2o(l.get("product_id")))
        b += "<h2>Totals</h2>" + grid([
            ("Untaxed", E(f"{po.get('amount_untaxed', 0)} {cur}")), ("Tax", E(f"{po.get('amount_tax', 0)} {cur}")),
            ("Total", E(f"{po.get('amount_total', 0)} {cur}"))])
        if po.get("notes"):
            b += "<h2>Notes</h2>" + shownote(po["notes"])
        rp = kw("stock.picking", "search_read", [[["id", "in", po.get("picking_ids") or []]]],
                {"fields": ["name", "date_done", "scheduled_date", "state"]})
        if rp:
            b += "<h2>Receipts</h2>" + table(["Transfer", "Date", "Status"],
                [[link(p["name"], frm), E(((p.get("date_done") or p.get("scheduled_date")) or "")[:10]), E(p["state"])]
                 for p in rp])
        bills = kw("account.move", "search_read", [[["id", "in", po.get("invoice_ids") or []]]],
                   {"fields": ["name", "invoice_date", "amount_total", "state", "payment_state"]})
        if bills:
            b += "<h2>Vendor Bills</h2>" + table(["Bill", "Date", "Amount", "Status", "Payment"],
                [[E(x["name"]), E(x.get("invoice_date") or "-"), f"<span class='num'>{x['amount_total']}</span>",
                  E(x["state"]), E(x.get("payment_state") or "-")] for x in bills])
        row = [E(po["name"]), E(m2o(po.get("partner_id"))), E((po.get("date_order") or "")[:10]),
               E(f"{po.get('amount_total', 0)} {cur}")]
        page(co, "purchases", safe(po["name"]) + ".html", f"Purchase Order {po['name']}", "PURCHASE / ARCHIVE",
             b, po["id"], "Purchase Orders", row, ctx)

    def build_transfer(p):
        co = CO(p["company_id"][0])
        ctx = {"tok": set()}
        tname = m2o(p.get("picking_type_id"))
        group = f"Transfer: {tname}"
        sub = sdir(group)
        body = transfer_body(p, f"{co}/{sub}", ctx)
        row = [E(p["name"]), E(tname), E(m2o(p.get("partner_id"))),
               E((p.get("date_done") or "")[:10]), E(p["state"])]
        page(co, sub, safe(p["name"]) + ".html", f"Transfer {p['name']}",
             f"{tname} / ARCHIVE", body, p["id"], group, row, ctx)

    def build_ncr(n):
        co = CO(n["company_id"][0]); frm = f"{co}/ncr"
        ctx = {"tok": set()}
        T(ctx, n["name"], n.get("origin"), m2o(n.get("partner_id")))
        atts = kw("ir.attachment", "search_read",
                  [[["res_model", "=", "stock.picking"], ["res_id", "=", n["id"]]]],
                  {"fields": ["name", "mimetype", "file_size", "datas"]})
        imgs = []
        os.makedirs(os.path.join(OUT, co, "attachments"), exist_ok=True)
        for i, a in enumerate(atts):
            if (a.get("mimetype") or "").startswith("image/") and a.get("datas"):
                fn = f"ncr_{safe(n['name'])}_{i}.jpg"
                open(os.path.join(OUT, co, "attachments", fn), "wb").write(base64.b64decode(a["datas"]))
                imgs.append((fn, a["name"]))
        b = grid([
            ("NCR No", E(n["name"])), ("Record Type", E(m2o(n.get("picking_type_id")))),
            ("Source Receipt", link(n.get("origin"), frm)),
            ("Date", E((n.get("date_done") or n.get("scheduled_date") or "")[:10])),
            ("Partner", E(m2o(n.get("partner_id")))),
            ("Route", E(f"{m2o(n.get('location_id'))} → {m2o(n.get('location_dest_id'))}")),
            ("Status", E(n["state"])), ("Company", E(m2o(n.get("company_id")))),
        ])
        b += "<h2>Nonconformity Note</h2>" + (shownote(n.get("note")) or "<div class='notbox'>(no note)</div>")
        b += "<h2>Products & Lots</h2>" + table(
            ["Product", "Lot/Serial", "Demand", "Done", "Route"], move_rows(n["id"], ctx))
        if imgs:
            b += f"<h2>Photos ({len(imgs)})</h2><div class='gal'>" + "".join(
                f"<a href='../attachments/{f}'><img src='../attachments/{f}' alt='{E(c)}' title='{E(c)}'></a>"
                for f, c in imgs) + "</div>"
            b += "<h2>Attachment List</h2>" + table(["File", "Type", "Size (KB)"],
                [[f"<a href='../attachments/{f}'>{E(c)}</a>", "image",
                  f"<span class='num'>{round(os.path.getsize(os.path.join(OUT, co, 'attachments', f)) / 1024)}</span>"]
                 for f, c in imgs])
        row = [E(n["name"]), link(n.get("origin"), frm), E((n.get("date_done") or "")[:10]), E(str(len(imgs)))]
        page(co, "ncr", safe(n["name"]) + ".html", f"NCR {n['name']}", "NCR / NONCONFORMITY / ARCHIVE",
             b, n["id"], "NCR Records", row, ctx, ncr=True)

    def build_scrap(s):
        co = CO(s["company_id"][0]); frm = f"{co}/scrap"
        ctx = {"tok": set()}
        T(ctx, s["name"], m2o(s.get("product_id")), m2o(s.get("lot_id")), s.get("origin"))
        b = "<h2>Scrap Details</h2>" + grid([
            ("Scrap No", E(s["name"])), ("Product", E(m2o(s.get("product_id")))),
            ("Lot/Serial", f"<span class='lot'>{E(m2o(s.get('lot_id')))}</span>" if s.get("lot_id") else "-"),
            ("Quantity", E(f"{s.get('scrap_qty', 0)} {m2o(s.get('product_uom_id'))}")),
            ("Location", E(m2o(s.get("location_id")))), ("Source Document", link(s.get("origin"), frm)),
            ("Related Transfer", link(m2o(s.get("picking_id")) if s.get("picking_id") else None, frm)),
            ("Date", E((s.get("date_done") or "")[:10])), ("Status", E(s["state"])),
            ("Company", E(m2o(s.get("company_id")))),
        ])
        row = [E(s["name"]), E(m2o(s.get("product_id"))),
               f"<span class='lot'>{E(m2o(s.get('lot_id')))}</span>" if s.get("lot_id") else "-",
               E(str(s.get("scrap_qty", 0))), E((s.get("date_done") or "")[:10])]
        page(co, "scrap", safe(s["name"]) + ".html", f"Scrap {s['name']}", "SCRAP / ARCHIVE",
             b, s["id"], "Scrap", row, ctx)

    # ---------------- record selection ----------------
    log("Connecting to", URL, "| DB:", DB, "| mode:", "SAMPLE" if SAMPLE else "FULL")
    if SAMPLE:
        sales = kw("sale.order", "search_read", [[["id", "in", [159, 137]]]], {"fields": SOF})
        mos = kw("mrp.production", "search_read", [[["id", "in", [3259, 3194]]]], {"fields": MOF})
        pfg = kw("purchase.order", "fields_get", [], {"attributes": []})
        pw = ["name", "date_order", "date_planned", "partner_id", "partner_ref", "pricelist_id", "payment_term_id",
              "incoterm_id", "user_id", "company_id", "origin", "state", "amount_untaxed", "amount_tax",
              "amount_total", "currency_id", "picking_ids", "invoice_ids", "notes"]
        pos = kw("purchase.order", "search_read", [[["id", "=", 449]]],
                 {"fields": [f for f in pw if f in pfg]})
        picks = kw("stock.picking", "search_read", [[["id", "=", 2848]]], {"fields": PF})
        extra_ids = []
        for so in sales:
            extra_ids += list(so.get("picking_ids") or [])
        for po in pos:
            extra_ids += list(po.get("picking_ids") or [])
        if extra_ids:
            picks += kw("stock.picking", "search_read", [[["id", "in", extra_ids]]], {"fields": PF})
        seen = {p["id"] for p in picks}
        for tid in [1, 2, 5, 11, 6]:
            r = kw("stock.picking", "search_read",
                   [[["picking_type_id", "=", tid], ["company_id", "=", 1], ["state", "=", "done"],
                     ["id", "not in", list(seen)]]],
                   {"fields": PF, "limit": 1, "order": "date_done desc"})
            if r:
                seen.add(r[0]["id"])
                picks.append(r[0])
        sfg = kw("stock.scrap", "fields_get", [], {"attributes": []})
        sw = ["name", "product_id", "lot_id", "scrap_qty", "product_uom_id", "location_id", "origin", "date_done",
              "state", "company_id", "picking_id"]
        scraps = kw("stock.scrap", "search_read", [[["id", "=", 118]]],
                    {"fields": [f for f in sw if f in sfg]})
    else:
        NOTC = [["state", "!=", "cancel"]]
        sales = kw("sale.order", "search_read", [NOTC], {"fields": SOF, "limit": 100000, "order": "id"})
        mos = kw("mrp.production", "search_read", [NOTC], {"fields": MOF, "limit": 100000, "order": "id"})
        pfg = kw("purchase.order", "fields_get", [], {"attributes": []})
        pw = ["name", "date_order", "date_planned", "partner_id", "partner_ref", "pricelist_id", "payment_term_id",
              "incoterm_id", "user_id", "company_id", "origin", "state", "amount_untaxed", "amount_tax",
              "amount_total", "currency_id", "picking_ids", "invoice_ids", "notes"]
        pos = kw("purchase.order", "search_read", [NOTC], {"fields": [f for f in pw if f in pfg],
                                                           "limit": 100000, "order": "id"})
        picks = kw("stock.picking", "search_read", [NOTC], {"fields": PF, "limit": 100000, "order": "id"})
        sfg = kw("stock.scrap", "fields_get", [], {"attributes": []})
        sw = ["name", "product_id", "lot_id", "scrap_qty", "product_uom_id", "location_id", "origin", "date_done",
              "state", "company_id", "picking_id"]
        scraps = kw("stock.scrap", "search_read", [NOTC], {"fields": [f for f in sw if f in sfg],
                                                           "limit": 100000, "order": "id"})
    log(f"Found: {len(sales)} sales, {len(mos)} MOs, {len(pos)} purchases, {len(picks)} transfers, {len(scraps)} scraps")

    def reg(co, sub, name):
        REG[name] = f"{co}/{sub}/{safe(name)}.html"
    for so in sales:
        reg(CO(so["company_id"][0]), "sales", so["name"])
    for mo in mos:
        reg(CO(mo["company_id"][0]), "manufacturing", mo["name"])
    for po in pos:
        reg(CO(po["company_id"][0]), "purchases", po["name"])
    for s in scraps:
        reg(CO(s["company_id"][0]), "scrap", s["name"])
    for p in picks:
        tn = m2o(p.get("picking_type_id"))
        if "NCR" in tn.upper():
            reg(CO(p["company_id"][0]), "ncr", p["name"])
        else:
            reg(CO(p["company_id"][0]), sdir(f"Transfer: {tn}"), p["name"])

    def progress(i, n, label):
        if i % 25 == 0 or i == n:
            log(f"  {label}: {i}/{n}")

    for i, so in enumerate(sales, 1):
        build_sale(so)
        progress(i, len(sales), "sales")
    for i, mo in enumerate(mos, 1):
        build_mo(mo)
        progress(i, len(mos), "manufacturing")
    for i, po in enumerate(pos, 1):
        build_po(po)
        progress(i, len(pos), "purchases")
    for i, p in enumerate(picks, 1):
        if "NCR" in m2o(p.get("picking_type_id")).upper():
            build_ncr(p)
        else:
            build_transfer(p)
        progress(i, len(picks), "transfers/ncr")
    for i, s in enumerate(scraps, 1):
        build_scrap(s)
        progress(i, len(scraps), "scrap")

    # ---------------- hierarchy pages ----------------
    def wrap(title, nav, body):
        return (f"<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'><title>{E(title)}</title>"
                f"<style>{CSS}</style></head><body>{nav}{body}</body></html>")
    for (co, g), items in sorted(GROUPS.items()):
        sub = sdir(g)
        rows = []
        for it in items:
            frel = os.path.relpath(it["f"], f"{co}/{sub}").replace(os.sep, "/")
            rows.append([f"<a href='{E(frel)}'>{E(it['t'])}</a>"] + it["row"][1:])
        b = f"<h1>{E(co)} — {E(g)} <span class='tag'>{len(items)} RECORDS</span></h1>" + table(["Document"] + gcols(g)[1:], rows)
        open(os.path.join(OUT, co, sub, "index.html"), "w", encoding="utf-8").write(
            wrap(f"{co} {g}", f"<div class='nav'><a href='../../index.html'>← Home</a> &nbsp;|&nbsp; "
                 f"<a href='../index.html'>{E(co)}</a></div>", b))
    for co in ["US", "TR"]:
        gs = sorted({g for (c, g) in GROUPS if c == co})
        tot = sum(len(GROUPS[(co, g)]) for g in gs)
        rows = [[f"<a href='{sdir(g)}/index.html'>{E(g)}</a>", f"<span class='num'>{len(GROUPS[(co, g)])}</span>"] for g in gs]
        b = f"<h1>{E(co)} Company Archive <span class='tag'>{tot} RECORDS</span></h1>" + table(["Document Type", "Records"], rows)
        open(os.path.join(OUT, co, "index.html"), "w", encoding="utf-8").write(
            wrap(f"{co} Archive", "<div class='nav'><a href='../index.html'>← Home</a></div>", b))
    mode = "SAMPLE" if SAMPLE else "FULL BACKUP " + stamp
    JS = ("<input id='q' placeholder='Search: document name, partner, product, lot / serial number...' oninput='f()'>"
          "<div id='res'></div>"
          "<div id='groups'>"
          f"<a class='co' href='US/index.html'>US<br><small>Matia Robotics (US) Inc. — "
          f"{sum(len(GROUPS[(c, g)]) for (c, g) in GROUPS if c == 'US')} records</small></a>"
          f"<a class='co' href='TR/index.html'>TR<br><small>Matia Robotics TR — "
          f"{sum(len(GROUPS[(c, g)]) for (c, g) in GROUPS if c == 'TR')} records</small></a>"
          "</div><script>var D=" + json.dumps(SEARCH, ensure_ascii=False) +
          ";function f(){var q=document.getElementById('q').value.toLowerCase().trim();"
          "var g=document.getElementById('groups'),r=document.getElementById('res');"
          "if(!q){g.style.display='';r.innerHTML='';return;}g.style.display='none';"
          "var h=D.filter(function(d){return d.k.indexOf(q)>-1}).slice(0,100);"
          "r.innerHTML=h.length?'<h2>Results ('+h.length+')</h2><table><thead><tr><th>Document</th><th>Company</th><th>Type</th></tr></thead><tbody>'+"
          "h.map(function(d){return '<tr><td><a href=\"'+d.f+'\">'+d.t+'</a></td><td>'+d.c+'</td><td>'+d.y+'</td></tr>'}).join('')+'</tbody></table>'"
          ": '<p>No matches found.</p>';}</script>")
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(
        wrap("Legacy Archive",
             "<div class='nav'>Legacy System Archive (Odoo 15) — reference copy</div>",
             f"<h1>Legacy System Archive <span class='tag'>{mode}</span></h1>"
             "<div class='meta'><div>Search below, or pick a company folder. "
             "Company → document type → full list → record page. Every page links back up.</div></div>" + JS))
    # link check
    bad = 0
    npages = 0
    for dp, _, fns in os.walk(OUT):
        for fn in fns:
            if not fn.endswith(".html"):
                continue
            npages += 1
            h = open(os.path.join(dp, fn), encoding="utf-8").read()
            for x in re.findall(r"href='([^']+)'", h):
                if x.startswith("http"):
                    continue
                if not os.path.exists(os.path.normpath(os.path.join(dp, x))):
                    log("BROKEN:", os.path.relpath(os.path.join(dp, fn), OUT), "->", x)
                    bad += 1
    log(f"DONE: {len(SEARCH)} records, {npages} pages, broken links: {bad}")
    log("Output folder:", OUT)
    return OUT

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
    if getattr(sys, "frozen", False):
        input("Press Enter to close...")
