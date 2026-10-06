# -*- coding: utf-8 -*-
"""Matia bulk procurement/production PREVIEW plan (admin-only, preview-only).

Scope (phase 1): enter qty for entry products -> explode full tree -> net
against TR stock -> supplier-based preview + cost. Creates NO records
(no PO/MO).

Future phase (NOT in this file, kept as plan): action_create_drafts()
will create one draft PO per supplier + draft MOs.

Never touch the existing Capacity Plan page: this file is standalone,
shared patterns were copied (no imports).
"""
import calendar
import json
import logging
import math

from odoo import api, fields, models, _
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


# Kit BOMs: same source as the existing Capacity Plan (same ID + name fallback).
# Order is the display order: Base, Outdoor, Seat, Screws last (user rule).
_MPP_KIT_BOMS = [
    {'key': 'base', 'preferred_id': 1766,
     'names': ['TekRMD Common Parts v2', 'TekRMD Common Parts']},
    {'key': 'outdoor', 'preferred_id': 1737,
     'names': ['TekRMD Outdoor Parts']},
    {'key': 'seat', 'preferred_id': 1738,
     'names': ['TekRMD Seat Parts']},
    {'key': 'screws', 'preferred_id': 1736,
     'names': ['TekRMD Common Screws']},
]

_MPP_MAX_LEVEL = 10
_MPP_TR_COMPANY_ID = 1
_MPP_US_COMPANY_ID = 2

# UoM display names are stored in the DB language (TR). The whole preview
# UI is English-only (user rule), so raw names like 'Adet' must never
# reach the client. Same map as the Capacity page (stock_planning.py).
_MPP_UOM_NAME_MAP = {
    'Adet': 'Units',
    'adet': 'Units',
    'Birim': 'Units',
    'birim': 'Units',
    'Kg': 'kg',
    'Metre': 'm',
    'metre': 'm',
    'Paket': 'Pack',
    'paket': 'Pack',
    'Set': 'Set',
    'Takım': 'Set',
    'takım': 'Set',
    'Takim': 'Set',
    'takim': 'Set',
}


def _mpp_uom_en(name):
    """English UoM label for the preview UI.

    @param name: raw uom.uom name from the DB (may be Turkish).
    @return: mapped English name, or the input unchanged when unknown.
    """
    if not name:
        return ''
    return _MPP_UOM_NAME_MAP.get(name, name)


def _mpp_own_partner_ids(env_sudo):
    """Partner IDs of our own companies (never valid sellers).

    Inter-company POs list Matia TR/US as the vendor; the preview must
    skip those lines and use the latest purchase from a real supplier.
    @param env_sudo: sudo environment.
    @return: set of res.partner ids belonging to any company.
    """
    try:
        comps = env_sudo['res.company'].with_context(
            active_test=False).sudo().search_read([], ['partner_id'])
    except Exception:
        return set()
    own = set()
    for comp in comps or []:
        _p = comp.get('partner_id')
        if _p:
            own.add(_p[0] if isinstance(_p, (list, tuple)) else _p)
    return own


def _mpp_env_sudo(self):
    """sudo env covering all companies (proven pattern from this module)."""
    all_company_ids = self.env['res.company'].with_context(
        active_test=False).sudo().search([]).ids
    return self.with_context(
        allowed_company_ids=all_company_ids,
        active_test=False,
    ).sudo().env


def _mpp_line_uom_factor(line):
    """Factor converting a price per PO UoM to price per line UoM.

    Example: last buy 147.96 TRY/m, line UoM mm -> 0.001, so the
    rolled cost uses 0.14796 TRY/mm. Returns 1.0 when UoMs match,
    are missing, or conversion fails (fail-safe: old behaviour).

    @param line: matia.procurement.plan.line record.
    @return: float factor.
    """
    try:
        last_uom = line.last_uom_id
        line_uom = line.uom_id
        if not last_uom or not line_uom:
            return 1.0
        if last_uom.id == line_uom.id:
            return 1.0
        return line_uom._compute_quantity(
            1.0, last_uom, round=False) or 1.0
    except Exception as exc:
        _logger.warning(
            'MPP UoM factor failed for line %s: %s; using 1.0',
            getattr(line, 'id', '?'), exc)
        return 1.0


def _mpp_tr_stock_locs(env_sudo):
    """WHTR/Stock% internal locations (excluding NCR)."""
    locs = env_sudo['stock.location'].search([('usage', '=', 'internal')])
    stock, ncr = [], []
    for loc in locs:
        cname = loc.complete_name or ''
        cid = loc.company_id.id if loc.company_id else False
        if 'WHTR' in cname or cid == _MPP_TR_COMPANY_ID:
            if 'NCR' in cname:
                ncr.append(loc.id)
            elif cname.startswith('WHTR/Stock'):
                stock.append(loc.id)
    return stock, ncr


def _mpp_us_stock_locs(env_sudo):
    """WHUS/Stock% internal locations (excluding NCR)."""
    locs = env_sudo['stock.location'].search([('usage', '=', 'internal')])
    stock = []
    for loc in locs:
        cname = loc.complete_name or ''
        cid = loc.company_id.id if loc.company_id else False
        if ('WHUS' in cname or cid == _MPP_US_COMPANY_ID) \
                and 'NCR' not in cname \
                and cname.startswith('WHUS/Stock'):
            stock.append(loc.id)
    return stock


def _mpp_stock_split(env_sudo, pids):
    """TR + US on-hand/reserved per product (NCR excluded, both sides).

    One read_group per company (was: TR-only in most callers, and the
    entry screen read US on-hand without reserves).
    @param env_sudo: sudo environment.
    @param pids: product IDs.
    @return: {pid: (oh_tr, rs_tr, oh_us, rs_us)} floats, missing -> zeros.
    """
    res = {}
    pids = [p for p in (pids or []) if p]
    if not pids:
        return res
    tr_locs = _mpp_tr_stock_locs(env_sudo)[0]
    us_locs = _mpp_us_stock_locs(env_sudo)
    if tr_locs:
        for sq in env_sudo['stock.quant'].read_group(
                [('product_id', 'in', pids),
                 ('location_id', 'in', tr_locs)],
                ['product_id', 'quantity', 'reserved_quantity'],
                ['product_id']):
            pid = sq['product_id'][0]
            cur = res.setdefault(pid, [0.0, 0.0, 0.0, 0.0])
            cur[0] = float(sq.get('quantity') or 0.0)
            cur[1] = float(sq.get('reserved_quantity') or 0.0)
    if us_locs:
        for sq in env_sudo['stock.quant'].read_group(
                [('product_id', 'in', pids),
                 ('location_id', 'in', us_locs)],
                ['product_id', 'quantity', 'reserved_quantity'],
                ['product_id']):
            pid = sq['product_id'][0]
            cur = res.setdefault(pid, [0.0, 0.0, 0.0, 0.0])
            cur[2] = float(sq.get('quantity') or 0.0)
            cur[3] = float(sq.get('reserved_quantity') or 0.0)
    return {pid: tuple(v) for pid, v in res.items()}


def _mpp_allocate_score(items, counts):
    """Score one count vector against the ideal millimetres.

    @param items: [(pid, size_mm, ideal_mm)] ID-sorted, size > 0.
    @param counts: [units] parallel to items.
    @return: (used_mm, penalty, over_cap): used_mm int, penalty the
        relative squared deviation sum, over_cap the pids whose count
        exceeds ceil(ideal / size) (slack use, never silent).
    """
    used = 0
    penalty = 0.0
    over = []
    for (_pid, _size, _ideal), _n in zip(items, counts):
        _mm = _n * _size
        used += _mm
        if _ideal > 0.0:
            _d = (_mm - _ideal) / _ideal
            penalty += _d * _d
        elif _mm > 0:
            penalty += float(_mm) * float(_mm)
        if _n > int(math.ceil(_ideal / _size - 1e-9)):
            over.append(_pid)
    return used, penalty, over


