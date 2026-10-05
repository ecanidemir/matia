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
import math

from odoo import api, fields, models, _
from odoo.exceptions import UserError


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
    currency_id = fields.Many2one(
        'res.currency', help='Total cost currency (default company).')
    total_cost = fields.Float(compute='_compute_total_cost', store=True)
    line_count = fields.Integer(compute='_compute_line_count', store=True)
    note = fields.Text()
    line_ids = fields.One2many('matia.procurement.plan.line', 'plan_id')
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
            if ('WHUS' in cname or cid == 2) and 'NCR' not in cname \
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
            items.append(dict(
                info,
                stock_tr=t,
                reserved_tr=r,
                avail_tr=max(0.0, t - r),
                stock_usa=usa_qty.get(pid, 0.0),
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
            net = gross - avail
            net_qty = int(math.ceil(net)) if net > 0 else 0
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
        return self._plan_summary(env_sudo, plan)

    # ------------------------------------------------------------------
    # Screen 3: supplier assignment + cost preview (writes: plan lines only)
    # Last purchase price is shown in its own currency plus a USD
    # conversion using the USD rate of the last purchase date.
    # ------------------------------------------------------------------
    @api.model
    def action_assign_suppliers(self, plan_id):
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            raise UserError(_('Plan not found.'))

        POLine = env_sudo['purchase.order.line']
        Supplier = env_sudo['product.supplierinfo']
        # Price snapshot for every purchased line (buy + subcontract),
        # seller assignment only for buy lines with an order qty.
        cost_lines = plan.line_ids.filtered(
            lambda l: l.route_type in ('buy', 'subcontract')
            and (l.gross_qty or 0) > 0)
        buy_pids = cost_lines.mapped('product_id').ids
        # Last purchase per product (TR confirmed POs first).
        # pid -> {partner_id, price_unit, currency_id, order_id, date_planned}
        last_buy = {}
        order_ids = set()
        if buy_pids:
            for pid in buy_pids:
                found = POLine.search_read([
                    ('product_id', '=', pid),
                    ('order_id.company_id', '=', _MPP_TR_COMPANY_ID),
                    ('order_id.state', '!=', 'cancel'),
                ], ['partner_id', 'date_planned', 'price_unit',
                    'currency_id', 'order_id'],
                    limit=1, order='date_planned desc, id desc')
                if not found:
                    found = POLine.search_read([
                        ('product_id', '=', pid),
                        ('order_id.state', '!=', 'cancel'),
                    ], ['partner_id', 'date_planned', 'price_unit',
                        'currency_id', 'order_id'],
                        limit=1, order='date_planned desc, id desc')
                if found:
                    last_buy[pid] = found[0]
                    if found[0].get('order_id'):
                        order_ids.add(found[0]['order_id'][0])
        # PO date (date_order) in one batch; fallback to line date_planned.
        order_dates = {}
        if order_ids:
            for o in env_sudo['purchase.order'].browse(
                    list(order_ids)).read(['date_order']):
                if o.get('date_order'):
                    order_dates[o['id']] = fields.Datetime.from_string(
                        o['date_order']) if isinstance(
                        o['date_order'], str) else o['date_order']

        usd = env_sudo['res.currency'].search(
            [('name', '=', 'USD')], limit=1)

        tmpl_map = {}
        for pr in env_sudo['product.product'].browse(buy_pids).read(
                ['product_tmpl_id', 'seller_ids', 'uom_id']):
            tmpl_map[pr['id']] = pr

        for line in cost_lines:
            pid = line.product_id.id
            pr = tmpl_map.get(pid, {})
            lb = last_buy.get(pid, {})
            vals = self._last_buy_vals(
                env_sudo, plan, usd, lb, order_dates)
            if line.route_type != 'buy' or not (line.order_qty or 0) > 0:
                # Price snapshot only (no seller / no order).
                line.write(vals)
                continue
            seller = False
            lp = lb.get('partner_id')
            sellers = Supplier.search_read([
                ('product_tmpl_id', '=', pr.get('product_tmpl_id', [0])[0]
                 if pr.get('product_tmpl_id') else 0),
            ], ['name', 'price', 'min_qty', 'currency_id',
                'product_uom', 'sequence'])
            if lp:
                cand = [s for s in sellers if s['name'][0] == lp[0]]
                if cand:
                    seller = sorted(
                        cand, key=lambda s: s['price'])[0]
            if not seller and sellers:
                seller = sorted(
                    sellers,
                    key=lambda s: (s.get('sequence') or 99,
                                   s['price']))[0]
            if not seller:
                vals['note'] = _('No supplier (no seller defined).')
                line.write(vals)
                continue
            # UoM-converted unit price
            price = float(seller['price'] or 0.0)
            s_uom = seller.get('product_uom')
            if s_uom and line.uom_id and s_uom[0] != line.uom_id.id:
                s_uom_rec = env_sudo['uom.uom'].browse(s_uom[0])
                price = line.uom_id._compute_quantity(
                    1.0, s_uom_rec, round=False) * price \
                    if price else 0.0
                # Note: price is per seller UoM; qty is in product UoM.
                # Amount = order_qty(product UoM) * converted price.
            warn = ''
            if seller.get('min_qty') and line.order_qty < seller['min_qty']:
                warn = _('Min. order %s') % seller['min_qty']
            # Currency: convert to the company currency
            cur = seller.get('currency_id')
            if cur and plan.currency_id and cur[0] != plan.currency_id.id:
                cur_rec = env_sudo['res.currency'].browse(cur[0])
                price = cur_rec._convert(
                    price, plan.currency_id, plan.company_id,
                    fields.Date.today())
            vals.update({
                'seller_id': seller['name'][0],
                'unit_price': price,
                'subtotal': price * float(line.order_qty or 0.0),
                'min_qty_warn': warn,
            })
            line.write(vals)
        plan.state = 'supplier_review'
        rollup = self._compute_rollup(env_sudo, plan)
        summary = self._plan_summary(env_sudo, plan)
        summary['kits'] = rollup['kits']
        summary['rolled_total_usd'] = rollup['total']
        return summary

    @api.model
    def _compute_rollup(self, env_sudo, plan):
        """Bottom-up rolled USD cost per unit.

        Each leaf purchase price (last_price_usd of buy/subcontract
        lines) is multiplied by its usage qty and summed upward to the
        top products and kits. No operation costing: make/phantom
        nodes contribute only their children's cost.
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

        memo = {}
        visiting = set()

        def _own(pid):
            line = line_by_pid.get(pid)
            if line and line.route_type in ('buy', 'subcontract'):
                return float(line.last_price_usd or 0.0)
            return 0.0

        def _unit(pid):
            if pid in memo:
                return memo[pid]
            if pid in visiting:
                return 0.0  # cycle guard
            visiting.add(pid)
            total = _own(pid)
            for c, q in children.get(pid, {}).items():
                total += _unit(c) * (q or 0.0)
            visiting.discard(pid)
            memo[pid] = total
            return total

        for pid, line in line_by_pid.items():
            unit = _unit(pid)
            line.write({
                'rolled_usd': unit,
                'rolled_total_usd': unit * float(line.gross_qty or 0.0),
            })

        # Kit totals from entry quantities (members only, no double count:
        # sub-product cost already lives inside each entry's rolled cost).
        try:
            targets = json.loads(plan.target_json or '{}')
        except ValueError:
            targets = {}
        kit_of = {}
        kit_names = {}
        for kit in _mpp_find_kit_boms(env_sudo):
            key = kit['key']
            kit_names[key] = kit['bom'].product_tmpl_id.name or key
            for bl in kit['bom'].bom_line_ids:
                kit_of.setdefault(bl.product_id.id, key)
        kits = {}
        grand = 0.0
        for pid_str, tq in targets.items():
            try:
                pid = int(pid_str)
                tqf = float(tq or 0)
            except (TypeError, ValueError):
                continue
            if tqf <= 0:
                continue
            ext = _unit(pid) * tqf
            grand += ext
            key = kit_of.get(pid, 'other')
            k = kits.setdefault(
                key, {'key': key,
                      'name': kit_names.get(key, 'Other'),
                      'cost': 0.0, 'count': 0})
            k['cost'] += ext
            k['count'] += 1
        return {'kits': list(kits.values()), 'total': grand}

    @api.model
    def _last_buy_vals(self, env_sudo, plan, usd, lb, order_dates):
        """Last-purchase snapshot: price in own currency, USD at the
        historical rate of the purchase date, and date as 'Mon YYYY'."""
        vals = {'last_price': 0.0, 'last_currency_id': False,
                'last_price_usd': 0.0, 'last_date': False}
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
                'unit_usd': line.rolled_usd,
                'rolled_usd': line.rolled_total_usd,
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
    rolled_usd = fields.Float(
        digits=(16, 4),
        help='Rolled-up USD unit cost: own last-buy USD price plus '
             'children rolled costs (no operation costing).')
    rolled_total_usd = fields.Float(
        digits=(16, 2),
        help='Rolled USD unit cost x gross qty.')
    min_qty_warn = fields.Char()
    note = fields.Text()
