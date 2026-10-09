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
<title>Full-Combo Device Quote</title>
<style>
:root{
  --s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--s6:32px;--s7:48px;
  --bg:#f4f5f7;--surface:#ffffff;--border:#e2e5ea;--border-strong:#c9cfd8;
  --ink:#14181d;--ink-2:#3c434d;--mut:#667085;
  --accent:#14365e;--accent-hover:#0d2745;--accent-ink:#ffffff;
  --focus:#1d4ed8;--err-bg:#fef3f2;--err-border:#f3b8b0;--err-ink:#7a271a;
  --radius-s:6px;--radius-m:10px;--radius-l:16px;
  --shadow-s:0 1px 2px rgba(16,24,40,.06);
  --shadow-m:0 4px 16px rgba(16,24,40,.08);
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:1rem;line-height:1.5}
.skip{position:absolute;left:var(--s4);top:-48px;background:var(--ink);color:#fff;padding:var(--s2) var(--s4);border-radius:var(--radius-s);z-index:10;text-decoration:none;font-size:.875rem;transition:top .15s}
.skip:focus{top:var(--s2)}
.wrap{max-width:880px;margin:0 auto;padding:var(--s5) var(--s4) var(--s7)}
.eyebrow{margin:0 0 var(--s2);font-size:.75rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--mut)}
h1{margin:0 0 var(--s2);font-size:1.75rem;line-height:1.2;letter-spacing:-.01em}
.lede{margin:0 0 var(--s5);max-width:62ch;color:var(--ink-2);font-size:1rem}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-l);box-shadow:var(--shadow-m);padding:var(--s4)}
form{display:grid;gap:var(--s4);grid-template-columns:1fr}
.field{display:grid;gap:var(--s1)}
.field label{font-size:.875rem;font-weight:600}
.field .hint{font-size:.75rem;color:var(--mut)}
.field input{width:100%;min-height:44px;padding:.6rem .75rem;font-size:1rem;color:var(--ink);background:#fff;border:1px solid var(--border-strong);border-radius:var(--radius-s)}
.field input:hover{border-color:#9aa3b2}
.btn{min-height:44px;padding:.65rem 1.25rem;font-size:1rem;font-weight:650;color:var(--accent-ink);background:var(--accent);border:1px solid var(--accent);border-radius:var(--radius-s);cursor:pointer;box-shadow:var(--shadow-s)}
.btn:hover{background:var(--accent-hover)}
.btn:disabled{opacity:.65;cursor:wait}
.btn .spin{display:none;width:1em;height:1em;margin-right:.5em;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;border-radius:50%;vertical-align:-.15em}
.btn[aria-busy="true"] .spin{display:inline-block;animation:spin 0.8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
#err{margin:var(--s4) 0 0;border-radius:var(--radius-m);font-size:.9rem}
#err:empty{display:none}
#err:not(:empty){background:var(--err-bg);border:1px solid var(--err-border);color:var(--err-ink);padding:var(--s3) var(--s4)}
#err:not(:empty)::before{content:"! ";font-weight:800}
.results{margin-top:var(--s5)}
.empty{border:1.5px dashed var(--border-strong);border-radius:var(--radius-m);background:var(--surface);padding:var(--s5) var(--s4);text-align:center;color:var(--mut)}
.empty strong{display:block;color:var(--ink);font-size:1.05rem;margin-bottom:var(--s1)}
.stats{display:grid;gap:var(--s3);grid-template-columns:repeat(2,1fr);margin:0 0 var(--s4)}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-m);box-shadow:var(--shadow-s);padding:var(--s3) var(--s4)}
.stat-label{display:block;font-size:.75rem;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--mut);margin-bottom:var(--s1)}
.stat-value{display:block;font-size:1.2rem;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.01em;overflow-wrap:anywhere}
.stat--net{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.stat--net .stat-label{color:#c8d5e5}
.note{margin:0 0 var(--s5);font-size:.85rem;color:var(--mut)}
h2.sub{margin:0 0 var(--s3);font-size:1.1rem;line-height:1.3}
table.kits{border-collapse:collapse;width:100%;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-m);overflow:hidden;box-shadow:var(--shadow-s);font-size:.9rem}
.kits th,.kits td{padding:.65rem .8rem;text-align:left}
.kits thead th{background:#eef0f3;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-2);border-bottom:1px solid var(--border)}
.kits tbody tr+tr td{border-top:1px solid var(--border)}
.kits td.num{font-variant-numeric:tabular-nums;text-align:right}
.kits th.num{text-align:right}
.kits td.kit{font-weight:600;text-transform:capitalize}
.foot{margin:var(--s5) 0 0;font-size:.8rem;color:var(--mut)}
[hidden]{display:none!important}
.loading{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-m);box-shadow:var(--shadow-s);padding:var(--s5) var(--s4);text-align:center}
.loading .ring{width:44px;height:44px;margin:0 auto var(--s3);border:4px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin 0.9s linear infinite}
.loading strong{display:block;font-size:1.05rem;margin-bottom:var(--s1)}
.loading .sub{margin:0 auto var(--s4);max-width:44ch;font-size:.9rem;color:var(--mut)}
.ptrack{height:10px;border-radius:999px;background:#e8ebef;overflow:hidden;margin:0 auto var(--s2);max-width:420px}
.pbar{height:100%;width:0%;border-radius:999px;background:var(--accent);transition:width .4s ease}
.pbar.striped{background-image:linear-gradient(45deg,rgba(255,255,255,.25) 25%,transparent 25%,transparent 50%,rgba(255,255,255,.25) 50%,rgba(255,255,255,.25) 75%,transparent 75%);background-size:1rem 1rem;animation:slide 1s linear infinite}
@keyframes slide{to{background-position:1rem 0}}
.elapsed{margin:0;font-size:.8rem;color:var(--mut);font-variant-numeric:tabular-nums}
.step{margin:var(--s2) 0 0;font-size:.85rem;color:var(--ink-2)}
@media (min-width:640px){
  h1{font-size:2rem}
  .card{padding:var(--s5)}
  form.grid{grid-template-columns:minmax(140px,.85fr) minmax(200px,1.2fr) auto;align-items:end}
  .btn{width:auto;white-space:nowrap}
  .stats{grid-template-columns:repeat(4,1fr)}
}
@media (max-width:639px){
  .stat-value{font-size:1.05rem;overflow-wrap:anywhere}
  .stat--wide,.stat--net{grid-column:1/-1}
  .stat--net .stat-value{font-size:1.35rem}
}
@media (max-width:559px){
  .wrap{padding:var(--s4) var(--s4) var(--s6)}
  .btn{width:100%}
  .kits thead{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
  .kits,.kits tbody,.kits tr,.kits td{display:block;width:100%}
  .kits{background:transparent;border:0;box-shadow:none}
  .kits tbody tr{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-m);box-shadow:var(--shadow-s);margin-bottom:var(--s2);padding:var(--s1) 0}
  .kits td{border:0;display:flex;justify-content:space-between;align-items:baseline;gap:var(--s3);padding:.5rem var(--s4)}
  .kits tbody tr+tr td{border-top:0}
  .kits td[data-label]::before{content:attr(data-label);font-size:.72rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--mut)}
}
@media (prefers-reduced-motion:reduce){
  *{animation:none!important;transition:none!important}
}
</style></head><body>
<a class="skip" href="#main">Skip to calculator</a>
<main class="wrap" id="main">
<header>
<p class="eyebrow">Matia &middot; Device pricing</p>
<h1>Full-combo device quote</h1>
<p class="lede">One complete set includes the base, outdoor unit, and seat. Enter a quantity to see the per-set price, the gross total, and the net amount you still need to buy to reach that quantity.</p>
</header>
<section class="card" aria-labelledby="calc-h">
<h2 class="sub" id="calc-h" style="position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0">Quote calculator</h2>
<form id="fq" class="grid" onsubmit="event.preventDefault();calc();">
<div class="field">
<label for="q">Quantity (sets)</label>
<input id="q" name="qty" type="number" value="100" min="1" max="10000" step="1" inputmode="numeric" aria-describedby="q-hint" required/>
<span class="hint" id="q-hint">Whole number, 1 to 10,000.</span>
</div>
<div class="field">
<label for="k">Access key</label>
<input id="k" name="key" type="password" autocomplete="off" aria-describedby="k-hint" required/>
<span class="hint" id="k-hint">Ask your Matia contact for the key.</span>
</div>
<div><button class="btn" id="go" type="submit" aria-busy="false"><span class="spin" aria-hidden="true"></span><span id="go-t">Calculate</span></button></div>
</form>
<div id="err" role="alert"></div>
</section>
<section class="results" aria-label="Quote results">
<div class="empty" id="empty"><strong>No quote yet</strong>Enter a quantity and your access key, then select Calculate. Results appear here.</div>
<div id="sum" aria-live="polite"></div>
<table class="kits" id="tbl" hidden><thead><tr>
<th scope="col">Kit</th><th scope="col" class="num">Retained USD</th>
</tr></thead><tbody id="tb"></tbody></table>
<p class="foot">Net matches the Production Plan page. Calculated from live data.</p>
</section>
</main>
<script>
var fmtUSD = new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'});
var busy=false, loadTimer=null, loadStart=0, abortCtl=null;
var STEPS=[
  {t:0, msg:'Reading live production data...'},
  {t:5, msg:'Running the plan engine on your quantity...'},
  {t:11, msg:'Adding up kit costs - almost done...'}
];
function money(v){ var n=Number(v); if(!isFinite(n)) return '--'; return fmtUSD.format(n); }
function setLoading(on){
  var b=document.getElementById('go'), t=document.getElementById('go-t');
  b.disabled=on; b.setAttribute('aria-busy', on ? 'true' : 'false');
  t.textContent = on ? 'Calculating...' : 'Calculate';
}
function showError(m){ document.getElementById('err').textContent=m||''; }
function stopLoading(){
  busy=false; setLoading(false);
  if(loadTimer){ clearInterval(loadTimer); loadTimer=null; }
  if(abortCtl){ try{ abortCtl=null; }catch(e){} }
}
function showLoading(sum){
  sum.innerHTML='';
  var box=document.createElement('div'); box.className='loading';
  var ring=document.createElement('div'); ring.className='ring'; ring.setAttribute('aria-hidden','true');
  var strong=document.createElement('strong'); strong.textContent='Calculating your quote...';
  var sub=document.createElement('p'); sub.className='sub';
  sub.textContent='This usually takes about 15 seconds. Please keep this page open.';
  var track=document.createElement('div'); track.className='ptrack';
  track.setAttribute('role','progressbar');
  track.setAttribute('aria-label','Quote calculation progress');
  track.setAttribute('aria-valuemin','0'); track.setAttribute('aria-valuemax','100');
  track.setAttribute('aria-hidden','true');
  var bar=document.createElement('div'); bar.className='pbar striped'; bar.id='pbar';
  track.appendChild(bar);
  var step=document.createElement('p'); step.className='step'; step.id='pstep'; step.textContent=STEPS[0].msg;
  var el=document.createElement('p'); el.className='elapsed'; el.id='pelapsed'; el.textContent='0s elapsed';
  el.setAttribute('aria-hidden','true');
  box.appendChild(ring); box.appendChild(strong); box.appendChild(sub);
  box.appendChild(track); box.appendChild(step); box.appendChild(el);
  sum.appendChild(box);
  loadStart=Date.now();
  var update=function(){
    var s=Math.floor((Date.now()-loadStart)/1000);
    var elN=document.getElementById('pelapsed'), barN=document.getElementById('pbar'), stepN=document.getElementById('pstep');
    if(!elN||!barN){ if(loadTimer){ clearInterval(loadTimer); loadTimer=null; } return; }
    elN.textContent=s+'s elapsed';
    var pct=Math.min(99, Math.round(s/15*100));
    barN.style.width=pct+'%'; track.setAttribute('aria-valuenow', String(pct));
    var msg=STEPS[0].msg;
    for(var i=0;i<STEPS.length;i++){ if(s>=STEPS[i].t){ msg=STEPS[i].msg; } }
    stepN.textContent=msg;
  };
  update();
  loadTimer=setInterval(update, 500);
}
function calc(){
  if(busy){ return; }
  var qEl=document.getElementById('q'), kEl=document.getElementById('k');
  var err=document.getElementById('err');
  var sum=document.getElementById('sum');
  var empty=document.getElementById('empty');
  var tbl=document.getElementById('tbl');
  showError('');
  var q=parseInt(String(qEl.value).trim(),10);
  if(!isFinite(q)||q<1||q>10000){ showError('Enter a whole quantity from 1 to 10,000.'); qEl.focus(); return; }
  if(!kEl.value){ showError('Enter your access key.'); kEl.focus(); return; }
  busy=true; setLoading(true);
  showLoading(sum);
  var url='/web_quote/quote?qty='+encodeURIComponent(q)+'&key='+encodeURIComponent(kEl.value);
  var fetchP;
  try{
    abortCtl=('AbortController' in window) ? new AbortController() : null;
    var opts=abortCtl ? {signal: abortCtl.signal} : undefined;
    fetchP=fetch(url, opts);
    if(abortCtl){ setTimeout(function(){ try{ abortCtl.abort(); }catch(e){} }, 90000); }
  }catch(e){ fetchP=fetch(url); }
  fetchP
    .then(function(r){ return r.json().then(function(j){ return {s:r.status,j:j}; }); })
    .then(function(x){
      stopLoading();
      sum.innerHTML='';
      if(x.s!==200){
        if(x.s===403){ showError('Wrong access key. Check the key and try again.'); }
        else{ showError((x.j&&x.j.error)||('Request failed (HTTP '+x.s+').')); }
        return;
      }
      var j=x.j;
      if(!j||j.error){ showError((j&&j.error)||'Could not calculate this quote.'); return; }
      try{ sessionStorage.setItem('wq_key', kEl.value); }catch(e){}
      empty.hidden=true;
      var stats=document.createElement('div'); stats.className='stats';
      var items=[
        {label:'Quantity', value:String(j.qty), plain:true},
        {label:'Per set', value:money(j.full_usd)},
        {label:'Gross total', value:money(j.gross_usd), wide:true},
        {label:'Net total', value:money(j.net_usd), net:true}
      ];
      items.forEach(function(it){
        var d=document.createElement('div');
        d.className='stat'+(it.net?' stat--net':'')+(it.wide?' stat--wide':'');
        var l=document.createElement('span'); l.className='stat-label'; l.textContent=it.label;
        var v=document.createElement('span'); v.className='stat-value'; v.textContent=it.value;
        d.appendChild(l); d.appendChild(v); stats.appendChild(d);
      });
      sum.appendChild(stats);
      var h=document.createElement('h2'); h.className='sub'; h.textContent='Retained cost by kit';
      sum.appendChild(h);
      var note=document.createElement('p'); note.className='note';
      note.textContent='To complete your stock to '+j.qty+' full device sets, you need '+money(j.net_usd)+' in parts (net total). Buying everything new would cost '+money(j.gross_usd)+' (gross) — the rest is already in stock.';
      sum.appendChild(note);
      var tb=document.getElementById('tb'); tb.innerHTML='';
      var rows=[]; var screwsTotal=0;
      (j.kits||[]).forEach(function(l){
        var key=String(l.kit||'').toLowerCase();
        var val=Number(l.retained_usd); if(!isFinite(val)){ val=0; }
        if(key==='screws'){ screwsTotal=Math.round((screwsTotal+val)*100)/100; return; }
        rows.push({kit:String(l.kit||''), val:val});
      });
      if(screwsTotal>0){
        var baseRow=null;
        for(var bi=0;bi<rows.length;bi++){
          if(String(rows[bi].kit).toLowerCase()==='base'){ baseRow=rows[bi]; break; }
        }
        if(baseRow){ baseRow.val=Math.round((baseRow.val+screwsTotal)*100)/100; }
        else{ rows.push({kit:'base', val:screwsTotal}); }
      }
      rows.forEach(function(r){
        var tr=document.createElement('tr');
        var tdK=document.createElement('td'); tdK.className='kit';
        tdK.setAttribute('data-label','Kit'); tdK.textContent=r.kit;
        var tdV=document.createElement('td'); tdV.className='num';
        tdV.setAttribute('data-label','Retained'); tdV.textContent=money(r.val);
        tr.appendChild(tdK); tr.appendChild(tdV); tb.appendChild(tr);
      });
      tbl.hidden=false;
    })
    .catch(function(e){
      var wasAbort=(e && (e.name==='AbortError'));
      stopLoading(); sum.innerHTML='';
      showError(wasAbort
        ? 'Still working - the server took longer than 90 seconds. Try again in a moment.'
        : 'Request failed. Check your connection and try again.');
    });
}
try{
  var savedKey=sessionStorage.getItem('wq_key');
  if(savedKey){ document.getElementById('k').value=savedKey; }
}catch(e){}
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