def _mpp_allocate_fallback(total, items, caps):
    """Largest-remainder handout (pre-exact policy), same result shape.

    Base floor(ideal / size) branches, then +1 units in
    largest-fractional-quota order while the size fits and the cap
    holds. Runs when the exact search space exceeds its ops budget.

    @param total: pool mm (int, >= 0).
    @param items: [(pid, size_mm, ideal_mm)] ID-sorted, size > 0.
    @param caps: [max units] parallel to items.
    @return: same dict shape as _mpp_allocate_exact.
    """
    quotas = [_ideal / _size for (_pid, _size, _ideal) in items]
    counts = []
    for (_q, _cap, (_pid, _size, _ideal)) in zip(quotas, caps, items):
        _n = int(math.floor(_q)) if _q > 0 else 0
        counts.append(min(max(0, _n), _cap, total // _size))
    if total - sum(n * s for n, (_p, s, _i) in zip(counts, items)) > 0:
        order = sorted(
            range(len(items)),
            key=lambda i: (-(quotas[i] - math.floor(quotas[i])),
                           -items[i][2]))
        for _i in order:
            while counts[_i] < caps[_i] and \
                    total - sum(n * s for n, (_p, s, _ii)
                                in zip(counts, items)) >= items[_i][1]:
                counts[_i] += 1
    used, penalty, over = _mpp_allocate_score(items, counts)
    return {'allocation': {pid: n for (pid, _s, _i), n in
                           zip(items, counts)},
            'used_mm': used, 'waste_mm': total - used,
            'penalty': penalty, 'over_cap': over}


def _mpp_allocate_exact(total_stock, parents, waste_band=0, slack=1,
                        ops_budget=2000000):
    """Split one shared pool by exact bounded enumeration (display only).

    Replaces the largest-remainder handout: every feasible count vector
    inside the per-parent caps is scored and the best one wins. Typical
    pools have a handful of parents with tiny caps, so full enumeration
    is cheap; huge inputs fall back to _mpp_allocate_fallback (same
    result shape, old policy).

    Objective: the least waste wins (a capacity screen must not strand
    stock to look fairer); ties are broken by the smallest relative
    squared deviation from the ideal millimetres, then by enumeration
    order (ascending counts over ID-sorted parents), so output is
    deterministic. @waste_band optionally widens the tie zone: vectors
    whose waste fits inside the band are compared by deviation first
    (larger bands trade leftover for proportionality); the default 0
    means waste is always minimized first.

    @param total_stock: shared pool in mm (float ok, rounded to int,
        negatives guarded to 0).
    @param parents: [{'id': pid, 'size': usage_mm,
        'ideal_mm': fair mm}]. Size <= 0 parents are skipped (get no
        branch entry, same as the floor pass).
    @param waste_band: tie-zone width in mm (default 0: waste is
        always minimized first; larger values trade leftover for
        proportionality).
    @param slack: extra units above ceil(ideal / size) a parent may take
        to close waste (reported in over_cap, never silent).
    @param ops_budget: max combos * parents for the exact search.
    @return: {'allocation': {pid: int}, 'used_mm': int,
        'waste_mm': int, 'penalty': float, 'over_cap': [pid]}.
    """
    try:
        total = max(0, int(round(float(total_stock or 0.0))))
    except (TypeError, ValueError):
        total = 0
    try:
        band = max(0, int(waste_band))
    except (TypeError, ValueError):
        band = 200
    try:
        slack = max(0, int(slack or 0))
    except (TypeError, ValueError):
        slack = 0
    items = []
    for _p in parents or []:
        try:
            _pid = _p.get('id')
            _size = int(round(float(_p.get('size') or 0.0)))
            _ideal = float(_p.get('ideal_mm') or 0.0)
        except (TypeError, ValueError, AttributeError):
            continue
        if _pid is None or _size <= 0:
            continue
        items.append((_pid, _size, max(0.0, _ideal)))
    try:
        items.sort(key=lambda r: r[0])
    except TypeError:
        items.sort(key=lambda r: str(r[0]))
    empty = {pid: 0 for (pid, _s, _i) in items}
    if not items or total <= 0:
        return {'allocation': empty, 'used_mm': 0, 'waste_mm': total,
                'penalty': 0.0, 'over_cap': []}
    caps = []
    for (_pid, _size, _ideal) in items:
        _cap = int(math.ceil(_ideal / _size - 1e-9)) + slack
        caps.append(min(max(0, _cap), total // _size))
    combos = 1
    for _c in caps:
        combos *= (_c + 1)
        if combos * len(items) > ops_budget:
            return _mpp_allocate_fallback(total, items, caps)
    sizes = [_s for (_p, _s, _i) in items]
    counts = [0] * len(items)
    best_in = None   # (penalty, counts): waste fits the band
    best_out = None  # (waste, penalty, counts): nothing fits the band

    def _walk(_i, _used):
        """Depth-first count enumeration with over-use pruning."""
        nonlocal best_in, best_out
        if _i >= len(items):
            _used_l, _pen_l, _over_l = _mpp_allocate_score(items, counts)
            _waste = total - _used_l
            if _waste <= band:
                if best_in is None or _pen_l < best_in[0]:
                    best_in = (_pen_l, list(counts))
            elif best_out is None or (_waste, _pen_l) < (
                    best_out[0], best_out[1]):
                best_out = (_waste, _pen_l, list(counts))
            return
        for _n in range(caps[_i] + 1):
            _nu = _used + _n * sizes[_i]
            if _nu > total:
                break
            counts[_i] = _n
            _walk(_i + 1, _nu)
        counts[_i] = 0

    _walk(0, 0)
    _final = best_in[1] if best_in is not None else best_out[2]
    used, penalty, over = _mpp_allocate_score(items, _final)
    return {'allocation': {pid: n for (pid, _s, _i), n in
                           zip(items, _final)},
            'used_mm': used, 'waste_mm': total - used,
            'penalty': penalty, 'over_cap': over}


def _mpp_par_notes(par_count, contrib, edges, codes):
    """Build short 'used elsewhere' tooltips for shared children.

    A row shows the note only when its OWN product is used by more
    than one parent inside this plan's trees (never the bottleneck
    child's sharing). The tooltip lists where (parent code) and how
    many per parent (BOM usage qty); no pool/distribution amounts.

    @param par_count: {child id: distinct net-contributing parents}.
    @param contrib: {(parent id, child id): net units pushed}.
    @param edges: {parent id: {child id: usage qty}}.
    @param codes: {product id: short ASCII code for display}.
    @return: {child id: 'Also used in: CODE xQTY, ...'} for children
        with more than one parent. English + ASCII only.
    """
    notes = {}
    for _cc, _n in (par_count or {}).items():
        try:
            _ok = int(_n) > 1
        except (TypeError, ValueError):
            continue
        if not _ok:
            continue
        _rows = []
        for (_pp, _c2), _ct in (contrib or {}).items():
            if _c2 != _cc:
                continue
            try:
                _pushed = float(_ct or 0.0)
            except (TypeError, ValueError):
                continue
            if _pushed <= 0:
                continue
            try:
                _q = float((edges.get(_pp, {}) or {}).get(_cc, 0.0))
            except (TypeError, ValueError):
                _q = 0.0
            _qi = int(_q)
            _qs = str(_qi) if _q == _qi else str(round(_q, 2))
            _code = codes.get(_pp) or ('id%s' % _pp)
            _rows.append((_code, '%s x%s' % (_code, _qs)))
        if not _rows:
            continue
        _rows.sort(key=lambda r: r[0])
        _segs = [r[1] for r in _rows[:10]]
        if len(_rows) > 10:
            _segs.append('+%s more' % (len(_rows) - 10))
        # Tooltip lands in an HTML title attribute: no double quotes.
        notes[_cc] = ('Also used in: ' + ', '.join(
            _segs)).replace('"', "'")
    return notes


def _mpp_load_pools(pool_json):
    """Parse a stored bottom-up producible snapshot.

    @param pool_json: content of matia.procurement.plan.producible_json.
    @return: (pool, branch, share, driver, notes, par_n) where pool maps
        product id -> bottom-up units (float), branch maps
        (parent id, child id) -> allocated units (int), share maps
        (parent id, child id) -> (pct of child pool, parent count),
        driver maps parent id -> its min-branch child id, notes maps
        child id -> the short 'Also used in: CODE xQTY, ...' tooltip
        ('' when the plan predates notes), and par_n maps child id ->
        its distinct parent count. Unparseable input yields empty
        dicts so callers fall back to the legacy own-stock formula.
    """
    try:
        data = json.loads(pool_json or '{}')
    except ValueError:
        return {}, {}, {}, {}, {}
    pool = {}
    try:
        for _k, _v in (data.get('pool') or {}).items():
            pool[int(_k)] = float(_v)
    except (TypeError, ValueError):
        pass
    branch = {}
    for _k, _v in (data.get('branch') or {}).items():
        try:
            _p, _c = str(_k).split('>')
            branch[(int(_p), int(_c))] = int(_v)
        except (TypeError, ValueError):
            continue
    share = {}
    for _k, _v in (data.get('share') or {}).items():
        try:
            _p, _c = str(_k).split('>')
            _pct, _n = list(_v)[:2]
            share[(int(_p), int(_c))] = (float(_pct), int(_n))
        except (TypeError, ValueError):
            continue
    driver = {}
    for _k, _v in (data.get('driver') or {}).items():
        try:
            driver[int(_k)] = int(_v)
        except (TypeError, ValueError):
            continue
    notes = {}
    for _k, _v in (data.get('par_note') or {}).items():
        try:
            notes[int(_k)] = str(_v)
        except (TypeError, ValueError):
            continue
    par_n = {}
    for _k, _v in (data.get('par_n') or {}).items():
        try:
            par_n[int(_k)] = int(_v)
        except (TypeError, ValueError):
            continue
    return pool, branch, share, driver, notes, par_n


def _mpp_find_kit_boms(env_sudo):
    """Find the 4 kit BOMs, ID-first with name fallback."""
    found = []
    for cfg in _MPP_KIT_BOMS:
        bom = False
        pref = env_sudo['mrp.bom'].browse(cfg['preferred_id'])
        if pref.exists() and pref.active:
            bom = pref
        if not bom:
            for n in cfg['names']:
                bom = env_sudo['mrp.bom'].search(
                    [('product_tmpl_id.name', '=', n)], limit=1)
                if bom:
                    break
        if not bom:
            for n in cfg['names']:
                bom = env_sudo['mrp.bom'].search([
                    '|',
                    ('product_tmpl_id.name', 'ilike', n),
                    ('code', 'ilike', n),
                ], limit=1)
                if bom:
                    break
        if bom:
            found.append({'key': cfg['key'], 'bom': bom})
    return found


class MatiaProcurementPlan(models.Model):
    _name = 'matia.procurement.plan'
    _description = 'Matia Bulk Procurement/Production Preview Plan'
    _order = 'id desc'

    name = fields.Char(required=True, default=lambda self: _('New'))
    company_id = fields.Many2one(
        'res.company', required=True, default=_MPP_TR_COMPANY_ID,
        help='Owning company of the plan (currency/origin). '
             'Stock netting covers TR + US warehouses.')
    state = fields.Selection([
        ('draft', 'Draft (qty entry)'),
        ('calculated', 'Net requirement calculated'),
        ('supplier_review', 'Supplier preview'),
        # ('done', ...) : FUTURE PHASE (draft PO/MO creation). Not yet.
    ], default='draft', required=True)
    target_json = fields.Text(
        help='JSON: {product_id: qty} - Screen 1 entries.')
    edge_json = fields.Text(
        help='JSON: {parent_id: {child_id: qty}} - BOM edges for '
             'rolled-up cost (Screen 2 output).')
    built_target_json = fields.Text(
        help='Copy of target_json the lines were built from. '
             'get_tree_with_cost skips the full rebuild when it '
             'still matches (cached view: no unlink/recreate).')
    producible_json = fields.Text(
        help='JSON: {"pool": {product_id: bottom-up units}, '
              '"branch": {"parent>child": allocated units}, '
              '"par_n": {child_id: parent count}, '
              '"par_note": {child_id: "Also used in: ..." tooltip}} - '
              'display-only producible snapshot written by '
              'action_explode_and_net.')
    currency_id = fields.Many2one(
        'res.currency', help='Total cost currency (default company).')
    total_cost = fields.Float(compute='_compute_total_cost', store=True)
    line_count = fields.Integer(compute='_compute_line_count', store=True)
    note = fields.Text()
    line_ids = fields.One2many('matia.procurement.plan.line', 'plan_id')
    mo_ids = fields.Many2many(
        'mrp.production', string='Manufacturing Orders', readonly=True,
        help='Draft MOs created from this plan (make lines). '
             'Existing records are never deleted by this module.')
    mo_count = fields.Integer(compute='_compute_mo_count', store=True)
    create_date = fields.Datetime(readonly=True)
    create_uid = fields.Many2one('res.users', readonly=True)

    @api.depends('line_ids.subtotal')
    def _compute_total_cost(self):
        for plan in self:
            plan.total_cost = sum(plan.line_ids.mapped('subtotal'))

    @api.depends('line_ids')
    def _compute_line_count(self):
        for plan in self:
            plan.line_count = len(plan.line_ids)

    @api.depends('mo_ids')
    def _compute_mo_count(self):
        """Count linked manufacturing orders.

        @param self: plan recordset.
        @return: None (sets mo_count).
        """
        for plan in self:
            plan.mo_count = len(plan.mo_ids)

    # ------------------------------------------------------------------
    # Screen 1: entry products (125 top products, TR+USA stock indicators)
    # ------------------------------------------------------------------
    @api.model
    def get_entry_products(self):
        """ONLY the top products of the 4 kits (no sub-products). Read-only."""
        env_sudo = _mpp_env_sudo(self)
        kits = _mpp_find_kit_boms(env_sudo)
        if not kits:
            raise UserError(_('Kit BOMs not found.'))

        top_map = {}  # pid -> {'kit_key': ...}
        for kit in kits:
            for line in kit['bom'].bom_line_ids:
                p = line.product_id
                if p.id not in top_map:
                    top_map[p.id] = {
                        'product_id': p.id,
                        'product_code': p.default_code or '',
                        'product_name': p.name or '',
                        'display_name': p.display_name or p.name,
                        'kit_key': kit['key'],
                    }

        pids = list(top_map)
        # Legacy entry endpoint (the Tab 1 UI is gone, but external
        # scripts may still call this). TR + US unreserved, NCR excluded.
        split = _mpp_stock_split(env_sudo, pids)

        items = []
        for pid, info in sorted(
                top_map.items(),
                key=lambda kv: kv[1]['display_name'] or ''):
            oh_t, rs_t, oh_u, rs_u = split.get(pid, (0.0, 0.0, 0.0, 0.0))
            a_t = max(0.0, oh_t - rs_t)
            a_u = max(0.0, oh_u - rs_u)
            items.append(dict(
                info,
                stock_tr=oh_t,
                reserved_tr=rs_t,
                avail_tr=a_t,
                stock_usa=oh_u,
                reserved_usa=rs_u,
                avail_usa=a_u,
                # Fill-to-N base: physical on-hand TR+USA, reserves
                # ignored (user rule for the Fill-to-N button).
                fill_base=max(0.0, oh_t + oh_u),
                qty_input=0,
            ))
        return {'items': items, 'total': len(items)}

    @api.model
    def create_plan(self, items):
        """Screen 1 confirm: opens a plan header with {product_id: qty}."""
        targets = {}
        for row in items or []:
            try:
                pid = int(row.get('product_id') or 0)
                qty = int(row.get('qty_input') or 0)
            except (TypeError, ValueError):
                continue
            if pid > 0 and qty > 0:
                targets[str(pid)] = qty
        if not targets:
            raise UserError(_('Enter a quantity for at least one product.'))
        company = self.env['res.company'].browse(_MPP_TR_COMPANY_ID)
        seq = self.env['ir.sequence'].sudo().next_by_code(
            'matia.procurement.plan') or _('MPP')
        plan = self.sudo().create({
            'name': seq,
            'company_id': company.id,
            'state': 'draft',
            'target_json': json.dumps(targets),
            'currency_id': company.currency_id.id,
        })
        return {'plan_id': plan.id, 'name': plan.name}

    # ------------------------------------------------------------------
    # Screen 2: explosion + TR netting (read-only sources, writes plan lines)
    # ------------------------------------------------------------------
    @api.model
    def action_explode_and_net(self, plan_id):
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            raise UserError(_('Plan not found.'))
        try:
            targets = json.loads(plan.target_json or '{}')
        except ValueError:
            targets = {}
        targets = {int(k): int(v) for k, v in targets.items()
                   if int(v or 0) > 0}
        if not targets:
            raise UserError(_('No target quantities on the plan.'))

        Product = env_sudo['product.product']
        Bom = env_sudo['mrp.bom']

        # Bulk BOM cache: BOMs of all related templates (chunked).
        tmpl_of = {}
        prods = Product.browse(list(targets)).read(
            ['product_tmpl_id'])
        for pr in prods:
            tmpl_of[pr['id']] = pr['product_tmpl_id'][0]

        bom_cache = {}  # tmpl_id -> bom record
        need = {}       # pid -> gross
        meta = {}       # pid -> {'level':min, 'paths':set, 'route':..}
        edges = {}      # parent pid -> {child pid: qty per parent unit}
        btype = {}      # pid -> bom type ('phantom' passes demand through)
        stack = [(pid, float(qty), 0, 'root')
                 for pid, qty in targets.items()]

        tmpl_ids_to_load = set(tmpl_of.values())
        loaded_tmpls = set()

        def _load_boms(tmpl_ids):
            todo = [t for t in tmpl_ids if t not in loaded_tmpls]
            for i in range(0, len(todo), 200):
                chunk = todo[i:i + 200]
                for b in Bom.search(
                        [('product_tmpl_id', 'in', chunk)]):
                    # Prefer product-variant BOM over template BOM
                    key = b.product_tmpl_id.id
                    if key not in bom_cache or b.product_id:
                        bom_cache[key] = b
                    loaded_tmpls.add(key)

        _load_boms(tmpl_ids_to_load)
        iter_guard = 0
        while stack:
            iter_guard += 1
            if iter_guard > 60000:
                raise UserError(
                    _('Tree too deep/wide, explosion limited.'))
            pid, mult, level, path = stack.pop()
            if level > _MPP_MAX_LEVEL:
                continue
            prod = Product.browse(pid)
            if not prod.exists():
                continue
            tmpl_id = prod.product_tmpl_id.id
            if tmpl_id not in loaded_tmpls:
                _load_boms([tmpl_id])
            bom = bom_cache.get(tmpl_id)
            if not bom:
                # Leaf: purchased part (with the multiplier from above)
                need[pid] = need.get(pid, 0.0) + mult
                m = meta.setdefault(pid, {'level': level,
                                         'paths': set()})
                m['level'] = min(m['level'], level)
                m['paths'].add(path)
                continue
            if bom.type == 'phantom':
                # Kit: not a line, carry the multiplier.
                # Edges still recorded so rolled cost flows through.
                # Phantom passes the FULL demand down (no stock held).
                btype[pid] = 'phantom'
                edge = edges.setdefault(pid, {})
                for bl in bom.bom_line_ids:
                    edge.setdefault(bl.product_id.id,
                                    float(bl.product_qty or 1.0))
                    stack.append((bl.product_id.id,
                                  mult * float(bl.product_qty or 1.0),
                                  level, path))
                continue
            # normal / subcontract: record need + explode below
            need[pid] = need.get(pid, 0.0) + mult
            btype[pid] = bom.type or 'normal'
            m = meta.setdefault(pid, {'level': level, 'paths': set()})
            m['level'] = min(m['level'], level)
            m['paths'].add(path)
            for bl in bom.bom_line_ids:
                child_path = '%s>%s' % (path, pid)
                if bl.product_id.id in child_path.split('>'):
                    continue  # cycle protection
                edges.setdefault(pid, {}).setdefault(
                    bl.product_id.id, float(bl.product_qty or 1.0))
                stack.append((bl.product_id.id,
                              mult * float(bl.product_qty or 1.0),
                              level + 1, child_path))

        if not need:
            raise UserError(_('Explosion returned no products.'))

        # TR + US stock (single read_group per company) + info columns.
        # Netting, producible pools and purchase math all run on the
        # COMBINED unreserved total (user rule); the per-company split
        # is kept on the lines for the TR / US display columns.
        pids = list(need)
        all_net_pids = set(need) | set(edges)
        for _ep, _ech in edges.items():
            all_net_pids.update(_ech)
        split = _mpp_stock_split(env_sudo, list(all_net_pids))
        onhand, reserv = {}, {}
        onhand_us, reserv_us = {}, {}
        for _pid, (_oht, _rst, _ohu, _rsu) in split.items():
            onhand[_pid] = max(0.0, _oht)
            reserv[_pid] = max(0.0, _rst)
            onhand_us[_pid] = max(0.0, _ohu)
            reserv_us[_pid] = max(0.0, _rsu)

        # Net cascade (user rule): targets seed demand; nodes are
        # processed parent-first (Kahn topological order over edges).
        # Each node deducts its own avail from its demand, and children
        # receive only the NET qty x usage. Phantom nodes hold no stock
        # and pass the full demand through. Shared sub-products
        # accumulate demand from every parent before they are netted.
        # (all_net_pids was collected above, before the stock read.)
        avail_map = {}
        for _ap in all_net_pids:
            _a_tr = max(0.0, onhand.get(_ap, 0.0) - reserv.get(_ap, 0.0))
            _a_us = max(0.0, onhand_us.get(_ap, 0.0)
                        - reserv_us.get(_ap, 0.0))
            avail_map[_ap] = _a_tr + _a_us
        demand = {pid: 0.0 for pid in all_net_pids}
        for pid, qty in targets.items():
            if pid in demand:
                demand[pid] += float(qty)
        indeg = {pid: 0 for pid in all_net_pids}
        for _pp, _ch in edges.items():
            if _pp not in indeg:
                continue
            for _cc in _ch:
                if _cc in indeg:
                    indeg[_cc] += 1
        _queue = [pid for pid in all_net_pids if indeg[pid] == 0]
        topo = []
        while _queue:
            _p = _queue.pop(0)
            topo.append(_p)
            for _c in edges.get(_p, {}):
                if _c not in indeg:
                    continue
                indeg[_c] -= 1
                if indeg[_c] == 0:
                    _queue.append(_c)
        for _p in all_net_pids:  # cycle leftovers go last
            if _p not in topo:
                topo.append(_p)
        net_map = {}
        contrib = {}  # (parent, child) -> net units P pushes to C
        for _p in topo:
            _d = demand.get(_p, 0.0)
            if btype.get(_p) == 'phantom':
                _n = _d
            else:
                _n = _d - avail_map.get(_p, 0.0)
                if _n < 0:
                    _n = 0.0
            net_map[_p] = _n
            for _c, _q in edges.get(_p, {}).items():
                if _c in demand:
                    try:
                        _add = _n * float(_q or 0.0)
                    except (TypeError, ValueError):
                        continue
                    demand[_c] += _add
                    contrib[(_p, _c)] = contrib.get(
                        (_p, _c), 0.0) + _add

        # Bottom-up producible pools (display only, purchase math
        # untouched): pool(X) = own stock + min over children of
        # floor(share(C->X) / usage). A shared child's pool is split
        # among its parents proportional to each parent's NET
        # contribution (demand-weighted); own stock never moves.
        # Reverse topo order settles children before parents.
        # Phantom nodes hold no stock (own = 0, pass-through).
        pool_map, branch_map = {}, {}
        for _x in reversed(topo):
            _kids = edges.get(_x, {}) or {}
            _own = 0.0 if btype.get(_x) == 'phantom' else \
                avail_map.get(_x, 0.0)
            if not _kids:
                pool_map[_x] = _own
                continue
            _mins = []
            for _c, _q in _kids.items():
                try:
                    _usage = float(_q or 0.0)
                except (TypeError, ValueError):
                    continue
                _inflow = demand.get(_c, 0.0)
                if _inflow > 0 and _usage > 0:
                    _share = pool_map.get(_c, 0.0) * contrib.get(
                        (_x, _c), 0.0) / _inflow
                else:
                    _share = 0.0
                _b = int(math.floor(_share / _usage)) \
                    if _usage > 0 and _share > 0 else 0
                branch_map[(_x, _c)] = _b
                _mins.append(_b)
            pool_map[_x] = _own + min(_mins) if _mins else _own

        # Exact-enumeration redistribution of stranded pool leftovers
        # (display only, purchase math untouched): independent floor()
        # per branch can leave a divisible remainder unused (live
        # E1CBRN06: pool 5000mm, floor branches used 4100, 900 left,
        # while 500x2 + 810x2 + 590x2 + 400x3 = 5000 exactly). For
        # each child, _mpp_allocate_exact() scores every feasible count
        # vector inside ceil(ideal) + slack caps and keeps the least
        # waste one (ties by relative deviation, then enumeration
        # order). Slack use is reported in over_cap,
        # never silent. Children are settled bottom-up (reverse topo,
        # each child once), then each parent's pool is refreshed from
        # the final branches.
        _by_child = {}
        for _pp, _ch in edges.items():
            for _cc, _q in _ch.items():
                try:
                    _u = float(_q or 0.0)
                except (TypeError, ValueError):
                    continue
                if _u > 0:
                    _by_child.setdefault(_cc, []).append((_pp, _u))
        _alloc = {}  # child id -> distribution detail for the tooltip
        _done_kids = set()
        for _x in reversed(topo):
            for _cc in (edges.get(_x, {}) or {}):
                if _cc in _done_kids:
                    continue
                _done_kids.add(_cc)
                _cpool = pool_map.get(_cc, 0.0)
                _inflow = demand.get(_cc, 0.0)
                _plist = _by_child.get(_cc, [])
                if _cpool > 0 and _inflow > 0 and _plist:
                    _pin = []
                    for (_pp, _u) in _plist:
                        _pin.append({
                            'id': _pp,
                            'size': _u,
                            'ideal_mm': _cpool * contrib.get(
                                (_pp, _cc), 0.0) / _inflow,
                        })
                    _res = _mpp_allocate_exact(max(0.0, _cpool), _pin)
                    _parts = []
                    for _pp, _cnt in _res['allocation'].items():
                        try:
                            _cnt = int(_cnt)
                        except (TypeError, ValueError):
                            _cnt = 0
                        branch_map[(_pp, _cc)] = _cnt
                        if _cnt > 0:
                            _us = next(
                                (_pp2.get('size') for _pp2 in _pin
                                 if _pp2.get('id') == _pp), 0)
                            try:
                                _ui = int(round(float(_us or 0.0)))
                            except (TypeError, ValueError):
                                _ui = 0
                            _parts.append((_pp, _cnt, _ui))
                    _alloc[_cc] = {
                        'pool': _cpool,
                        'used': float(_res.get('used_mm') or 0.0),
                        'parts': _parts,
                        'over_cap': list(_res.get('over_cap') or []),
                    }
            _own2 = 0.0 if btype.get(_x) == 'phantom' else \
                avail_map.get(_x, 0.0)
            _kids2 = edges.get(_x, {}) or {}
            _mins2 = [branch_map.get((_x, _c2), 0) for _c2 in _kids2]
            pool_map[_x] = _own2 + min(_mins2) if _mins2 else _own2

        # Share info for the display note (which branches split a
        # child's pool): pct of the child's pool this parent received
        # + how many parents share it. Driver = min-branch child.
        share_map, driver_map = {}, {}
        _par_count = {}
        for (_pp, _cc), _ct in contrib.items():
            if _ct > 0:
                _par_count[_cc] = _par_count.get(_cc, 0) + 1
        for (_pp, _cc) in branch_map:
            _inflow = demand.get(_cc, 0.0)
            _pct = 100.0 * contrib.get((_pp, _cc), 0.0) / _inflow \
                if _inflow > 0 else 0.0
            share_map[(_pp, _cc)] = (round(_pct, 1),
                                     _par_count.get(_cc, 1))
        for _pp, _ch in edges.items():
            _best, _best_c = None, None
            for _cc in _ch:
                _b = branch_map.get((_pp, _cc))
                if _b is None:
                    continue
                if _best is None or _b < _best:
                    _best, _best_c = _b, _cc
            if _best_c is not None:
                driver_map[_pp] = _best_c

        # Info: confirmed incoming POs + open MO output (NOT netted, display only)
        incoming, mo_out = {}, {}
        po_ids = env_sudo['purchase.order'].search([
            ('company_id', 'in', [_MPP_TR_COMPANY_ID, _MPP_US_COMPANY_ID]),
            ('state', 'in', ['purchase', 'done']),
        ])
        if po_ids:
            for g in env_sudo['purchase.order.line'].read_group(
                    [('order_id', 'in', po_ids.ids),
                     ('product_id', 'in', pids)],
                    ['product_id', 'product_qty'],
                    ['product_id']):
                incoming[g['product_id'][0]] = float(
                    g.get('product_qty') or 0.0)
        mo_ids = env_sudo['mrp.production'].search([
            ('company_id', 'in', [_MPP_TR_COMPANY_ID, _MPP_US_COMPANY_ID]),
            ('state', 'in', ['confirmed', 'progress', 'to_close']),
        ])
        if mo_ids:
            for g in env_sudo['mrp.production'].read_group(
                    [('id', 'in', mo_ids.ids)],
                    ['product_id', 'product_qty'],
                    ['product_id']):
                if g.get('product_id'):
                    mo_out[g['product_id'][0]] = float(
                        g.get('product_qty') or 0.0)

        # Route + UoM info (bulk read)
        prod_info = {}
        for pr in Product.browse(pids).read([
                'default_code', 'name', 'display_name', 'uom_id',
                'route_ids', 'purchase_ok', 'detailed_type',
                'product_tmpl_id']):
            prod_info[pr['id']] = pr
        # Phantom parents hold no stock (not in need) so they miss
        # prod_info; their codes are needed for the 'used elsewhere'
        # tooltip (one extra read, parents only).
        _missing_codes = [pid for pid in edges if pid not in prod_info]
        if _missing_codes:
            for pr in Product.browse(_missing_codes).read(
                    ['default_code']):
                prod_info[pr['id']] = pr
        _codes = {}
        for _pid in edges:
            _codes[_pid] = (prod_info.get(_pid, {}) or {}).get(
                'default_code') or ('id%s' % _pid)
        _par_notes = _mpp_par_notes(_par_count, contrib, edges, _codes)
        route_names = {}
        all_route_ids = set()
        for pr in prod_info.values():
            all_route_ids.update(pr.get('route_ids') or [])
        if all_route_ids:
            for r in env_sudo['stock.location.route'].browse(
                    list(all_route_ids)).read(['name']):
                route_names[r['id']] = r['name']

        # Clear old lines, rewrite (preview is repeatable)
        plan.line_ids.unlink()
        lines = []
        for pid, gross in need.items():
            info = prod_info.get(pid, {})
            oh = max(0.0, onhand.get(pid, 0.0))
            rs = max(0.0, reserv.get(pid, 0.0))
            oh_u = max(0.0, onhand_us.get(pid, 0.0))
            rs_u = max(0.0, reserv_us.get(pid, 0.0))
            avail = max(0.0, oh - rs) + max(0.0, oh_u - rs_u)
            # Net comes from the cascade (demand minus own avail,
            # children already fed with this net). Gross stays raw.
            netf = net_map.get(pid, max(0.0, gross - avail))
            net_qty = int(math.ceil(netf)) if netf > 0 else 0
            rnames = [route_names.get(rid, '')
                      for rid in (info.get('route_ids') or [])]
            if any('Subcontract' in (n or '') for n in rnames):
                route = 'subcontract'
            elif any('Manufacture' in (n or '') for n in rnames):
                route = 'make'
            elif any('Buy' in (n or '') for n in rnames):
                route = 'buy'
            else:
                route = 'buy' if info.get(
                    'purchase_ok') else 'unknown'
            uom = info.get('uom_id') or False
            lines.append({
                'plan_id': plan.id,
                'product_id': pid,
                'level': meta.get(pid, {}).get('level', 0),
                'gross_qty': gross,
                'stock_tr': oh,
                'reserved_tr': rs,
                'avail_tr': max(0.0, oh - rs),
                'stock_us': oh_u,
                'reserved_us': rs_u,
                'avail_us': max(0.0, oh_u - rs_u),
                'incoming_info': incoming.get(pid, 0.0),
                'open_mo_info': mo_out.get(pid, 0.0),
                'net_qty': net_qty,
                'order_qty': net_qty,
                'uom_id': uom[0] if uom else False,
                'route_type': route,
            })
        env_sudo['matia.procurement.plan.line'].create(lines)
        plan.edge_json = json.dumps(
            {str(p): {str(c): q for c, q in ch.items()}
             for p, ch in edges.items()})
        plan.producible_json = json.dumps({
            'pool': {str(k): v for k, v in pool_map.items()},
            'branch': {'%s>%s' % (p, c): v
                       for (p, c), v in branch_map.items()},
            'share': {'%s>%s' % (p, c): [pct, n]
                      for (p, c), (pct, n) in share_map.items()},
            'driver': {str(p): c for p, c in driver_map.items()},
            'par_n': {str(k): v for k, v in _par_count.items()
                      if v > 1},
            'par_note': {str(k): v for k, v in _par_notes.items()},
        })
        plan.state = 'calculated'
        plan.built_target_json = plan.target_json
        return self._plan_summary(env_sudo, plan)

    # ------------------------------------------------------------------
    # Screen 3: supplier assignment + cost preview (writes: plan lines only)
    # Last purchase price is shown in its own currency plus a USD
    # conversion using the USD rate of the last purchase date.
    # ------------------------------------------------------------------
    @api.model
    def _mpp_price_in_plan_currency(self, env_sudo, plan, price,
                                    cur_id, label):
        """Convert a price to the plan currency (fail-fast, clear msg).

        Both supplier-preview branches (last-buy and pricelist) used to
        call ``res.currency._convert`` unguarded, so a missing rate
        crashed the whole preview with a raw traceback. Centralized
        here: returns the converted amount, or raises a UserError that
        names the product and the missing rate direction (the technical
        detail goes to the server log, not the dialog).
        @param env_sudo: sudo environment.
        @param plan: matia.procurement.plan record.
        @param price: amount in the source currency.
        @param cur_id: source res.currency id (False = plan currency).
        @param label: product label for the error message.
        @return: price in plan.currency_id.
        """
        if not cur_id or not plan.currency_id \
                or cur_id == plan.currency_id.id:
            return float(price or 0.0)
        cur_rec = env_sudo['res.currency'].browse(cur_id)
        try:
            return cur_rec._convert(
                float(price or 0.0), plan.currency_id,
                plan.company_id, fields.Date.today())
        except Exception as exc:
            _logger.warning(
                'MPP supplier preview: FX %s -> %s failed: %s',
                cur_rec.name,
                plan.currency_id.name if plan.currency_id else '?',
                exc)
            raise UserError(_(
                'Currency conversion failed for %s: no usable rate '
                'from %s to %s. Set the rate and run supplier '
                'preview again.') % (
                    label, cur_rec.name, plan.currency_id.name))

    def action_assign_suppliers(self, plan_id):
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            raise UserError(_('Plan not found.'))

        POLine = env_sudo['purchase.order.line']
        Supplier = env_sudo['product.supplierinfo']
        # Price snapshot for every purchased line (buy + subcontract).
        # Seller assignment for buy AND subcontract lines with an order
        # qty: buy lines are ordered directly, subcontract lines are
        # ordered from the subcontractor via a PO (confirming that PO
        # triggers Odoo's standard subcontract receipt + MO chain).
        cost_lines = plan.line_ids.filtered(
            lambda l: l.route_type in ('buy', 'subcontract')
            and (l.gross_qty or 0) > 0)
        buy_pids = cost_lines.mapped('product_id').ids
        # Last purchase per product across TR+USA: the latest order
        # wins regardless of company (battery last bought from the USA
        # shows the USA price/supplier/company).
        # pid -> {partner_id, price_unit, currency_id, product_uom,
        #         order_id, buy_dt, company_id, company_name}
        last_buy = self._mpp_last_buys(env_sudo, buy_pids)
        # PO date (date_order) in one map; fallback to line date_planned.
        order_dates = {}
        for _lb in last_buy.values():
            if _lb.get('order_id') and _lb.get('buy_dt') is not None:
                order_dates[_lb['order_id']] = _lb['buy_dt']

        usd = env_sudo['res.currency'].search(
            [('name', '=', 'USD')], limit=1)

        tmpl_map = {}
        for pr in env_sudo['product.product'].browse(buy_pids).read(
                ['product_tmpl_id', 'seller_ids', 'uom_id']):
            tmpl_map[pr['id']] = pr
        # All pricelist sellers in ONE query (was: one search_read per
        # line). Grouped by template; row order per template matches
        # the old per-template query (no order = id order).
        tmpl_ids = list({
            t[0] for t in (
                pr.get('product_tmpl_id')
                for pr in tmpl_map.values()) if t})
        seller_map = {}
        # Pricelist sellers that are our own companies are never valid
        # (same rule as last-buy: TR/US can never be the seller).
        own_partners = _mpp_own_partner_ids(env_sudo)
        if tmpl_ids:
            for s in Supplier.search_read([
                    ('product_tmpl_id', 'in', tmpl_ids),
            ], ['product_tmpl_id', 'name', 'price', 'min_qty',
                'currency_id', 'product_uom', 'sequence']):
                _sn = s.get('name')
                _sid = _sn[0] if _sn else False
                if _sid and _sid in own_partners:
                    continue
                _st = s.get('product_tmpl_id')
                seller_map.setdefault(
                    _st[0] if _st else 0, []).append(s)

        for line in cost_lines:
            pid = line.product_id.id
            pr = tmpl_map.get(pid, {})
            lb = last_buy.get(pid, {})
            vals = self._last_buy_vals(
                env_sudo, plan, usd, lb, order_dates)
            if line.route_type not in ('buy', 'subcontract') or not (
                    line.order_qty or 0) > 0:
                # Price snapshot only (no seller / no order).
                self._mpp_write_if_changed(line, vals)
                continue
            seller_pid = False
            price = 0.0
            warn = ''
            lp = lb.get('partner_id')
            _tmpl = pr.get('product_tmpl_id')
            sellers = seller_map.get(_tmpl[0] if _tmpl else 0, [])
            # Safety net: never assign our own company even if an
            # unfiltered last-buy slips through (falls to pricelist).
            if lp and lp[0] in own_partners:
                lb = {}
                lp = False
            if lp:
                # Real purchase history wins: order from the last
                # supplier (TR or USA) at the last price. The pricelist
                # is consulted only for the min-qty warning.
                seller_pid = lp[0]
                price = float(lb.get('price_unit') or 0.0)
                pou = lb.get('product_uom')
                if pou and line.uom_id and pou[0] != line.uom_id.id:
                    try:
                        pou_rec = env_sudo['uom.uom'].browse(pou[0])
                        price = line.uom_id._compute_quantity(
                            1.0, pou_rec, round=False) * price \
                            if price else 0.0
                    except Exception as exc:
                        _logger.warning(
                            'MPP supplier preview: UoM conversion failed '
                            'for %s, using PO-line price as-is: %s',
                            line.product_id.display_name, exc)
                        price = float(lb.get('price_unit') or 0.0)
                cur = lb.get('currency_id')
                price = self._mpp_price_in_plan_currency(
                    env_sudo, plan, price,
                    cur[0] if cur else False,
                    line.product_id.display_name)
                cand = [s for s in sellers if s['name'][0] == lp[0]]
                if cand and cand[0].get('min_qty') \
                        and line.order_qty < cand[0]['min_qty']:
                    warn = _('Min. order %s') % cand[0]['min_qty']
            elif sellers:
                seller = sorted(
                    sellers,
                    key=lambda s: (s.get('sequence') or 99,
                                   s['price']))[0]
                price = float(seller['price'] or 0.0)
                s_uom = seller.get('product_uom')
                if s_uom and line.uom_id and s_uom[0] != line.uom_id.id:
                    s_uom_rec = env_sudo['uom.uom'].browse(s_uom[0])
                    price = line.uom_id._compute_quantity(
                        1.0, s_uom_rec, round=False) * price \
                        if price else 0.0
                    # Note: price is per seller UoM; qty is product UoM.
                if seller.get('min_qty') \
                        and line.order_qty < seller['min_qty']:
                    warn = _('Min. order %s') % seller['min_qty']
                seller_cur = seller.get('currency_id')
                price = self._mpp_price_in_plan_currency(
                    env_sudo, plan, price,
                    seller_cur[0] if seller_cur else False,
                    line.product_id.display_name)
                seller_pid = seller['name'][0]
            if not seller_pid:
                vals['note'] = _('No supplier (no seller defined).')
                self._mpp_write_if_changed(line, vals)
                continue
            vals.update({
                'seller_id': seller_pid,
                'unit_price': price,
                'min_qty_warn': warn,
            })
            # Subtotal (TRY order value) is written for buy lines only:
            # make/subcontract/sellerless lines keep 0, which is why the
            # tree shows Est. USD (rolled_usd x order) instead.
            if line.route_type == 'buy':
                vals['subtotal'] = price * float(line.order_qty or 0.0)
            self._mpp_write_if_changed(line, vals)
        plan.state = 'supplier_review'
        rollup = self._compute_rollup(env_sudo, plan)
        summary = self._plan_summary(env_sudo, plan)
        summary['kits'] = rollup['kits']
        summary['rolled_total_usd'] = rollup['total']
        summary['rolled_total_try'] = rollup.get('total_try', 0.0)
        return summary

    @api.model
    def _aggregate_kits(self, env_sudo, targets, unit_usd, unit_try):
        """Kit totals from entry quantities (members only, no double
        count: sub-product cost already lives inside each entry's
        rolled cost).

        @param env_sudo: sudo environment.
        @param targets: {str(pid): qty} entry quantities.
        @param unit_usd: callable(pid) -> rolled USD per unit.
        @param unit_try: callable(pid) -> rolled TRY per unit.
        @return: {'kits': [...], 'total': grand_usd,
            'total_try': grand_try}.
        """
        kit_of = {}
        kit_names = {}
        for kit in _mpp_find_kit_boms(env_sudo):
            key = kit['key']
            kit_names[key] = kit['bom'].product_tmpl_id.name or key
            for bl in kit['bom'].bom_line_ids:
                kit_of.setdefault(bl.product_id.id, key)
        kits = {}
        grand = 0.0
        grand_try = 0.0
        for pid_str, tq in (targets or {}).items():
            try:
                pid = int(pid_str)
                tqf = float(tq or 0)
            except (TypeError, ValueError):
                continue
            if tqf <= 0:
                continue
            ext = unit_usd(pid) * tqf
            grand += ext
            grand_try += unit_try(pid) * tqf
            key = kit_of.get(pid, 'other')
            k = kits.setdefault(
                key, {'key': key,
                      'name': kit_names.get(key, 'Other'),
                      'cost': 0.0, 'cost_try': 0.0, 'count': 0})
            k['cost'] += ext
            k['cost_try'] += unit_try(pid) * tqf
            k['count'] += 1
        return {'kits': list(kits.values()), 'total': grand,
                'total_try': grand_try}

    @api.model
    def _compute_rollup(self, env_sudo, plan):
        """Bottom-up rolled USD + TRY cost per unit.

        Each leaf purchase price (last price of buy/subcontract
        lines) is multiplied by its usage qty and summed upward to the
        top products and kits. USD uses the historical USD rate of the
        last buy date; TRY uses the historical TRY rate of the same
        date. No operation costing: make/phantom nodes contribute only
        their children's cost.
        """
        try:
            edges = json.loads(plan.edge_json or '{}')
        except ValueError:
            edges = {}
        children = {}
        for p, ch in edges.items():
            try:
                children[int(p)] = {int(c): float(q)
                                    for c, q in ch.items()}
            except (TypeError, ValueError):
                continue
        line_by_pid = {}
        for line in plan.line_ids:
            line_by_pid.setdefault(line.product_id.id, line)

        memo_usd = {}
        memo_try = {}
        visiting = set()

        def _own_usd(pid):
            line = line_by_pid.get(pid)
            if line and line.route_type in ('buy', 'subcontract'):
                return float(line.last_price_usd or 0.0) * \
                    _mpp_line_uom_factor(line)
            return 0.0

        def _own_try(pid):
            line = line_by_pid.get(pid)
            if not line or line.route_type not in ('buy', 'subcontract'):
                return 0.0
            price = float(line.last_price or 0.0) * \
                _mpp_line_uom_factor(line)
            if not price:
                return 0.0
            cur = line.last_currency_id
            if not cur or cur.id == plan.currency_id.id:
                return price
            buy_date = line.last_date or fields.Date.today()
            try:
                return cur._convert(
                    price, plan.currency_id, plan.company_id, buy_date)
            except Exception as exc:
                _logger.warning(
                    'MPP rollup: TRY conversion failed for '
                    'product %s (%s -> %s): %s; using 0.0',
                    pid, cur.name,
                    plan.currency_id.name if plan.currency_id else '?',
                    exc)
                return 0.0

        def _unit_usd(pid):
            if pid in memo_usd:
                return memo_usd[pid]
            if pid in visiting:
                return 0.0  # cycle guard
            visiting.add(pid)
            total = _own_usd(pid)
            for c, q in children.get(pid, {}).items():
                total += _unit_usd(c) * (q or 0.0)
            visiting.discard(pid)
            memo_usd[pid] = total
            return total

        def _unit_try(pid):
            if pid in memo_try:
                return memo_try[pid]
            if pid in visiting:
                return 0.0  # cycle guard
            visiting.add(pid)
            total = _own_try(pid)
            for c, q in children.get(pid, {}).items():
                total += _unit_try(c) * (q or 0.0)
            visiting.discard(pid)
            memo_try[pid] = total
            return total

        for pid, line in line_by_pid.items():
            unit_u = _unit_usd(pid)
            unit_t = _unit_try(pid)
            self._mpp_write_if_changed(line, {
                'rolled_usd': unit_u,
                'rolled_total_usd': unit_u * float(line.gross_qty or 0.0),
                'rolled_try': unit_t,
                'rolled_total_try': unit_t * float(line.gross_qty or 0.0),
            })

        # Kit totals from entry quantities (members only, no double count:
        # sub-product cost already lives inside each entry's rolled cost).
        try:
            targets = json.loads(plan.target_json or '{}')
        except ValueError:
            targets = {}
        return self._aggregate_kits(env_sudo, targets, _unit_usd,
                                    _unit_try)

    @api.model
    def _mpp_company_code(self, env_sudo, company_id):
        """Short TR/USA label for the source-company column.

        @param env_sudo Sudo env.
        @param company_id res.company ID (or False).
        @return 'TR', 'USA', or the company name as fallback.
        """
        try:
            cid = int(company_id)
        except (TypeError, ValueError):
            return ''
        if cid == _MPP_TR_COMPANY_ID:
            return 'TR'
        comp = env_sudo['res.company'].browse(cid)
        if comp.exists():
            if (comp.currency_id.name or '').upper() == 'USD':
                return 'USA'
            return comp.name or ''
        return ''

    @api.model
    def _mpp_last_buys(self, env_sudo, pids):
        """Latest purchase per product across TR+USA companies.

        The most recent PO (by order date) wins regardless of company,
        so a battery last bought from the USA shows the USA price,
        supplier and company. Cancelled orders are ignored.
        @param env_sudo Sudo env.
        @param pids Product IDs.
        @return {pid: {partner_id, price_unit, currency_id, product_uom,
            order_id, buy_dt, company_id, company_name}}; pids without
            any purchase are omitted.
        """
        res = {}
        pids = sorted({p for p in (pids or []) if p})
        if not pids:
            return res
        # Our own companies (TR/US) are never valid sellers: skip
        # inter-company PO lines so the latest REAL supplier wins.
        own_partners = _mpp_own_partner_ids(env_sudo)
        POLine = env_sudo['purchase.order.line']
        # ONE batched fetch for all products (was: one search_read per
        # product). Same order, first 5 rows per product kept, so the
        # best-pick below sees exactly the old candidate sets.
        by_pid = {}
        for c in POLine.search_read([
                ('product_id', 'in', pids),
                ('order_id.state', '!=', 'cancel'),
        ], ['product_id', 'partner_id', 'date_planned', 'price_unit',
            'currency_id', 'product_uom', 'order_id'],
                order='date_planned desc, id desc'):
            _cp = c.get('product_id')
            _cpid = _cp[0] if _cp else False
            if not _cpid:
                continue
            _pp = c.get('partner_id')
            _ppid = _pp[0] if _pp else False
            if _ppid and _ppid in own_partners:
                continue
            bucket = by_pid.setdefault(_cpid, [])
            if len(bucket) < 5:
                bucket.append(c)
        oids = list({
            c['order_id'][0] for _cl in by_pid.values()
            for c in _cl if c.get('order_id')})
        omap = {}
        if oids:
            for o in env_sudo['purchase.order'].browse(oids).read(
                    ['date_order', 'company_id']):
                dt = o.get('date_order')
                omap[o['id']] = (
                    fields.Datetime.from_string(dt)
                    if isinstance(dt, str) else dt,
                    o.get('company_id'),
                )
        for pid in pids:
            cands = by_pid.get(pid)
            if not cands:
                continue
            best, best_dt = False, False
            for c in cands:
                _oid = c['order_id'][0] if c.get('order_id') else 0
                dt, _comp = omap.get(_oid, (False, False))
                if not dt and c.get('date_planned'):
                    dp = c['date_planned']
                    dt = fields.Datetime.from_string(dp) \
                        if isinstance(dp, str) else dp
                if not best or (dt and (not best_dt or dt > best_dt)):
                    best, best_dt = c, dt
            if not best:
                continue
            _oid = best['order_id'][0] if best.get('order_id') else 0
            _dt, comp = omap.get(_oid, (False, False))
            cid = comp[0] if comp else False
            res[pid] = {
                'partner_id': best.get('partner_id'),
                'price_unit': float(best.get('price_unit') or 0.0),
                'currency_id': best.get('currency_id'),
                'product_uom': best.get('product_uom'),
                'order_id': _oid or False,
                'buy_dt': best_dt,
                'company_id': cid,
                'company_name': comp[1] if comp else '',
            }
        return res

    @api.model
    def _kits_from_stored(self, env_sudo, plan, targets):
        """Kit totals from the stored rolled line values (no writes).

        Same shape as _compute_rollup's return, but the per-unit costs
        come from the lines written by the last full build instead of
        being recomputed. Used by the cached tree path.
        @param env_sudo: sudo environment.
        @param plan: matia.procurement.plan record.
        @param targets: {str(pid): qty} entry quantities.
        @return: {'kits': [...], 'total': grand_usd,
            'total_try': grand_try}.
        """
        unit_by_pid = {}
        for line in plan.line_ids:
            unit_by_pid.setdefault(
                line.product_id.id,
                (float(line.rolled_usd or 0.0),
                 float(line.rolled_try or 0.0)))
        return self._aggregate_kits(
            env_sudo, targets,
            lambda pid: unit_by_pid.get(pid, (0.0, 0.0))[0],
            lambda pid: unit_by_pid.get(pid, (0.0, 0.0))[1])

    @api.model
    def _mpp_write_if_changed(self, line, vals):
        """Write only values that actually changed.

        Preview/rollup recompute the same snapshot on every run;
        skipping no-op writes avoids one UPDATE plus stored-computed
        cascades per untouched line. Many2one values compare by id.
        @param line: matia.procurement.plan.line record.
        @param vals: write dict.
        @return: True when a write happened.
        """
        diff = {}
        for field, new in vals.items():
            cur = line[field]
            if hasattr(cur, '_name') and cur._name:
                if (cur.id or False) != (new or False):
                    diff[field] = new
            elif cur != new:
                diff[field] = new
        if diff:
            line.write(diff)
            return True
        return False

    @api.model
    def _last_buy_vals(self, env_sudo, plan, usd, lb, order_dates):
        """Last-purchase snapshot: price in own currency, USD at the
        historical rate of the purchase date, and date as 'Mon YYYY'."""
        vals = {'last_price': 0.0, 'last_currency_id': False,
                'last_uom_id': False,
                'last_price_usd': 0.0, 'last_date': False,
                'last_company_id': False}
        if not lb:
            return vals
        price = float(lb.get('price_unit') or 0.0)
        cur = lb.get('currency_id')
        cur_id = cur[0] if cur else False
        pou = lb.get('product_uom')
        pou_id = pou[0] if pou else False
        # lb comes from _mpp_last_buys (order_id is int, date is buy_dt);
        # accept raw search_read shape too (order_id [id, name]).
        buy_dt = lb.get('buy_dt') or None
        if not buy_dt:
            _oid_raw = lb.get('order_id')
            if isinstance(_oid_raw, (list, tuple)):
                _oid = _oid_raw[0] if _oid_raw else False
            else:
                _oid = _oid_raw or False
            if _oid and _oid in (order_dates or {}):
                buy_dt = order_dates[_oid]
        if not buy_dt and lb.get('date_planned'):
            dp = lb['date_planned']
            buy_dt = fields.Datetime.from_string(dp) if isinstance(
                dp, str) else dp
        buy_date = buy_dt.date() if buy_dt else fields.Date.today()
        usd_price = price
        if cur_id and usd:
            cur_rec = env_sudo['res.currency'].browse(cur_id)
            if cur_id != usd.id:
                usd_price = cur_rec._convert(
                    price, usd, plan.company_id, buy_date)
        vals.update({
            'last_price': price,
            'last_currency_id': cur_id,
            'last_uom_id': pou_id,
            'last_price_usd': usd_price,
            'last_date': buy_date,
            'last_company_id': lb.get('company_id') or False,
        })
        return vals

    @api.model
    def _mpp_month_year(self, date_val):
        """'Sep 2025' style label, always English regardless of locale."""
        if not date_val:
            return ''
        d = fields.Date.from_string(date_val) if isinstance(
            date_val, str) else date_val
        return '%s %s' % (calendar.month_abbr[d.month], d.year)

    @api.model
    def _plan_summary(self, env_sudo, plan):
        groups = {}
        for line in plan.line_ids:
            key = line.route_type or 'unknown'
            g = groups.setdefault(key, {'route': key, 'lines': [],
                                       'cost': 0.0, 'count': 0})
            val = {
                'line_id': line.id,
                'product_id': line.product_id.id,
                'code': line.product_id.default_code or '',
                'name': line.product_id.name or '',
                'level': line.level,
                'gross': line.gross_qty,
                'stock_tr': line.stock_tr,
                'reserved_tr': line.reserved_tr,
                'avail_tr': line.avail_tr,
                'stock_us': line.stock_us,
                'reserved_us': line.reserved_us,
                'avail_us': line.avail_us,
                'incoming_info': line.incoming_info,
                'open_mo_info': line.open_mo_info,
                'net': line.net_qty,
                'order_qty': line.order_qty,
                'uom': _mpp_uom_en(
                    line.uom_id.name if line.uom_id else ''),
                'seller': line.seller_id.display_name
                if line.seller_id else '',
                'price': line.unit_price,
                'subtotal': line.subtotal,
                'last_price': line.last_price,
                'last_currency': line.last_currency_id.name
                if line.last_currency_id else '',
                'last_uom': _mpp_uom_en(
                    line.last_uom_id.name if line.last_uom_id else ''),
                'last_usd': line.last_price_usd,
                'last_date': self._mpp_month_year(line.last_date),
                'last_company': self._mpp_company_code(
                    env_sudo,
                    line.last_company_id.id
                    if line.last_company_id else False),
                'unit_usd': line.rolled_usd,
                'rolled_usd': line.rolled_total_usd,
                'rolled_try': line.rolled_try,
                'rolled_total_try': line.rolled_total_try,
                'warn': line.min_qty_warn or '',
                'note': line.note or '',
            }
            g['lines'].append(val)
            g['cost'] += line.subtotal or 0.0
            g['count'] += 1
        # Supplier breakdown (buy group)
        suppliers = {}
        for line in plan.line_ids.filtered(
                lambda l: l.route_type == 'buy' and l.order_qty > 0):
            sid = line.seller_id.id if line.seller_id else 0
            s = suppliers.setdefault(
                sid, {'seller_id': sid,
                      'seller_name': line.seller_id.display_name
                       if line.seller_id else _('No supplier'),
                      'lines': [], 'cost': 0.0})
            s['lines'].append({
                'product_id': line.product_id.id,
                'code': line.product_id.default_code or '',
                'name': line.product_id.name or '',
                'order_qty': line.order_qty,
                'price': line.unit_price,
                'subtotal': line.subtotal,
                'last_price': line.last_price,
                'last_currency': line.last_currency_id.name
                if line.last_currency_id else '',
                'last_uom': _mpp_uom_en(
                    line.last_uom_id.name if line.last_uom_id else ''),
                'last_usd': line.last_price_usd,
                'last_date': self._mpp_month_year(line.last_date),
                'last_company': self._mpp_company_code(
                    env_sudo,
                    line.last_company_id.id
                    if line.last_company_id else False),
                'unit_usd': line.rolled_usd,
                'rolled_usd': line.rolled_total_usd,
                'warn': line.min_qty_warn or '',
            })
            s['cost'] += line.subtotal or 0.0
        return {
            'plan_id': plan.id,
            'name': plan.name,
            'state': plan.state,
            'total_cost': plan.total_cost,
            'groups': groups,
            'suppliers': list(suppliers.values()),
        }

    # ------------------------------------------------------------------
    # Tree UI (capacity-style): kit groups + lazy sub-BOM with cost.
    # Single-page flow: get_startup_tree -> set_targets_and_rebuild ->
    # get_tree_with_cost. Needed numbers persist on target_json.
    # ------------------------------------------------------------------
    @api.model
    def get_startup_tree(self):
        """Latest plan with its saved Needed values (or a fresh plan).

        The Plan tab opens with this: numbers persist on the plan, so
        the user continues where they left off. When no plan exists
        yet, an empty one is created and skeleton groups (need=0)
        are returned.
        @return Same dict as get_tree_with_cost (tree_groups + targets).
        """
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].search(
            [], order='id desc', limit=1)
        if not plan:
            company = env_sudo['res.company'].browse(_MPP_TR_COMPANY_ID)
            seq = env_sudo['ir.sequence'].sudo().next_by_code(
                'matia.procurement.plan') or _('MPP')
            plan = env_sudo['matia.procurement.plan'].create({
                'name': seq,
                'company_id': company.id,
                'state': 'draft',
                'target_json': '{}',
                'currency_id': company.currency_id.id,
            })
        return self.get_tree_with_cost(plan.id)

    @api.model
    def set_targets_and_rebuild(self, plan_id, targets):
        """Save Needed numbers on the plan and rebuild the tree.

        Only positive quantities are kept; missing rows mean 0.
        @param plan_id Plan to update.
        @param targets {product_id: qty} Needed numbers from the client.
        @return Same dict as get_tree_with_cost.
        """
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            raise UserError(_('Plan not found.'))
        clean = {}
        for _k, _v in (targets or {}).items():
            try:
                _pid = int(_k)
                _qty = int(float(_v))
            except (TypeError, ValueError):
                continue
            if _pid > 0 and _qty > 0:
                clean[str(_pid)] = _qty
        plan.write({'target_json': json.dumps(clean)})
        return self.get_tree_with_cost(plan.id)

    @api.model
    def get_tree_with_cost(self, plan_id):
        """Explode + net + suppliers, then return capacity-style groups.

        Groups are the 4 kit BOMs in Base/Outdoor/Seat/Screws order;
        items are ALL of the kit's top products (level 0), each with
        its saved Needed value (0 when not entered). Children load
        lazily via get_sub_bom_cost.
        @param plan_id Plan ID (see get_startup_tree).
        @return Summary dict plus 'tree_groups' and 'targets'.
        """
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            raise UserError(_('Plan not found.'))
        try:
            targets = json.loads(plan.target_json or '{}')
        except ValueError:
            targets = {}
        targets = {int(k): float(v) for k, v in targets.items()
                   if float(v or 0) > 0}
        # Cached view: when the lines were already built from these
        # exact targets, skip the full rebuild (no unlink/recreate,
        # no re-netting). This also protects RFQ/MO links written on
        # the lines after the first build. Any target change (or a
        # plan built before built_target_json existed) rebuilds.
        # Empty plan (startup before any Needed entry): skeleton
        # groups, no explosion.
        if not targets and not plan.line_ids:
            summary = self._plan_summary(env_sudo, plan)
            summary['kits'] = []
            summary['rolled_total_usd'] = 0.0
            summary['rolled_total_try'] = 0.0
        elif plan.line_ids and (plan.built_target_json or '') == (
                plan.target_json or ''):
            summary = self._plan_summary(env_sudo, plan)
            kits = self._kits_from_stored(env_sudo, plan, {
                str(k): v for k, v in targets.items()})
            summary['kits'] = kits['kits']
            summary['rolled_total_usd'] = kits['total']
            summary['rolled_total_try'] = kits['total_try']
        else:
            summary = self.action_explode_and_net(plan.id)
            summary = self.action_assign_suppliers(plan.id)
        line_by_pid = {}
        for line in plan.line_ids:
            line_by_pid.setdefault(line.product_id.id, line)
        kit_cfgs = _mpp_find_kit_boms(env_sudo)
        # ALL kit tops resolve (not just entered targets): rows with
        # no Needed value show need=0 and stay expandable.
        top_pids = set(targets)
        for kit in kit_cfgs:
            for bl in kit['bom'].bom_line_ids:
                top_pids.add(bl.product_id.id)
        prod_by_id = {}
        if top_pids:
            for pr in env_sudo['product.product'].browse(
                    list(top_pids)).read(
                    ['default_code', 'name', 'display_name', 'uom_id',
                     'product_tmpl_id']):
                prod_by_id[pr['id']] = pr
        bom_by_tmpl = {}
        tmpl_ids = [p.get('product_tmpl_id', [0])[0]
                    for p in prod_by_id.values()
                    if p.get('product_tmpl_id')]
        if tmpl_ids:
            for b in env_sudo['mrp.bom'].search(
                    [('product_tmpl_id', 'in', list(set(tmpl_ids)))]):
                key = b.product_tmpl_id.id
                if key not in bom_by_tmpl or b.product_id:
                    bom_by_tmpl[key] = b
        # One query for kit-line templates missing from bom_by_tmpl
        # (was: one search per line in the loop below).
        # (kit_cfgs was found above, before the product read.)
        missing_tmpls = set()
        for kit in kit_cfgs:
            for bl in kit['bom'].bom_line_ids:
                _t = bl.product_id.product_tmpl_id.id
                if _t not in bom_by_tmpl:
                    missing_tmpls.add(_t)
        extra_bom_tmpls = set()
        if missing_tmpls:
            for b in env_sudo['mrp.bom'].search(
                    [('product_tmpl_id', 'in', list(missing_tmpls))]):
                extra_bom_tmpls.add(b.product_tmpl_id.id)
        tree_groups = []
        pool_map, _pool_branch, _share_map, _driver_map, use_notes, par_n = \
            _mpp_load_pools(plan.producible_json)
        for kit in kit_cfgs:
            key = kit['key']
            bom = kit['bom']
            items = []
            for bl in bom.bom_line_ids:
                pid = bl.product_id.id
                pr = prod_by_id.get(pid, {})
                line = line_by_pid.get(pid)
                tmpl_id = bl.product_id.product_tmpl_id.id
                has_bom = tmpl_id in bom_by_tmpl \
                    or tmpl_id in extra_bom_tmpls
                # TR + US combined unreserved (user rule); the split
                # stays on the row for the TR / US columns.
                a_tr = line.avail_tr if line else 0.0
                a_us = line.avail_us if line else 0.0
                avail = a_tr + a_us
                need = float(targets.get(pid, 0) or 0)
                # Bottom-up pool (own stock + assemblable from children);
                # legacy own-stock value when the plan predates pools.
                # The share note reflects this row's OWN product: it is
                # shown only when the product itself is used by more
                # than one parent inside this plan's trees (never the
                # bottleneck child's sharing).
                _pool = pool_map.get(pid, avail)
                _pn = par_n.get(pid, 1)
                items.append({
                    'product_id': pid,
                    'code': bl.product_id.default_code or '',
                    'name': bl.product_id.name or '',
                    'display': pr.get('display_name')
                    or bl.product_id.display_name,
                    'bom_qty': float(bl.product_qty or 1.0),
                    # Line UoM first (same source as Capacity and the
                    # sub-BOM rows); product card only as fallback.
                    'uom': _mpp_uom_en(
                        bl.product_uom_id.name
                        if bl.product_uom_id else (
                            pr.get('uom_id', [0, ''])[1]
                            if pr.get('uom_id') else '')),
                    'has_bom': bool(has_bom),
                    'level': 0,
                    'stock_tr': line.stock_tr if line else 0.0,
                    'reserved_tr': line.reserved_tr if line else 0.0,
                    'avail_tr': a_tr,
                    'stock_us': line.stock_us if line else 0.0,
                    'reserved_us': line.reserved_us if line else 0.0,
                    'avail_us': a_us,
                    'avail_total': avail,
                    'gross': line.gross_qty if line else 0.0,
                    # Needed = saved target for this top (editable on
                    # the client, persisted via set_targets_and_rebuild).
                    'need': need,
                    # Planned = net cascade value for tops: need minus
                    # combined avail (level-0 nodes have no parents,
                    # so this is exact). Children show their own net
                    # via sub-BOM.
                    'planned': max(0.0, need - avail),
                    'producible': int(math.floor(_pool))
                    if _pool > 0 else 0,
                    'share_pct': 100.0,
                    'share_n': _pn,
                    'share_note': use_notes.get(pid, ''),
                    'net': line.net_qty if line else 0.0,
                    'order_qty': line.order_qty if line else 0.0,
                    'seller': line.seller_id.display_name
                    if line and line.seller_id else '',
                    'last_company': self._mpp_company_code(
                        env_sudo, line.last_company_id.id)
                    if line and line.last_company_id else '',
                    'last_price': line.last_price if line else 0.0,
                    'last_currency':
                        line.last_currency_id.name
                        if line and line.last_currency_id else '',
                    'last_uom': _mpp_uom_en(
                        line.last_uom_id.name
                        if line and line.last_uom_id else ''),
                    'last_usd': line.last_price_usd if line else 0.0,
                    'last_try': self._mpp_line_try(env_sudo, plan, line),
                    'last_date': self._mpp_month_year(
                        line.last_date) if line else '',
                    'rolled_try': line.rolled_try if line else 0.0,
                    'rolled_total_try':
                        line.rolled_total_try if line else 0.0,
                    'rolled_usd': line.rolled_usd if line else 0.0,
                    'rolled_total_usd':
                        line.rolled_total_usd if line else 0.0,
                    'subtotal': line.subtotal if line else 0.0,
                    'incoming_info': line.incoming_info if line else 0.0,
                    'open_mo_info': line.open_mo_info if line else 0.0,
                    'top_breakdown': '',
                    'warn': line.min_qty_warn if line else '',
                })
            items.sort(key=lambda r: (r['code'] or '', r['name'] or ''))
            tree_groups.append({
                'key': key,
                'title': dict(base='Base', screws='Screws',
                              outdoor='Outdoor', seat='Seat').get(key, key),
                'bom_name': bom.product_tmpl_id.name or key,
                'badge': key,
                'count': len(items),
                'items': items,
            })
        # Display order Base/Outdoor/Seat/Screws (user rule),
        # independent of the kit search order.
        _order = {'base': 0, 'outdoor': 1, 'seat': 2, 'screws': 3}
        tree_groups.sort(key=lambda g: _order.get(g['key'], 99))
        summary['tree_groups'] = tree_groups
        summary['targets'] = {str(k): v for k, v in targets.items()}
        # Per-top contribution: which target needs how much of each part.
        contrib = self._mpp_need_per_top(env_sudo, plan)
        code_by_pid = {}
        if contrib:
            all_p = set(contrib) | {t for v in contrib.values()
                                    for t in v}
            for pr in env_sudo['product.product'].browse(
                    list(all_p)).read(['default_code', 'name']):
                code_by_pid[pr['id']] = pr.get('default_code') or pr.get(
                    'name') or str(pr['id'])
        for g in tree_groups:
            for it in g['items']:
                it['top_breakdown'] = self._mpp_format_breakdown(
                    contrib.get(it['product_id'], {}), code_by_pid)
        # Flat lines also carry breakdown (tooltip on Planned column).
        if 'groups' in summary:
            for _rk, grp in summary['groups'].items():
                for ln in grp.get('lines', []):
                    ln['top_breakdown'] = self._mpp_format_breakdown(
                        contrib.get(ln.get('product_id'), {}), code_by_pid)
                    if ln.get('product_id') in line_by_pid:
                        _l = line_by_pid[ln['product_id']]
                        ln['last_try'] = self._mpp_line_try(
                            env_sudo, plan, _l)
        return summary

    @api.model
    def _mpp_line_try(self, env_sudo, plan, line):
        """Last-buy price converted to TRY at the buy-date rate."""
        if not line or not (line.last_price or 0.0):
            return 0.0
        cur = line.last_currency_id
        if not cur or cur.id == plan.currency_id.id:
            return float(line.last_price or 0.0)
        buy_date = line.last_date or fields.Date.today()
        try:
            return cur._convert(
                float(line.last_price or 0.0), plan.currency_id,
                plan.company_id, buy_date)
        except Exception as exc:
            _logger.warning(
                'MPP line TRY: conversion failed for line %s '
                '(product %s): %s; using 0.0',
                line.id if line else '?',
                line.product_id.display_name if line else '?',
                exc)
            return 0.0

    @api.model
    def _mpp_need_per_top(self, env_sudo, plan):
        """Re-explode targets tracking per-top contribution.

        @return {part_pid: {top_pid: gross_qty}}.
        """
        try:
            targets = json.loads(plan.target_json or '{}')
        except ValueError:
            return {}
        targets = {int(k): float(v) for k, v in targets.items()
                   if float(v or 0) > 0}
        if not targets:
            return {}
        Product = env_sudo['product.product']
        Bom = env_sudo['mrp.bom']
        bom_cache = {}

        def _bom_of(pid):
            prod = Product.browse(pid)
            if not prod.exists():
                return False
            tid = prod.product_tmpl_id.id
            if tid not in bom_cache:
                b = Bom.search(
                    [('product_tmpl_id', '=', tid),
                     ('product_id', '=', pid)], limit=1)
                if not b:
                    b = Bom.search(
                        [('product_tmpl_id', '=', tid)], limit=1)
                bom_cache[tid] = b
            return bom_cache[tid]

        contrib = {}
        stack = [(top, float(qty), top, 0)
                 for top, qty in targets.items()]
        guard = 0
        while stack:
            guard += 1
            if guard > 60000:
                break
            pid, mult, top, level = stack.pop()
            if level > _MPP_MAX_LEVEL:
                continue
            bom = _bom_of(pid)
            if not bom:
                contrib.setdefault(pid, {}).setdefault(top, 0.0)
                contrib[pid][top] += mult
                continue
            if bom.type == 'phantom':
                for bl in bom.bom_line_ids:
                    stack.append((bl.product_id.id,
                                  mult * float(bl.product_qty or 1.0),
                                  top, level))
                continue
            contrib.setdefault(pid, {}).setdefault(top, 0.0)
            contrib[pid][top] += mult
            for bl in bom.bom_line_ids:
                stack.append((bl.product_id.id,
                              mult * float(bl.product_qty or 1.0),
                              top, level + 1))
        return contrib

    @api.model
    def _mpp_format_breakdown(self, per_top, code_by_pid):
        """'CODE×qty, ...' short string (max 5 entries + '+N more')."""
        if not per_top:
            return ''
        parts = []
        for top, qty in sorted(per_top.items(),
                               key=lambda kv: -kv[1])[:5]:
            code = code_by_pid.get(top, str(top))
            q = int(qty) if float(qty).is_integer() else round(qty, 2)
            parts.append('%s×%s' % (code, q))
        s = ', '.join(parts)
        if len(per_top) > 5:
            s += ' +%s more' % (len(per_top) - 5)
        return s

    @api.model
    def get_sub_bom_cost(self, product_id, parent_qty=1.0, plan_id=False):
        """Children of one product with TR+US avail + cost snapshot.

        Capacity-style lazy expansion for the procurement tree.
        @param product_id Parent product ID.
        @param parent_qty Parent multiplier (usage per top unit).
        @param plan_id Optional plan (uses its line snapshots first).
        @return {'items': [...]}, each with bom_qty, avail, last
            price/TRY/USD + short date, rolled TRY/USD unit, has_bom.
        """
        env_sudo = _mpp_env_sudo(self)
        prod = env_sudo['product.product'].browse(int(product_id))
        if not prod.exists():
            raise UserError(_('Product not found.'))
        bom = env_sudo['mrp.bom'].search(
            [('product_tmpl_id', '=', prod.product_tmpl_id.id),
             ('product_id', '=', prod.id)], limit=1)
        if not bom:
            bom = env_sudo['mrp.bom'].search(
                [('product_tmpl_id', '=', prod.product_tmpl_id.id)],
                limit=1)
        if not bom:
            return {'items': []}
        try:
            mult = float(parent_qty or 1.0)
        except (TypeError, ValueError):
            mult = 1.0
        child_ids = [bl.product_id.id for bl in bom.bom_line_ids]
        # TR + US combined unreserved (same rule as the explosion).
        split = _mpp_stock_split(env_sudo, child_ids)
        onhand, reserv, onhand_us, reserv_us = {}, {}, {}, {}
        for _pid, (_oht, _rst, _ohu, _rsu) in split.items():
            onhand[_pid] = max(0.0, _oht)
            reserv[_pid] = max(0.0, _rst)
            onhand_us[_pid] = max(0.0, _ohu)
            reserv_us[_pid] = max(0.0, _rsu)
        # Snapshot: plan lines first, else last PO line lookup.
        snap = {}
        plan = env_sudo['matia.procurement.plan'].browse(
            int(plan_id)) if plan_id else False
        _pool_map, branch_map, share_map, _pool_driver, use_notes, _par_n = \
            _mpp_load_pools(plan.producible_json if plan else '')
        if plan and plan.exists():
            for line in plan.line_ids.filtered(
                    lambda l: l.product_id.id in child_ids):
                snap[line.product_id.id] = line
        missing = [c for c in child_ids if c not in snap]
        usd = env_sudo['res.currency'].search(
            [('name', '=', 'USD')], limit=1)
        # Latest purchase across TR+USA per missing child: the latest
        # order wins regardless of company (same rule as the tree).
        last_buy = self._mpp_last_buys(env_sudo, missing)
        order_dates = {}
        for _lb in last_buy.values():
            if _lb.get('order_id') and _lb.get('buy_dt') is not None:
                order_dates[_lb['order_id']] = _lb['buy_dt']
        # One query for child templates with a BOM (was: one search
        # per child in the loop below).
        child_tmpls = {bl.product_id.product_tmpl_id.id
                       for bl in bom.bom_line_ids}
        bom_tmpls = set()
        if child_tmpls:
            for b in env_sudo['mrp.bom'].search(
                    [('product_tmpl_id', 'in', list(child_tmpls))]):
                bom_tmpls.add(b.product_tmpl_id.id)
        items = []
        for bl in bom.bom_line_ids:
            cp = bl.product_id
            pid = cp.id
            oh = max(0.0, onhand.get(pid, 0.0))
            rs = max(0.0, reserv.get(pid, 0.0))
            oh_u = max(0.0, onhand_us.get(pid, 0.0))
            rs_u = max(0.0, reserv_us.get(pid, 0.0))
            avail = max(0.0, oh - rs) + max(0.0, oh_u - rs_u)
            bqty = float(bl.product_qty or 1.0)
            line = snap.get(pid)
            if line:
                lp = float(line.last_price or 0.0)
                lcur = line.last_currency_id.name \
                    if line.last_currency_id else ''
                luom = _mpp_uom_en(
                    line.last_uom_id.name if line.last_uom_id else '')
                lusd = float(line.last_price_usd or 0.0)
                ltry = self._mpp_line_try(env_sudo, plan, line)
                ldate = self._mpp_month_year(line.last_date)
                rtry = float(line.rolled_try or 0.0)
                rusd = float(line.rolled_usd or 0.0)
                seller = line.seller_id.display_name \
                    if line.seller_id else ''
                lcompany = self._mpp_company_code(
                    env_sudo, line.last_company_id.id) \
                    if line.last_company_id else ''
            else:
                lb = last_buy.get(pid, {})
                lp = float(lb.get('price_unit') or 0.0)
                cur = lb.get('currency_id')
                lcur = cur[1] if cur else ''
                pou = lb.get('product_uom')
                luom = _mpp_uom_en(pou[1] if pou else '')
                buy_dt = lb.get('buy_dt')
                buy_date = buy_dt.date() if buy_dt else False
                lusd, ltry = lp, lp
                if cur and buy_date:
                    cur_rec = env_sudo['res.currency'].browse(cur[0])
                    comp = plan.company_id if plan and plan.exists() \
                        else env_sudo['res.company'].browse(
                            _MPP_TR_COMPANY_ID)
                    try:
                        if usd and cur[0] != usd.id:
                            lusd = cur_rec._convert(
                                lp, usd, comp, buy_date)
                        ltry = cur_rec._convert(
                            lp, comp.currency_id, comp, buy_date)
                    except Exception as exc:
                        _logger.warning(
                            'MPP tree cost: historical FX failed for '
                            'product id %s on %s, cost shown as 0.0: %s',
                            pid, buy_date, exc)
                ldate = self._mpp_month_year(buy_date) if buy_date else ''
                # Rolled unit cost is per BOM UoM: convert the PO-UoM
                # snapshot before display (same rule as _compute_rollup).
                _factor = 1.0
                try:
                    if pou and bl.product_uom_id and \
                            pou[0] != bl.product_uom_id.id:
                        _pou_rec = env_sudo['uom.uom'].browse(pou[0])
                        _factor = bl.product_uom_id._compute_quantity(
                            1.0, _pou_rec, round=False) or 1.0
                except Exception as exc:
                    _logger.warning(
                        'MPP tree cost: UoM conversion failed for '
                        'product id %s: %s; using 1.0', pid, exc)
                    _factor = 1.0
                rtry, rusd = ltry * _factor, lusd * _factor
                _lp = lb.get('partner_id')
                seller = _lp[1] if _lp else ''
                lcompany = self._mpp_company_code(
                    env_sudo, lb.get('company_id'))
            has_bom = cp.product_tmpl_id.id in bom_tmpls
            # Branch producible: this parent's allocated share of the
            # child's pool; legacy own-stock formula when the plan
            # predates pools (or no plan was passed).
            _branch = branch_map.get((prod.id, pid))
            if _branch is None:
                _branch = int(math.floor(avail / bqty)) \
                    if bqty > 0 and avail > 0 else 0
            _sh = share_map.get((prod.id, pid), (100.0, 1))
            items.append({
                'product_id': pid,
                'code': cp.default_code or '',
                'name': cp.name or '',
                'bom_qty': bqty,
                'gross': bqty * mult,
                # Branch demand = parent NET x usage; net deducts own
                # avail (same cascade rule as the explosion).
                'planned': bqty * mult,
                'net': max(0.0, bqty * mult - avail),
                'uom': _mpp_uom_en(
                    bl.product_uom_id.name
                    if bl.product_uom_id else ''),
                'has_bom': has_bom,
                'stock_tr': oh,
                'reserved_tr': rs,
                'avail_tr': max(0.0, oh - rs),
                'stock_us': oh_u,
                'reserved_us': rs_u,
                'avail_us': max(0.0, oh_u - rs_u),
                'avail_total': avail,
                'producible': _branch,
                'share_pct': _sh[0],
                'share_n': _sh[1],
                'share_note': use_notes.get(pid, ''),
                'seller': seller,
                'last_company': lcompany,
                'last_price': lp,
                'last_currency': lcur,
                'last_uom': luom,
                'last_usd': lusd,
                'last_try': ltry,
                'last_date': ldate,
                'rolled_try': rtry,
                'rolled_usd': rusd,
            })
        items.sort(key=lambda r: (r['code'] or '', r['name'] or ''))
        return {'items': items}

    @api.model
    def search_tree(self, plan_id, query):
        """Search every BOM tree of the plan, return matches with parents.

        The Tab 2 filter only sees already-expanded rows, so a part
        buried in a collapsed subtree (e.g. E1CBRN06 in 4 BOMs) is
        invisible until its parents are opened. This walks the full
        forest server-side (same BOM resolution as get_sub_bom_cost)
        and returns each hit with its parent trail plus the id path
        the client needs to expand-and-scroll to it.
        @param plan_id Plan ID from create_plan.
        @param query Case-insensitive substring on code or name.
        @return {'matches': [...], 'total': int}, capped at 100 hits.
            Each match: product_id/code/name/level, group_key,
            group_title, top_pid/top_code, trail [{code, name} top
            first, match last], path_ids [top..match] for expansion.
        """
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            raise UserError(_('Plan not found.'))
        q = (query or '').strip().lower()
        if len(q) < 2:
            return {'matches': [], 'total': 0}
        try:
            targets = json.loads(plan.target_json or '{}')
        except ValueError:
            targets = {}
        try:
            targets = {int(k) for k, v in targets.items()
                       if float(v or 0) > 0}
        except (TypeError, ValueError):
            return {'matches': [], 'total': 0}
        kit_cfgs = _mpp_find_kit_boms(env_sudo)
        group_title = {'base': 'Base', 'screws': 'Screws',
                       'outdoor': 'Outdoor', 'seat': 'Seat'}
        matches = []
        cap = 100
        prod_cache = {}
        bom_cache = {}

        def _info(pid):
            hit = prod_cache.get(pid)
            if hit is None:
                try:
                    pr = env_sudo['product.product'].browse(int(pid))
                    hit = {'code': pr.default_code or '',
                           'name': pr.name or ''} \
                        if pr.exists() else {'code': '', 'name': ''}
                except Exception:
                    hit = {'code': '', 'name': ''}
                prod_cache[pid] = hit
            return hit

        def _kids_bom(pid):
            if pid in bom_cache:
                return bom_cache[pid]
            bom = False
            try:
                prod = env_sudo['product.product'].browse(int(pid))
                if prod.exists():
                    bom = env_sudo['mrp.bom'].search(
                        [('product_tmpl_id', '=',
                          prod.product_tmpl_id.id),
                         ('product_id', '=', prod.id)], limit=1)
                    if not bom:
                        bom = env_sudo['mrp.bom'].search(
                            [('product_tmpl_id', '=',
                              prod.product_tmpl_id.id)], limit=1)
            except Exception:
                bom = False
            bom_cache[pid] = bom
            return bom

        def _hit(pid):
            info = _info(pid)
            return q in (info['code'] or '').lower() or \
                q in (info['name'] or '').lower()

        def _walk(pid, ancestors, depth, ctx):
            if len(matches) >= cap or depth > 10 or pid in ancestors:
                return
            bom = _kids_bom(pid)
            if not bom:
                return
            try:
                lines = bom.bom_line_ids
            except Exception:
                return
            for bl in lines:
                cpid = bl.product_id.id
                chain = ancestors + [pid]
                if _hit(cpid):
                    info = _info(cpid)
                    trail = []
                    for apid in chain + [cpid]:
                        ainfo = _info(apid)
                        trail.append({'code': ainfo['code'],
                                      'name': ainfo['name']})
                    matches.append({
                        'product_id': cpid,
                        'code': info['code'],
                        'name': info['name'],
                        'level': depth + 1,
                        'group_key': ctx['group_key'],
                        'group_title': ctx['group_title'],
                        'top_pid': ctx['top_pid'],
                        'top_code': ctx['top_code'],
                        'top_name': ctx['top_name'],
                        'path_ids': chain + [cpid],
                        'trail': trail,
                    })
                    if len(matches) >= cap:
                        return
                _walk(cpid, chain, depth + 1, ctx)
                if len(matches) >= cap:
                    return

        try:
            for kit in kit_cfgs:
                gkey = kit['key']
                gtitle = group_title.get(gkey, gkey)
                for bl in kit['bom'].bom_line_ids:
                    tpid = bl.product_id.id
                    if tpid not in targets:
                        continue
                    tinfo = _info(tpid)
                    if _hit(tpid):
                        matches.append({
                            'product_id': tpid,
                            'code': tinfo['code'],
                            'name': tinfo['name'],
                            'level': 0,
                            'group_key': gkey,
                            'group_title': gtitle,
                            'top_pid': tpid,
                            'top_code': tinfo['code'],
                            'top_name': tinfo['name'],
                            'path_ids': [tpid],
                            'trail': [{'code': tinfo['code'],
                                       'name': tinfo['name']}],
                        })
                        if len(matches) >= cap:
                            break
                    _walk(tpid, [], 0, {
                        'group_key': gkey, 'group_title': gtitle,
                        'top_pid': tpid, 'top_code': tinfo['code'],
                        'top_name': tinfo['name']})
                    if len(matches) >= cap:
                        break
                if len(matches) >= cap:
                    break
        except Exception as exc:
            _logger.warning('MPP search_tree failed for plan %s: %s',
                            plan_id, exc)
        return {'matches': matches, 'total': len(matches)}

    # ------------------------------------------------------------------
    # Tab 3: supplier summary + MO creation (fulfillment, writes POs/MOs).
    # Subcontract chain: subcontract lines are ordered from their seller
    # via a normal PO (per-seller Create RFQ). Confirming that PO runs
    # Odoo's standard subcontract receipt + subcontract-MO chain, so the
    # subcontract MO is never created here. Make lines get draft MOs
    # below, linked by one procurement.group per plan + origin=plan.
    # ------------------------------------------------------------------
    @api.model
    def get_supplier_summary(self, plan_id):
        """Tab 3 data: suppliers with estimated USD + production lines.

        Supplier rows are split per (seller, source company): a seller
        whose lines were last bought from the USA gets its own USA row
        (TR RFQ / US RFQ buttons), because the draft RFQ is created in
        that company. Totals: total_usd = SUM(rolled_usd(unit, children
        included) x order_qty). Each supplier carries its parts in
        'lines' (code/name/order_qty/uom/route/prices) so the client can
        expand the supplier row and show which parts are bought there.
        @param plan_id Plan ID.
        @return Dict with suppliers, supplier_count, grand_total_usd,
            production rows (make/subcontract with linked docs),
            rfq/mo counts and lists.
        """
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            raise UserError(_('Plan not found.'))
        suppliers = {}
        for line in plan.line_ids.filtered(
                lambda l: l.route_type in ('buy', 'subcontract')
                and (l.order_qty or 0) > 0 and l.seller_id):
            sid = line.seller_id.id
            cid = line.last_company_id.id if line.last_company_id \
                else plan.company_id.id
            key = (sid, cid)
            s = suppliers.setdefault(key, {
                'seller_id': sid,
                'seller_name': line.seller_id.display_name,
                'company_id': cid,
                'company': self._mpp_company_code(env_sudo, cid),
                'line_count': 0, 'total_usd': 0.0,
                'route_types': set(), 'currency_names': set(),
                'lines': [],
            })
            s['line_count'] += 1
            _qty = float(line.order_qty or 0.0)
            _rolled = float(line.rolled_usd or 0.0)
            s['total_usd'] += _rolled * _qty
            s['route_types'].add(line.route_type or '')
            if line.last_currency_id:
                s['currency_names'].add(line.last_currency_id.name)
            s['lines'].append({
                'line_id': line.id,
                'product_id': line.product_id.id,
                'code': line.product_id.default_code or '',
                'name': line.product_id.name or '',
                'order_qty': line.order_qty,
                'uom': _mpp_uom_en(
                    line.uom_id.name if line.uom_id else ''),
                'route': line.route_type,
                'seller': line.seller_id.display_name
                if line.seller_id else '',
                'last_price': line.last_price,
                'last_currency': line.last_currency_id.name
                if line.last_currency_id else '',
                'last_usd': line.last_price_usd,
                'last_date': self._mpp_month_year(line.last_date),
                'rolled_usd': line.rolled_usd,
                'total_usd': round(_rolled * _qty, 2),
            })
        po_by_seller = {}
        for po in plan.purchase_order_ids:
            po_by_seller.setdefault(
                (po.partner_id.id, po.company_id.id), []).append({
                    'id': po.id, 'name': po.name, 'state': po.state,
                    'amount_total': po.amount_total,
                    'currency': po.currency_id.name
                    if po.currency_id else '',
                })
        sup_list = []
        for (sid, cid), s in sorted(
                suppliers.items(),
                key=lambda kv: ((kv[1]['seller_name'] or '').lower(),
                               kv[1]['company'] or '')):
            rfqs = po_by_seller.get((sid, cid), [])
            sup_list.append({
                'seller_id': sid,
                'seller_name': s['seller_name'],
                'company_id': cid,
                'company': s['company'],
                # Button label: TR RFQ / US RFQ.
                'rfq_label': '%s RFQ' % (
                    'TR' if s['company'] == 'TR' else 'US'),
                'line_count': s['line_count'],
                'total_usd': round(s['total_usd'], 2),
                'routes': sorted(s['route_types']),
                'currencies': sorted(s['currency_names']),
                'lines': sorted(
                    s['lines'],
                    key=lambda r: ((r['code'] or ''),
                                   (r['name'] or ''))),
                'rfqs': rfqs,
                'has_draft_rfq': any(
                    r['state'] == 'draft' for r in rfqs),
            })
        # Make lines: is a normal-type BOM available (MO creatable)?
        make_lines = plan.line_ids.filtered(
            lambda l: l.route_type == 'make'
            and (l.order_qty or 0) > 0)
        tmpl_ok = set()
        if make_lines:
            tmpl_of = {}
            for pr in env_sudo['product.product'].browse(
                    make_lines.mapped('product_id').ids).read(
                    ['product_tmpl_id']):
                tmpl_of[pr['id']] = pr['product_tmpl_id'][0]
            for b in env_sudo['mrp.bom'].search(
                    [('product_tmpl_id', 'in', list(set(
                        tmpl_of.values()))),
                     ('type', '=', 'normal')]):
                tmpl_ok.add(b.product_tmpl_id.id)
            prod_tmpl = tmpl_of
        else:
            prod_tmpl = {}
        production = []
        for line in plan.line_ids.filtered(
                lambda l: l.route_type in ('make', 'subcontract')
                and (l.order_qty or 0) > 0):
            mo = False
            if line.mo_id:
                mo = {'id': line.mo_id.id, 'name': line.mo_id.name,
                      'state': line.mo_id.state}
            po = False
            if line.purchase_order_id:
                _po = line.purchase_order_id
                po = {'id': _po.id, 'name': _po.name,
                      'state': _po.state}
            production.append({
                'line_id': line.id,
                'code': line.product_id.default_code or '',
                'name': line.product_id.name or '',
                'route': line.route_type,
                'order_qty': line.order_qty,
                'uom': _mpp_uom_en(
                    line.uom_id.name if line.uom_id else ''),
                'seller': line.seller_id.display_name
                if line.seller_id else '',
                'mo': mo,
                'mo_creatable': line.route_type == 'make' and not mo
                and prod_tmpl.get(line.product_id.id) in tmpl_ok,
                'po': po,
            })
        production.sort(key=lambda r: (r['route'] or '',
                                       r['code'] or '',
                                       r['name'] or ''))
        grand = sum(s['total_usd'] for s in sup_list)
        return {
            'plan_id': plan.id,
            'plan_name': plan.name,
            'state': plan.state,
            'suppliers': sup_list,
            'supplier_count': len({s['seller_id']
                                   for s in sup_list}),
            'grand_total_usd': round(grand, 2),
            'production': production,
            'rfq_count': len(plan.purchase_order_ids),
            'mo_count': len(plan.mo_ids),
            'mos': [{
                'id': m.id, 'name': m.name, 'state': m.state,
                'product': m.product_id.display_name,
            } for m in plan.mo_ids],
        }

    @api.model
    def action_create_mos(self, plan_id, line_ids=None):
        """Create draft MOs for make lines (idempotent).

        Lines already linked to an MO are skipped; lines without a
        normal-type BOM are reported, never forced.
        @param plan_id Plan ID.
        @param line_ids Optional line IDs (None = all make lines).
        @return Dict with created/skipped plus a fresh supplier summary.
        """
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            raise UserError(_('Plan not found.'))
        lines = plan.line_ids.filtered(
            lambda l: l.route_type == 'make'
            and (l.order_qty or 0) > 0)
        if line_ids:
            want = set()
            for _i in line_ids:
                try:
                    want.add(int(_i))
                except (TypeError, ValueError):
                    continue
            lines = lines.filtered(lambda l: l.id in want)
        if not lines:
            raise UserError(_('No make lines to manufacture.'))
        picking = env_sudo['stock.picking.type'].search([
            ('code', '=', 'mrp_operation'),
            ('company_id', '=', plan.company_id.id),
        ], limit=1)
        if not picking:
            raise UserError(_(
                'No manufacturing operation type found for TR.'))
        group = env_sudo['procurement.group'].search(
            [('name', '=', plan.name)], limit=1)
        if not group:
            group = env_sudo['procurement.group'].create({
                'name': plan.name, 'move_type': 'direct',
            })
        src = picking.default_location_src_id
        if not src:
            src = env_sudo['stock.location'].search([
                ('usage', '=', 'internal'),
                ('company_id', '=', plan.company_id.id),
            ], limit=1)
        dst = picking.default_location_dest_id
        if not dst:
            dst = env_sudo['stock.location'].search([
                ('usage', '=', 'production'),
                ('company_id', '=', plan.company_id.id),
            ], limit=1)
        if not src or not dst:
            raise UserError(_(
                'Manufacturing source/destination locations not found.'))
        bom_cache = {}

        def _normal_bom(pid):
            prod = env_sudo['product.product'].browse(pid)
            if not prod.exists():
                return False
            tid = prod.product_tmpl_id.id
            if tid not in bom_cache:
                b = env_sudo['mrp.bom'].search([
                    ('product_tmpl_id', '=', tid),
                    ('product_id', '=', pid),
                    ('type', '=', 'normal'),
                ], limit=1)
                if not b:
                    b = env_sudo['mrp.bom'].search([
                        ('product_tmpl_id', '=', tid),
                        ('type', '=', 'normal'),
                    ], limit=1)
                bom_cache[tid] = b
            return bom_cache[tid]

        created, skipped = [], []
        for line in lines:
            if line.mo_id:
                skipped.append({
                    'line_id': line.id,
                    'code': line.product_id.default_code or '',
                    'reason': _('MO already linked: %s')
                    % line.mo_id.name,
                })
                continue
            bom = _normal_bom(line.product_id.id)
            if not bom:
                skipped.append({
                    'line_id': line.id,
                    'code': line.product_id.default_code or '',
                    'reason': _('No normal-type BOM found.'),
                })
                continue
            try:
                mo = env_sudo['mrp.production'].create({
                    'product_id': line.product_id.id,
                    'product_qty': float(line.order_qty),
                    'product_uom_id': line.uom_id.id
                    if line.uom_id else line.product_id.uom_id.id,
                    'bom_id': bom.id,
                    'picking_type_id': picking.id,
                    'location_src_id': src.id,
                    'location_dest_id': dst.id,
                    'company_id': plan.company_id.id,
                    'date_planned_start': fields.Datetime.now(),
                    'origin': plan.name,
                    'procurement_group_id': group.id,
                })
            except Exception as exc:
                _logger.exception(
                    'MPP MO creation failed for line %s (%s).',
                    line.id, line.product_id.default_code)
                skipped.append({
                    'line_id': line.id,
                    'code': line.product_id.default_code or '',
                    'reason': str(exc),
                })
                continue
            line.write({'mo_id': mo.id})
            created.append({
                'id': mo.id, 'name': mo.name,
                'product': line.product_id.display_name,
                'qty': float(line.order_qty),
            })
        if created:
            plan.write({'mo_ids': [(4, c['id']) for c in created]})
        return {
            'created': created,
            'skipped': skipped,
            'supplier_summary': self.get_supplier_summary(plan.id),
        }


class MatiaProcurementPlanLine(models.Model):
    _name = 'matia.procurement.plan.line'
    _description = 'Matia Preview Plan Line'

    plan_id = fields.Many2one('matia.procurement.plan', required=True,
                              ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    level = fields.Integer(default=0)
    gross_qty = fields.Float(digits=(16, 3))
    stock_tr = fields.Float(digits=(16, 3))
    reserved_tr = fields.Float(digits=(16, 3))
    avail_tr = fields.Float(digits=(16, 3))
    stock_us = fields.Float(digits=(16, 3))
    reserved_us = fields.Float(digits=(16, 3))
    avail_us = fields.Float(digits=(16, 3))
    incoming_info = fields.Float(
        digits=(16, 3),
        help='Info: confirmed incoming PO qty (NOT netted).')
    open_mo_info = fields.Float(
        digits=(16, 3),
        help='Info: open MO production (NOT netted).')
    net_qty = fields.Float(digits=(16, 3))
    order_qty = fields.Float(digits=(16, 3))
    uom_id = fields.Many2one('uom.uom')
    route_type = fields.Selection([
        ('buy', 'Buy'),
        ('make', 'Make'),
        ('subcontract', 'Subcontract'),
        ('unknown', 'Unknown'),
    ], default='unknown', required=True)
    seller_id = fields.Many2one('res.partner')
    unit_price = fields.Float(digits=(16, 4))
    subtotal = fields.Float(digits=(16, 2))
    last_price = fields.Float(
        digits=(16, 4),
        help='Last purchase unit price in its own currency, per PO UoM '
             '(snapshot, NOT scaled by BOM qty).')
    last_currency_id = fields.Many2one('res.currency')
    last_uom_id = fields.Many2one(
        'uom.uom',
        help='PO line UoM of the last purchase (snapshot). Rolled costs '
             'convert this price to the plan line UoM before multiplying '
             'by BOM qty.')
    last_price_usd = fields.Float(
        digits=(16, 4),
        help='Last purchase price per PO UoM converted to USD at the USD '
             'rate of the last purchase date (snapshot).')
    last_date = fields.Date(
        help='Last purchase date (shown as Mon YYYY).')
    last_company_id = fields.Many2one(
        'res.company', readonly=True,
        help='Company of the last purchase (TR or USA). The draft RFQ '
             'for this line is created in this company.')
    rolled_usd = fields.Float(
        digits=(16, 4),
        help='Rolled-up USD unit cost: own last-buy USD price plus '
             'children rolled costs (no operation costing).')
    rolled_total_usd = fields.Float(
        digits=(16, 2),
        help='Rolled USD unit cost x gross qty.')
    rolled_try = fields.Float(
        digits=(16, 4),
        help='Rolled-up TRY unit cost: own last-buy price in TRY '
             '(at last buy date rate) plus children rolled costs.')
    rolled_total_try = fields.Float(
        digits=(16, 2),
        help='Rolled TRY unit cost x gross qty.')
    min_qty_warn = fields.Char()
    note = fields.Text()
    mo_id = fields.Many2one(
        'mrp.production', readonly=True,
        help='Draft MO created from this make line (if any).')
