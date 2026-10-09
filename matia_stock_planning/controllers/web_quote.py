# -*- coding: utf-8 -*-
"""Public read-only web quote page + JSON API (v1).

Provides two ``auth='public'`` GET routes guarded by a shared secret
(``QUOTE_KEY``) stored in ``ir.config_parameter`` key ``web_quote.key``:

- ``GET /web_quote``: simple HTML page (qty input, key input, result table).
  Inline string, no XML/view file, no manifest ``data`` change.
- ``GET /web_quote/quote?qty=N&key=...``: JSON quote for N full-combo
  (base+screws+outdoor+seat) device sets: gross = full x N, net = SUM of
  top-level net needs x rolled unit USD. Read-only: no write method
  (``save_slot``, ``set_targets_and_rebuild``) is ever called here.

Odoo 15 notes: ``auth='public'`` env is unprivileged, so internal calls
use recordset ``.sudo()`` (``Environment.sudo()`` does not exist in 15).
"""
import json

from odoo import http
from odoo.http import request

_QTY_MIN = 1
_QTY_MAX = 10000
_CONFIG_KEY = 'web_quote.key'


def _quote_key_ok(provided):
    """Check the provided key against ir.config_parameter (fail closed).

    @param provided: raw ``key`` query value (may be None/empty).
    @return: True only when a stored key exists and matches exactly.
    """
    if not provided:
        return False
    try:
        stored = request.env['ir.config_parameter'].sudo().get_param(
            _CONFIG_KEY, default=False)
    except Exception:
        return False
    if not stored:
        return False
    return str(provided) == str(stored)


def _json_response(payload, status=200):
    """Build a JSON http response.

    @param payload: JSON-serializable dict.
    @param status: HTTP status code.
    @return: Werkzeug response with application/json content type.
    """
    # Odoo 15 ``make_response(data, headers, cookies)`` takes NO status
    # argument (verified against 15.0 source); set it afterwards.
    response = request.make_response(
        json.dumps(payload),
        headers=[('Content-Type', 'application/json; charset=utf-8')],
    )
    response.status_code = status
    return response


def _build_quote(qty):
    """Compute gross + net quote for N full-combo device sets (read-only).

    @param qty: device count (int, already validated 1..10000).
    @return: dict with qty, gross_usd, net_usd, full_usd, lines.
    """
    cost_env = request.env['matia.product.cost'].sudo()
    plan_env = request.env['matia.stock.planning'].sudo()
    cost_tree = cost_env.get_cost_tree()
    combos = (cost_tree or {}).get('combos') or {}
    full = float(combos.get('full') or 0.0)
    unit_map = {}
    for grp in (cost_tree or {}).get('groups') or []:
        for item in grp.get('items') or []:
            try:
                pid = int(item.get('product_id'))
            except (TypeError, ValueError):
                continue
            try:
                unit_map[pid] = float(item.get('unit_usd') or 0.0)
            except (TypeError, ValueError):
                unit_map[pid] = 0.0
    cap = plan_env.get_capacity_planning_data(
        include_tr=True, include_usa=True, dynamic_targets=[qty])
    qkey = str(int(qty))
    lines = []
    net_total = 0.0
    for grp in (cap or {}).get('groups') or []:
        for item in grp.get('items') or []:
            try:
                pid = int(item.get('product_id'))
            except (TypeError, ValueError):
                continue
            needs = item.get('dynamic_needs') or {}
            entry = needs.get(qkey) or {}
            try:
                need_units = float(entry.get('val') or 0.0)
            except (TypeError, ValueError):
                need_units = 0.0
            unit = float(unit_map.get(pid) or 0.0)
            line_net = round(need_units * unit, 2)
            net_total += line_net
            lines.append({
                'product_id': pid,
                'code': item.get('product_code') or '',
                'name': item.get('product_name') or '',
                'group': grp.get('key') or '',
                'bom_qty': item.get('bom_qty') or 0.0,
                'avail': item.get('avail_qty') or 0,
                'need_units': need_units,
                'unit_usd': round(unit, 4),
                'line_net_usd': line_net,
            })
    lines.sort(key=lambda r: (r.get('group') or '', r.get('code') or ''))
    gross = round(full * int(qty), 2)
    return {
        'qty': int(qty),
        'full_usd': round(full, 2),
        'gross_usd': gross,
        'net_usd': round(net_total, 2),
        'lines': lines,
        'note': 'Top-level net only, no sub-BOM detail.',
    }


