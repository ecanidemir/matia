# -*- coding: utf-8 -*-
"""Public web quote page + JSON API (v2: plan engine, slot 0).

Provides two ``auth='public'`` GET routes guarded by a shared secret
(``QUOTE_KEY``) stored in ``ir.config_parameter`` key ``web_quote.key``:

- ``GET /web_quote``: simple HTML page (qty input, key input, result table).
  Inline string, no XML/view file, no manifest ``data`` change.
- ``GET /web_quote/quote?qty=N&key=...``: JSON quote for N full-combo
  (base+screws+outdoor+seat) device sets. Runs the plan engine itself:
  slot 0 targets are set to N x kit recipe qty via ``save_slot`` and the
  plan's own result (``retained_total_usd``) is returned, so the net
  matches the Production Plan page to the cent. Gross = full x N
  (``matia.product.cost`` combos).

NOT read-only: each quote WRITES slot 0 (targets + full tree rebuild).
Slot 0's saved study and RFQ/MO line links are replaced on every call.

Odoo 15 notes: ``auth='public'`` env is unprivileged, so internal calls
use recordset ``.sudo()`` (``Environment.sudo()`` does not exist in 15).
"""
import json

from odoo import _, http
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
    """Run the plan engine on slot 0 with qty in every Needed, return it.

    The entered figure is written as-is into ALL kit-top Needed rows
    (``save_slot(0, ...)``), then the Rebuild path runs
    (``get_tree_with_cost(force=True)``: full re-explosion from live
    master data, no cache). Net = the plan's own ``retained_total_usd``,
    so it matches the Production Plan page to the cent.

    @param qty: device count (int, already validated 1..10000).
    @return: dict with qty, gross_usd, net_usd, full_usd, kits, plan_id.
    """
    cost_env = request.env['matia.product.cost'].sudo()
    slot_env = request.env['matia.procurement.plan'].sudo()
    cap_env = request.env['matia.stock.planning'].sudo()
    try:
        cost_tree = cost_env.get_cost_tree()
        combos = (cost_tree or {}).get('combos') or {}
        full = float(combos.get('full') or 0.0)
        # Girilen rakam tüm Needed satırlarına aynen yazılır: satırlar
        # = 4 kitin üst ürünleri (kapasite gruplarındaki item'lar).
        cap = cap_env.get_capacity_planning_data(
            include_tr=True, include_usa=True, dynamic_targets=[])
        pids = set()
        for _grp in (cap or {}).get('groups', []) or []:
            for _it in _grp.get('items', []) or []:
                try:
                    _pid = int(_it.get('product_id') or 0)
                except (TypeError, ValueError):
                    continue
                if _pid > 0:
                    pids.add(_pid)
        if not pids:
            raise ValueError(_('Kit üst ürünleri bulunamadı.'))
        targets = {str(_pid): int(qty) for _pid in sorted(pids)}
        # Plan motorunun kendisi: slot 0 yaz + Rebuild (force).
        # NOT: slot 0 üzerine yazar (kayıtlı çalışma + RFQ/MO
        # satır bağları yenilenir). Staging'de doğrulanmadan
        # prod'a alınmaz.
        saved = slot_env.save_slot(0, targets)
        res = slot_env.get_tree_with_cost(saved.get('plan_id'), force=True)
        net_total = float(res.get('retained_total_usd') or 0.0)
        kits = [{'kit': (_k.get('key') or ''),
                 'retained_usd': round(float(
                     _k.get('retained_usd') or 0.0), 2)}
                for _k in res.get('retained_kits', []) or []]
        return {
            'qty': int(qty),
            'full_usd': round(full, 2),
            'gross_usd': round(full * int(qty), 2),
            'net_usd': round(net_total, 2),
            'kits': kits,
            'plan_id': res.get('plan_id'),
            'slot': res.get('slot', 0),
            'note': 'Slot 0 plan engine result (all Needed = qty, Rebuild).',
        }
    except Exception as exc:
        return {'error': _('Hesaplama hatası: %s') % exc}


class WebQuoteController(http.Controller):
    """Public quote endpoints (key-guarded, no login; writes slot 0)."""

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
<p class="mut">Base + Screws + Outdoor + Seat per device set. Runs the plan engine on slot 0 (all Needed = qty, Rebuild) — net matches the Production Plan page.</p>
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
<th>Kit</th><th>Retained USD</th>
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
      if(j.error){ err.textContent=j.error; return; }
      document.getElementById('sum').innerHTML='<p>Qty <b>'+j.qty+'</b> | Full/set <b>'
        +j.full_usd+'</b> USD | Gross <b>'+j.gross_usd+'</b> USD | Net <b>'+j.net_usd
        +'</b> USD</p><p class="mut">'+j.note+'</p>';
      var tb=document.getElementById('tb'); tb.innerHTML='';
      (j.kits||[]).forEach(function(l){
        var tr=document.createElement('tr');
        tr.textContent='';
        [l.kit,l.retained_usd]
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
        """Return the JSON quote for ``qty`` full-combo sets (slot 0 engine).

        Writes ``qty`` into every kit-top Needed on slot 0 and runs the
        plan Rebuild, then returns the plan's own totals.

        @param qty: device count, 1..10000 (else 400).
        @param key: must equal ``ir.config_parameter`` web_quote.key (else 403).
        @return: JSON with qty, full_usd, gross_usd, net_usd, kits, plan_id.
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
