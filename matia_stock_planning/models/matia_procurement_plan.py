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
_MPP_KIT_BOMS = [
    {'key': 'base', 'preferred_id': 1766,
     'names': ['TekRMD Common Parts v2', 'TekRMD Common Parts']},
    {'key': 'screws', 'preferred_id': 1736,
     'names': ['TekRMD Common Screws']},
    {'key': 'outdoor', 'preferred_id': 1737,
     'names': ['TekRMD Outdoor Parts']},
    {'key': 'seat', 'preferred_id': 1738,
     'names': ['TekRMD Seat Parts']},
]

_MPP_MAX_LEVEL = 10
_MPP_TR_COMPANY_ID = 1
_MPP_US_COMPANY_ID = 2


def _mpp_env_sudo(self):
    """sudo env covering all companies (proven pattern from this module)."""
    all_company_ids = self.env['res.company'].with_context(
        active_test=False).sudo().search([]).ids
    return self.with_context(
        allowed_company_ids=all_company_ids,
        active_test=False,
    ).sudo().env


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
    _description = 'Matia Bulk Procurement/Production Preview Plan (TR)'
    _order = 'id desc'

    name = fields.Char(required=True, default=lambda self: _('New'))
    company_id = fields.Many2one(
        'res.company', required=True, default=_MPP_TR_COMPANY_ID,
        help='This plan is for the TR company only (ID=1).')
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
        tr_locs, _ncr = _mpp_tr_stock_locs(env_sudo)
        # USA locations (info only, excluded from netting)
        usa_locs = []
        for loc in env_sudo['stock.location'].search(
                [('usage', '=', 'internal')]):
            cname = loc.complete_name or ''
            cid = loc.company_id.id if loc.company_id else False
            if ('WHUS' in cname or cid == _MPP_US_COMPANY_ID) and 'NCR' not in cname \
                    and cname.startswith('WHUS/Stock'):
                usa_locs.append(loc.id)

        tr_qty, usa_qty, reserved = {}, {}, {}
        if pids and tr_locs:
            for sq in env_sudo['stock.quant'].read_group(
                    [('product_id', 'in', pids),
                     ('location_id', 'in', tr_locs)],
                    ['product_id', 'quantity', 'reserved_quantity'],
                    ['product_id']):
                pid = sq['product_id'][0]
                tr_qty[pid] = float(sq.get('quantity') or 0.0)
                reserved[pid] = float(sq.get('reserved_quantity') or 0.0)
        if pids and usa_locs:
            for sq in env_sudo['stock.quant'].read_group(
                    [('product_id', 'in', pids),
                     ('location_id', 'in', usa_locs)],
                    ['product_id', 'quantity'],
                    ['product_id']):
                usa_qty[sq['product_id'][0]] = float(
                    sq.get('quantity') or 0.0)

        items = []
        for pid, info in sorted(
                top_map.items(),
                key=lambda kv: kv[1]['display_name'] or ''):
            t = tr_qty.get(pid, 0.0)
            r = reserved.get(pid, 0.0)
            u = usa_qty.get(pid, 0.0)
            items.append(dict(
                info,
                stock_tr=t,
                reserved_tr=r,
                avail_tr=max(0.0, t - r),
                stock_usa=u,
                # Fill-to-N base: physical on-hand TR+USA, reserves
                # ignored (user rule for the Fill-to-N button).
                fill_base=max(0.0, t + u),
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

        # TR stock (single read_group) + info columns
        tr_locs, _ncr = _mpp_tr_stock_locs(env_sudo)
        pids = list(need)
        onhand, reserv = {}, {}
        if tr_locs:
            for sq in env_sudo['stock.quant'].read_group(
                    [('product_id', 'in', pids),
                     ('location_id', 'in', tr_locs)],
                    ['product_id', 'quantity', 'reserved_quantity'],
                    ['product_id']):
                pid = sq['product_id'][0]
                onhand[pid] = float(sq.get('quantity') or 0.0)
                reserv[pid] = float(sq.get('reserved_quantity') or 0.0)

        # Net cascade (user rule): targets seed demand; nodes are
        # processed parent-first (Kahn topological order over edges).
        # Each node deducts its own avail from its demand, and children
        # receive only the NET qty x usage. Phantom nodes hold no stock
        # and pass the full demand through. Shared sub-products
        # accumulate demand from every parent before they are netted.
        all_net_pids = set(need) | set(edges)
        for _ep, _ech in edges.items():
            all_net_pids.update(_ech)
        avail_map = {}
        for _ap in all_net_pids:
            _oh = max(0.0, onhand.get(_ap, 0.0))
            _rs = max(0.0, reserv.get(_ap, 0.0))
            avail_map[_ap] = max(0.0, _oh - _rs)
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
                        demand[_c] += _n * float(_q or 0.0)
                    except (TypeError, ValueError):
                        continue

        # Info: confirmed incoming POs + open MO output (NOT netted, display only)
        incoming, mo_out = {}, {}
        po_ids = env_sudo['purchase.order'].search([
            ('company_id', '=', _MPP_TR_COMPANY_ID),
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
            ('company_id', '=', _MPP_TR_COMPANY_ID),
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
            avail = max(0.0, oh - rs)
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
                'avail_tr': avail,
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
        if tmpl_ids:
            for s in Supplier.search_read([
                    ('product_tmpl_id', 'in', tmpl_ids),
            ], ['product_tmpl_id', 'name', 'price', 'min_qty',
                'currency_id', 'product_uom', 'sequence']):
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
                return float(line.last_price_usd or 0.0)
            return 0.0

        def _own_try(pid):
            line = line_by_pid.get(pid)
            if not line or line.route_type not in ('buy', 'subcontract'):
                return 0.0
            price = float(line.last_price or 0.0)
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
                'last_price_usd': 0.0, 'last_date': False,
                'last_company_id': False}
        if not lb:
            return vals
        price = float(lb.get('price_unit') or 0.0)
        cur = lb.get('currency_id')
        cur_id = cur[0] if cur else False
        buy_dt = None
        if lb.get('order_id') and lb['order_id'][0] in order_dates:
            buy_dt = order_dates[lb['order_id'][0]]
        elif lb.get('date_planned'):
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
                'name': line.product_id.display_name,
                'level': line.level,
                'gross': line.gross_qty,
                'stock_tr': line.stock_tr,
                'reserved_tr': line.reserved_tr,
                'avail_tr': line.avail_tr,
                'incoming_info': line.incoming_info,
                'open_mo_info': line.open_mo_info,
                'net': line.net_qty,
                'order_qty': line.order_qty,
                'uom': line.uom_id.name if line.uom_id else '',
                'seller': line.seller_id.display_name
                if line.seller_id else '',
                'price': line.unit_price,
                'subtotal': line.subtotal,
                'last_price': line.last_price,
                'last_currency': line.last_currency_id.name
                if line.last_currency_id else '',
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
                'name': line.product_id.display_name,
                'order_qty': line.order_qty,
                'price': line.unit_price,
                'subtotal': line.subtotal,
                'last_price': line.last_price,
                'last_currency': line.last_currency_id.name
                if line.last_currency_id else '',
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
    # Single-screen flow: create_plan -> get_tree_with_cost.
    # ------------------------------------------------------------------
    @api.model
    def get_tree_with_cost(self, plan_id):
        """Explode + net + suppliers, then return capacity-style groups.

        Groups are the 4 kit BOMs; items are the kit's top products
        (level 0). Children load lazily via get_sub_bom_cost.
        @param plan_id Plan ID from create_plan.
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
        if plan.line_ids and (plan.built_target_json or '') == (
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
        prod_by_id = {}
        if targets:
            for pr in env_sudo['product.product'].browse(
                    list(targets)).read(
                    ['default_code', 'name', 'display_name', 'uom_id']):
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
        kit_cfgs = _mpp_find_kit_boms(env_sudo)
        # One query for kit-line templates missing from bom_by_tmpl
        # (was: one search per line in the loop below).
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
        for kit in kit_cfgs:
            key = kit['key']
            bom = kit['bom']
            items = []
            for bl in bom.bom_line_ids:
                pid = bl.product_id.id
                if pid not in targets:
                    continue
                pr = prod_by_id.get(pid, {})
                line = line_by_pid.get(pid)
                tmpl_id = bl.product_id.product_tmpl_id.id
                has_bom = tmpl_id in bom_by_tmpl \
                    or tmpl_id in extra_bom_tmpls
                avail = line.avail_tr if line else 0.0
                items.append({
                    'product_id': pid,
                    'code': bl.product_id.default_code or '',
                    'name': bl.product_id.display_name,
                    'display': pr.get('display_name')
                    or bl.product_id.display_name,
                    'bom_qty': 1.0,
                    'uom': pr.get('uom_id', [0, ''])[1]
                    if pr.get('uom_id') else (
                        bl.product_uom_id.name
                        if bl.product_uom_id else ''),
                    'has_bom': bool(has_bom),
                    'level': 0,
                    'stock_tr': line.stock_tr if line else 0.0,
                    'reserved_tr': line.reserved_tr if line else 0.0,
                    'avail_tr': avail,
                    'gross': line.gross_qty if line else targets.get(pid, 0),
                    # Planned = net cascade value for tops: target minus
                    # own avail (level-0 nodes have no parents, so this is
                    # exact). Children show their own net via sub-BOM.
                    'planned': max(
                        0.0, float(targets.get(pid, 0)) - avail),
                    'producible': int(math.floor(avail))
                    if avail > 0 else 0,
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
        """Children of one product with TR avail + cost snapshot.

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
        tr_locs, _ncr = _mpp_tr_stock_locs(env_sudo)
        onhand, reserv = {}, {}
        if child_ids and tr_locs:
            for sq in env_sudo['stock.quant'].read_group(
                    [('product_id', 'in', child_ids),
                     ('location_id', 'in', tr_locs)],
                    ['product_id', 'quantity', 'reserved_quantity'],
                    ['product_id']):
                pid = sq['product_id'][0]
                onhand[pid] = float(sq.get('quantity') or 0.0)
                reserv[pid] = float(sq.get('reserved_quantity') or 0.0)
        # Snapshot: plan lines first, else last PO line lookup.
        snap = {}
        plan = env_sudo['matia.procurement.plan'].browse(
            int(plan_id)) if plan_id else False
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
            avail = max(0.0, oh - rs)
            bqty = float(bl.product_qty or 1.0)
            line = snap.get(pid)
            if line:
                lp = float(line.last_price or 0.0)
                lcur = line.last_currency_id.name \
                    if line.last_currency_id else ''
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
                rtry, rusd = ltry, lusd
                _lp = lb.get('partner_id')
                seller = _lp[1] if _lp else ''
                lcompany = self._mpp_company_code(
                    env_sudo, lb.get('company_id'))
            has_bom = cp.product_tmpl_id.id in bom_tmpls
            items.append({
                'product_id': pid,
                'code': cp.default_code or '',
                'name': cp.display_name,
                'bom_qty': bqty,
                'gross': bqty * mult,
                # Branch demand = parent NET x usage; net deducts own
                # avail (same cascade rule as the explosion).
                'planned': bqty * mult,
                'net': max(0.0, bqty * mult - avail),
                'uom': bl.product_uom_id.name
                if bl.product_uom_id else '',
                'has_bom': has_bom,
                'stock_tr': oh,
                'reserved_tr': rs,
                'avail_tr': avail,
                'producible': int(math.floor(avail / bqty))
                if bqty > 0 and avail > 0 else 0,
                'seller': seller,
                'last_company': lcompany,
                'last_price': lp,
                'last_currency': lcur,
                'last_usd': lusd,
                'last_try': ltry,
                'last_date': ldate,
                'rolled_try': rtry,
                'rolled_usd': rusd,
            })
        items.sort(key=lambda r: (r['code'] or '', r['name'] or ''))
        return {'items': items}

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
        included) x order_qty). No TRY, no product rows.
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
            })
            s['line_count'] += 1
            s['total_usd'] += float(line.rolled_usd or 0.0) * float(
                line.order_qty or 0.0)
            s['route_types'].add(line.route_type or '')
            if line.last_currency_id:
                s['currency_names'].add(line.last_currency_id.name)
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
                'name': line.product_id.display_name,
                'route': line.route_type,
                'order_qty': line.order_qty,
                'uom': line.uom_id.name if line.uom_id else '',
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
    _description = 'Matia Preview Plan Line (TR)'

    plan_id = fields.Many2one('matia.procurement.plan', required=True,
                              ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    level = fields.Integer(default=0)
    gross_qty = fields.Float(digits=(16, 3))
    stock_tr = fields.Float(digits=(16, 3))
    reserved_tr = fields.Float(digits=(16, 3))
    avail_tr = fields.Float(digits=(16, 3))
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
        help='Last purchase unit price in its own currency (snapshot).')
    last_currency_id = fields.Many2one('res.currency')
    last_price_usd = fields.Float(
        digits=(16, 4),
        help='Last purchase price converted to USD at the USD rate '
             'of the last purchase date (snapshot).')
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