class WebQuoteController(http.Controller):
    """Public read-only quote endpoints (key-guarded, no login)."""

    @http.route('/web_quote', type='http', auth='public', methods=['GET'],
                csrf=False)
    def web_quote_page(self, **kwargs):
        """Serve the inline HTML quote page (no key check here).

        The key is only checked on the JSON API; the page itself holds
        no data.

        @return: HTML response.
        """
        html = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Web Quote</title>
<style>
body{font-family:Arial,sans-serif;margin:2rem;max-width:900px}
label{display:inline-block;min-width:90px}
input{padding:.35rem;margin:.25rem}
button{padding:.4rem 1rem;cursor:pointer}
table{border-collapse:collapse;width:100%;margin-top:1rem}
th,td{border:1px solid #ccc;padding:.35rem .5rem;text-align:left;font-size:.85rem}
th{background:#f2f2f2}
#err{color:#b00}
.mut{color:#666;font-size:.8rem}
</style></head><body>
<h2>Web Quote (full combo)</h2>
<p class="mut">Base + Screws + Outdoor + Seat per device set. Top-level net only.</p>
<div>
<label for="q">Qty (1-10000):</label>
<input id="q" type="number" value="100" min="1" max="10000"/>
<label for="k">Key:</label>
<input id="k" type="password" autocomplete="off"/>
<button onclick="calc()">Calculate</button>
</div>
<div id="err"></div>
<div id="sum"></div>
<table id="tbl" style="display:none"><thead><tr>
<th>Group</th><th>Code</th><th>Product</th><th>BOM qty</th>
<th>Avail</th><th>Need</th><th>Unit USD</th><th>Net USD</th>
</tr></thead><tbody id="tb"></tbody></table>
<script>
function calc(){
  var q=document.getElementById('q').value;
  var k=document.getElementById('k').value;
  var err=document.getElementById('err');
  err.textContent='';
  fetch('/web_quote/quote?qty='+encodeURIComponent(q)+'&key='+encodeURIComponent(k))
    .then(function(r){ return r.json().then(function(j){ return {s:r.status,j:j}; }); })
    .then(function(x){
      if(x.s!==200){ err.textContent=(x.j&&x.j.error)||('HTTP '+x.s); return; }
      var j=x.j;
      document.getElementById('sum').innerHTML='<p>Qty <b>'+j.qty+'</b> | Full/set <b>'
        +j.full_usd+'</b> USD | Gross <b>'+j.gross_usd+'</b> USD | Net <b>'+j.net_usd
        +'</b> USD</p><p class="mut">'+j.note+'</p>';
      var tb=document.getElementById('tb'); tb.innerHTML='';
      j.lines.forEach(function(l){
        var tr=document.createElement('tr');
        tr.textContent='';
        [l.group,l.code,l.name,l.bom_qty,l.avail,l.need_units,l.unit_usd,l.line_net_usd]
          .forEach(function(v){ var td=document.createElement('td'); td.textContent=v; tr.appendChild(td); });
        tb.appendChild(tr);
      });
      document.getElementById('tbl').style.display='';
    })
    .catch(function(e){ err.textContent='Request failed'; });
}
</script>
</body></html>"""
        return request.make_response(
            html,
            headers=[('Content-Type', 'text/html; charset=utf-8')],
        )

    @http.route('/web_quote/quote', type='http', auth='public', methods=['GET'],
                csrf=False)
    def web_quote_json(self, **kwargs):
        """Return the JSON quote for ``qty`` full-combo sets (read-only).

        @param qty: device count, 1..10000 (else 400).
        @param key: must equal ``ir.config_parameter`` web_quote.key (else 403).
        @return: JSON with qty, full_usd, gross_usd, net_usd, lines.
        """
        if not _quote_key_ok(kwargs.get('key')):
            return _json_response({'error': 'Forbidden'}, status=403)
        try:
            qty = int(kwargs.get('qty') or 0)
        except (TypeError, ValueError):
            return _json_response(
                {'error': 'qty must be an integer 1..10000'}, status=400)
        if qty < _QTY_MIN or qty > _QTY_MAX:
            return _json_response(
                {'error': 'qty must be an integer 1..10000'}, status=400)
        try:
            return _json_response(_build_quote(qty))
        except Exception as exc:
            return _json_response(
                {'error': 'Quote failed: %s' % (exc,)}, status=500)
