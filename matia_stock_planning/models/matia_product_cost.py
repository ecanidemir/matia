# -*- coding: utf-8 -*-
"""Matia Product Cost dashboard (admin-only, read + price overrides).

Global, plan-independent cost page: explodes the same 4 kit BOMs as
the Capacity/Production Plan pages, rolls bottom-up USD costs live
(corrected overrides win, otherwise the latest real purchase), and
hosts the global Prices list (moved out of the Production Plan page).

Creates NO records: cost math is computed on the fly, the only
writes are the manual price overrides (same global table the plan
page reads). All RPC entry points are @api.model with no ensure_one
(JS calls them model-style, like the procurement dashboard).
"""
import calendar
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .matia_procurement_plan import (
    _MPP_MAX_LEVEL,
    _MPP_TR_COMPANY_ID,
    _MPP_US_COMPANY_ID,
    _mpp_env_sudo,
    _mpp_find_kit_boms,
    _mpp_kit_tmpl_ids,
    _mpp_last_buy_scope,
    _mpp_location_routes,
    _mpp_norm_bom_qty,
    _mpp_price_overrides,
    _mpp_product_routes,
    _mpp_search_kit_forest,
    _mpp_stock_per_po_factor,
    _mpp_uom_en,
)


_logger = logging.getLogger(__name__)


# Display order + titles mirror the Capacity page groups.
_MPC_GROUPS = [
    {'key': 'base', 'title': 'Base Parts'},
    {'key': 'outdoor', 'title': 'Outdoor Parts'},
    {'key': 'seat', 'title': 'Seat Parts'},
    {'key': 'screws', 'title': 'Screws'},
]

_MPC_ROUTE_LABELS = {
    'buy': 'Buy',
    'subcontract': 'Subcontract',
    'make': 'Manufacture',
    'kit': 'Kit',
}


def _mpc_month_year(date_val):
    """'Sep 2025' style label, always English regardless of locale."""
    if not date_val:
        return ''
    d = fields.Date.from_string(date_val) if isinstance(
        date_val, str) else date_val
    if hasattr(d, 'month'):
        return '%s %s' % (calendar.month_abbr[d.month], d.year)
    return ''


class MatiaProductCost(models.AbstractModel):
    _name = 'matia.product.cost'
    _description = 'Matia Product Cost Dashboard (stateless)'

    # ----------------------------------------------------------
    # internals
    # ----------------------------------------------------------
    @api.model
    def _mpc_explode(self, env_sudo):
        """Explode the 4 kit BOMs into edges + bulk product info.

        @param env_sudo: sudo environment.
        @return: (kits, tops, children, prod_info) where tops is
            {group_key: [{'pid', 'qty', 'uom'}]} (quantities already
            converted to the product stock UoM), children is
            {pid: {child_pid: qty}}, prod_info is the bulk read dict.
        @raise UserError: when no kit BOM is found.
        """
        kits = _mpp_find_kit_boms(env_sudo)
        if not kits:
            raise UserError(_('No kit BOM found.'))
        Product = env_sudo['product.product']
        Bom = env_sudo['mrp.bom']
        tops = {}
        for kit in kits:
            entries = []
            for bl in kit['bom'].bom_line_ids:
                prod = bl.product_id
                # Single conversion point shared with the plan
                # explosion: BOM-line UoM -> child stock UoM. The
                # zero guard preserves the old inline semantics
                # (a 0-qty line stays 0.0; the helper defaults
                # empty qty to 1.0 for plan lines).
                raw0 = float(bl.product_qty or 0.0)
                qty = _mpp_norm_bom_qty(bl) if raw0 else 0.0
                entries.append({
                    'pid': prod.id,
                    'qty': qty,
                    'uom': _mpp_uom_en(
                        bl.product_uom_id.name
                        if bl.product_uom_id else ''),
                })
            tops[kit['key']] = entries
        # BFS walk storing variant-first BOM edges (depth + cycle
        # guards mirror the procurement explosion logic).
        children = {}
        bom_cache = {}
        seen = set()
        stack = []
        for entries in tops.values():
            for entry in entries:
                stack.append((entry['pid'], 0, ()))
        iter_guard = 0
        while stack:
            iter_guard += 1
            if iter_guard > 60000:
                raise UserError(
                    _('Tree too deep/wide, explosion limited.'))
            pid, level, path = stack.pop()
            if pid in path or level > _MPP_MAX_LEVEL:
                continue
            if pid in seen:
                continue
            seen.add(pid)
            prod = Product.browse(pid)
            if not prod.exists():
                continue
            tmpl_id = prod.product_tmpl_id.id
            if tmpl_id not in bom_cache:
                bom = Bom.search([('product_id', '=', pid)], limit=1)
                if not bom:
                    bom = Bom.search(
                        [('product_tmpl_id', '=', tmpl_id)], limit=1)
                bom_cache[tmpl_id] = bom
            bom = bom_cache[tmpl_id]
            if bom and bom.bom_line_ids:
                edges = children.setdefault(pid, {})
                for bl in bom.bom_line_ids:
                    cprod = bl.product_id
                    # Same shared conversion as the kit tops above.
                    craw0 = float(bl.product_qty or 0.0)
                    qty = _mpp_norm_bom_qty(bl) if craw0 else 0.0
                    edges[cprod.id] = edges.get(cprod.id, 0.0) + qty
                    stack.append(
                        (cprod.id, level + 1, path + (pid,)))
        pids = sorted(set(seen) | {
            e['pid'] for entries in tops.values() for e in entries})
        prod_info = {}
        for pr in Product.browse(pids).read(
                ['default_code', 'name', 'product_tmpl_id',
                 'uom_id', 'uom_po_id']):
            prod_info[pr['id']] = pr
        return kits, tops, children, prod_info

    @api.model
    def _mpc_price_map(self, env_sudo, pids):
        """Live USD price data per product (no plan involved).

        Corrected overrides win; otherwise the latest real purchase
        converted to USD at its historical rate; make/kit products
        have no own price (0.0). Prices are per stock UoM, the unit
        every cost formula uses.

        @param env_sudo: sudo environment.
        @param pids: product.product IDs.
        @return: (price_map, routes) where price_map is
            {pid: {'own_usd', 'last_price', 'last_currency',
            'last_usd', 'last_date', 'seller', 'last_uom',
            'price_factor', 'corrected', 'location',
            'effective_usd'}} and routes is {pid: route key}.
        """
        Mpp = env_sudo['matia.procurement.plan']
        overrides = _mpp_price_overrides(env_sudo, list(pids or []))
        last_buy = Mpp._mpp_last_buys(
            env_sudo, list(pids or []),
            _mpp_last_buy_scope(overrides))
        usd = env_sudo['res.currency'].search(
            [('name', '=', 'USD')], limit=1)
        company = env_sudo['res.company'].browse(_MPP_TR_COMPANY_ID)
        routes = _mpp_product_routes(env_sudo, list(pids or []))
        Product = env_sudo['product.product']
        stock_uoms = {}
        for pr in Product.browse(
                [p for p in (pids or []) if p]).read(['uom_id']):
            _u = pr.get('uom_id')
            stock_uoms[pr['id']] = _u[0] if _u else False
        price_map = {}
        for pid in (pids or []):
            route = routes.get(pid, 'unknown')
            lb = last_buy.get(pid, {})
            price = float(lb.get('price_unit') or 0.0)
            cur = lb.get('currency_id')
            cur_id = cur[0] if cur else False
            cur_name = cur[1] if cur else ''
            pou = lb.get('product_uom')
            pou_id = pou[0] if pou else False
            pou_name = pou[1] if pou else ''
            buy_dt = lb.get('buy_dt')
            if not buy_dt and lb.get('date_planned'):
                dp = lb['date_planned']
                buy_dt = fields.Datetime.from_string(dp) \
                    if isinstance(dp, str) else dp
            buy_date = buy_dt.date() if buy_dt \
                else fields.Date.today()
            last_usd = 0.0
            if lb and price and cur_id and usd:
                try:
                    cur_rec = env_sudo['res.currency'].browse(cur_id)
                    # round=False: keep sub-cent precision (e.g. 0.10
                    # TRY -> ~0.0033 USD); USD rounding (0.01) would
                    # yield 0.0 and the Prices page shows blank USD.
                    last_usd = cur_rec._convert(
                        price, usd, company, buy_date, round=False) \
                        if cur_id != usd.id else price
                except Exception as exc:
                    _logger.warning(
                        'MPC currency conversion failed for '
                        'product %s: %s', pid, exc)
            # PO-UoM price -> stock-UoM price (e.g. per m -> per mm).
            stock_uid = stock_uoms.get(pid)
            factor = 1.0
            try:
                if stock_uid and pou_id and stock_uid != pou_id:
                    stock = env_sudo['uom.uom'].browse(stock_uid)
                    pou_rec = env_sudo['uom.uom'].browse(pou_id)
                    if stock.exists() and pou_rec.exists():
                        factor = stock._compute_quantity(
                            1.0, pou_rec, round=False) or 1.0
            except Exception:
                factor = 1.0
            last_usd_stock = last_usd * factor
            ovr = overrides.get(pid, {})
            corr = float(ovr.get('price') or 0.0)
            own = 0.0
            if route not in ('make', 'kit'):
                own = corr if corr > 0 else last_usd_stock
            _pp = lb.get('partner_id')
            price_map[pid] = {
                'own_usd': own,
                'last_price': price,
                'last_currency': cur_name,
                'last_usd': last_usd_stock,
                'last_date': _mpc_month_year(buy_date)
                if lb else '',
                'seller': _pp[1] if _pp else '',
                'last_uom': _mpp_uom_en(pou_name),
                'price_factor': _mpp_stock_per_po_factor(
                    env_sudo, stock_uid, pou_id or stock_uid),
                'corrected': corr,
                'location': ovr.get('location') or '',
                'effective_usd': own,
            }
        # Kit top products are 'kit' rows (no own price) even when
        # their template carries a buy route.
        try:
            kits = _mpp_find_kit_boms(env_sudo)
            kit_tmpls = _mpp_kit_tmpl_ids(
                env_sudo,
                [k['bom'].product_tmpl_id.id for k in kits
                 if k['bom'].product_tmpl_id])
            tmpl_of = {}
            for pr in env_sudo['product.product'].browse(
                    [p for p in (pids or []) if p]).read(
                    ['product_tmpl_id']):
                _pt = pr.get('product_tmpl_id')
                tmpl_of[pr['id']] = _pt[0] if _pt else False
            for pid in (pids or []):
                if tmpl_of.get(pid) in kit_tmpls:
                    routes[pid] = 'kit'
                    if pid in price_map:
                        price_map[pid]['own_usd'] = 0.0
                        price_map[pid]['effective_usd'] = 0.0
        except Exception:
            pass
        return price_map, routes

    @api.model
    def _mpc_std_usd_map(self, env_sudo, pids):
        """Company-aware standard-price fallback in USD, per stock UoM.

        standard_price IS company-dependent (ir.property rows per
        company; verified live: product 2039 holds 192.61 TRY for
        TR vs 30.0 USD for US). Each side is therefore read from
        ir.property directly (per-company rows, no ORM-context
        shortcut: a force_company-context product read proved
        unreliable live — the TR side kept returning the US
        value):

        - TR side: TR-company standard_price (TRY), converted to
          USD with the TR-company USD rate of the estimated
          last-change day. The day is estimated from stock
          valuation because standard_price has no history table
          and product write dates are unreliable (variant
          write_date always mirrors the last valuation layer;
          template write_date is stale): the latest TR-company
          incoming (quantity > 0) stock.valuation.layer whose
          unit_cost matches the TR standard_price within
          max(0.005, 1e-4 * value). Base currency is TRY, so
          USD = TRY * rate. Products with no matching TR layer
          fall back to the latest overall TR USD rate (flagged).
        - US side: US-company standard_price row. The US company currency is USD, so
          no FX conversion applies (only the stock/PO UoM
          factor, applied by the caller like on the TR side).
          The month-year shown is the latest US-company
          incoming layer when one exists, otherwise blank.

        @param env_sudo: sudo environment.
        @param pids: product.product IDs.
        @return: {pid: {'std_tr_usd': float, 'std_tr_date': str
            (month-year of the TR rate used), 'std_tr_latest':
            bool (True when the fallback latest TR rate was used),
            'std_us_usd': float (0.0 when the US company holds
            no standard_price), 'std_us_date': str (month-year
            of the latest US layer, '' when the product has no
            US incoming layer)}}. All USD values are per stock
            UoM.
        """
        out = {}
        pids = [p for p in (pids or []) if p]
        if not pids:
            return out
        std_field = env_sudo['ir.model.fields'].search(
            [('model', '=', 'product.product'),
             ('name', '=', 'standard_price')], limit=1)
        stds_tr = {}
        stds_us = {}
        if std_field:
            _res = ['product.product,%d' % p for p in pids]
            for prow in env_sudo['ir.property'].search_read(
                    [('fields_id', '=', std_field.id),
                     ('res_id', 'in', _res)],
                    ['res_id', 'company_id', 'value_float']):
                try:
                    _pid = int(
                        (prow.get('res_id') or ',').split(',')[1])
                except (IndexError, TypeError, ValueError):
                    continue
                try:
                    _val = float(prow.get('value_float') or 0.0)
                except (TypeError, ValueError):
                    continue
                _cc = prow.get('company_id')
                _cid = _cc[0] if _cc else False
                if _cid == _MPP_TR_COMPANY_ID:
                    stds_tr[_pid] = _val
                elif _cid == _MPP_US_COMPANY_ID:
                    stds_us[_pid] = _val
                elif not _cid:
                    # Company-independent fallback: only fills
                    # sides with no company-specific row.
                    stds_tr.setdefault(_pid, _val)
                    stds_us.setdefault(_pid, _val)
        live = {pid: std for pid, std in stds_tr.items()
                if std > 0}
        live_us = {pid for pid, std in stds_us.items()
                   if std > 0}
        # One read for both companies; layers arrive newest-first
        # per product so the first hit per side wins.
        layered = list(set(live) | live_us)
        if layered:
            layers = env_sudo['stock.valuation.layer'].search_read(
                [('product_id', 'in', layered),
                 ('quantity', '>', 0)],
                ['product_id', 'unit_cost', 'create_date',
                 'company_id'],
                order='product_id, create_date desc, id desc')
        else:
            layers = []
        tr_match = {}
        us_latest = {}
        for lay in layers:
            _lp = lay.get('product_id')
            pid = _lp[0] if _lp else False
            if not pid or (pid not in live
                           and pid not in live_us):
                continue
            _lc = lay.get('company_id')
            comp = _lc[0] if _lc else False
            try:
                cost = float(lay.get('unit_cost') or 0.0)
            except (TypeError, ValueError):
                continue
            _cd = lay.get('create_date')
            dt = fields.Datetime.from_string(_cd) \
                if isinstance(_cd, str) else _cd
            if not dt:
                continue
            if comp == _MPP_US_COMPANY_ID and pid not in us_latest:
                # US company currency is USD: no FX conversion.
                us_latest[pid] = (cost, dt.date())
            elif comp == _MPP_TR_COMPANY_ID and \
                    pid in live and pid not in tr_match:
                std = live[pid]
                if abs(cost - std) <= max(0.005, 1e-4 * abs(std)):
                    tr_match[pid] = dt.date()
        usd = env_sudo['res.currency'].search(
            [('name', '=', 'USD')], limit=1)
        rate_points = []
        if usd:
            for rr in env_sudo['res.currency.rate'].search_read(
                    [('currency_id', '=', usd.id),
                      ('company_id', '=', _MPP_TR_COMPANY_ID)],
                    ['name', 'rate'], order='name desc'):
                try:
                    _nm = rr.get('name')
                    rd = fields.Date.from_string(_nm) \
                        if isinstance(_nm, str) else _nm
                    rate_points.append(
                        (rd, float(rr.get('rate') or 0.0)))
                except (TypeError, ValueError):
                    continue
        rate_points.sort(key=lambda t: t[0], reverse=True)
        for pid in pids:
            std = stds_tr.get(pid, 0.0)
            tr_usd, tr_date, tr_latest = 0.0, '', False
            if std > 0 and rate_points:
                tgt = tr_match.get(pid)
                rate, rdate, tr_latest = rate_points[0][1], \
                    rate_points[0][0], True
                if tgt:
                    for (rd, rt) in rate_points:
                        if rd <= tgt:
                            rate, rdate, tr_latest = rt, rd, False
                            break
                tr_usd = std * rate
                tr_date = _mpc_month_year(rdate)
            us_usd, us_date = 0.0, ''
            if stds_us.get(pid, 0.0) > 0:
                us_usd = stds_us[pid]
                if pid in us_latest:
                    us_date = _mpc_month_year(
                        us_latest[pid][1])
            out[pid] = {'std_tr_usd': tr_usd, 'std_tr_date': tr_date,
                        'std_tr_latest': tr_latest,
                        'std_us_usd': us_usd, 'std_us_date': us_date}
        return out

    @api.model
    def _mpc_unit_map(self, children, price_map):
        """Memoized bottom-up rolled unit USD per product."""
        memo = {}

        def unit(pid, path=()):
            if pid in memo:
                return memo[pid]
            if pid in path:
                return 0.0
            total = float(price_map.get(pid, {}).get(
                'own_usd') or 0.0)
            for cpid, qty in (children.get(pid) or {}).items():
                total += unit(cpid, path + (pid,)) * float(qty or 0.0)
            memo[pid] = total
            return total

        for pid in (children.keys() | price_map.keys()):
            unit(pid)
        return memo

    # ----------------------------------------------------------
    # RPC: cost tree
    # ----------------------------------------------------------
    @api.model
    def get_cost_tree(self):
        """1-device set cost per group + combo totals (live compute).

        @return: {'groups': [{'key', 'title', 'items',
            'set_total'}], 'combos': {'base', 'full',
            'base_outdoor', 'base_seat'}, 'count': int}.
            Base already includes screws in the combos; item costs
            are rolled bottom-up USD per 1 device set.
        """
        # No ensure_one: called model-style (empty recordset) from JS.
        env_sudo = _mpp_env_sudo(self)
        kits, tops, children, prod_info = self._mpc_explode(env_sudo)
        all_pids = sorted(set(children.keys()) |
                          {c for edges in children.values()
                           for c in edges} |
                          {e['pid'] for entries in tops.values()
                           for e in entries})
        price_map, _routes = self._mpc_price_map(env_sudo, all_pids)
        unit_map = self._mpc_unit_map(children, price_map)
        kit_names = {}
        for kit in kits:
            try:
                kit_names[kit['key']] = kit['bom'].display_name or ''
            except Exception:
                kit_names[kit['key']] = ''
        group_labels = {'base': 'Base', 'outdoor': 'Outdoor',
                        'seat': 'Seat', 'screws': 'Screws'}
        groups = []
        totals = {}
        count = 0
        for cfg in _MPC_GROUPS:
            items = []
            set_total = 0.0
            for entry in tops.get(cfg['key'], []):
                pid = entry['pid']
                info = prod_info.get(pid, {})
                unit_usd = unit_map.get(pid, 0.0)
                ext_usd = unit_usd * float(entry['qty'] or 0.0)
                set_total += ext_usd
                count += 1
                items.append({
                    'product_id': pid,
                    'code': info.get('default_code') or '',
                    'name': info.get('name') or '',
                    'usage': float(entry['qty'] or 0.0),
                    'uom': entry.get('uom') or '',
                    'has_bom': bool(children.get(pid)),
                    'unit_usd': round(unit_usd, 4),
                    'ext_usd': round(ext_usd, 2),
                })
            items.sort(key=lambda r: (r['code'] or '', r['name'] or ''))
            set_total = round(set_total, 2)
            totals[cfg['key']] = set_total
            kit_name = kit_names.get(cfg['key']) or cfg['title']
            groups.append({
                'key': cfg['key'],
                'title': '%s (%s)' % (
                    kit_name, group_labels.get(cfg['key'], '')),
                'label': '%s Parts' % group_labels.get(
                    cfg['key'], ''),
                'items': items,
                'set_total': set_total,
            })
        base = totals.get('base', 0.0) + totals.get('screws', 0.0)
        outdoor = totals.get('outdoor', 0.0)
        seat = totals.get('seat', 0.0)
        return {
            'groups': groups,
            'combos': {
                'base': round(base, 2),
                'full': round(base + outdoor + seat, 2),
                'base_outdoor': round(base + outdoor, 2),
                'base_seat': round(base + seat, 2),
            },
            'count': count,
        }

    @api.model
    def get_sub_bom_cost(self, product_id=False, chain_qty=1.0,
                         path=False):
        """Children of one product's BOM with rolled costs.

        @param product_id: product.product ID to explode.
        @param chain_qty: accumulated parent quantity (per 1 device
            set); child cost scales with it.
        @param path: ancestor product IDs (cycle guard).
        @return: {'items': [{product_id, code, name,
            usage_per_parent, scaled_qty, uom, has_bom, is_cycle,
            unit_usd, ext_usd}]}.
        """
        # No ensure_one: called model-style (empty recordset) from JS.
        env_sudo = _mpp_env_sudo(self)
        try:
            pid = int(product_id)
        except (TypeError, ValueError):
            raise UserError(_('Invalid product.'))
        try:
            chain = float(chain_qty or 1.0)
        except (TypeError, ValueError):
            chain = 1.0
        path = [int(p) for p in (path or []) if p]
        _kits, tops, children, prod_info = self._mpc_explode(env_sudo)
        void = {e['pid'] for entries in tops.values()
                for e in entries}
        all_pids = sorted(set(children.keys()) |
                          {c for edges in children.values()
                           for c in edges} | void | {pid})
        price_map, _routes = self._mpc_price_map(env_sudo, all_pids)
        unit_map = self._mpc_unit_map(children, price_map)
        uom_names = {}
        for pr in env_sudo['product.product'].browse(
                list((children.get(pid) or {}).keys())).read(
                ['uom_id']):
            _uu = pr.get('uom_id')
            uom_names[pr['id']] = _uu[1] if _uu else ''
        items = []
        for cpid, qty in (children.get(pid) or {}).items():
            info = prod_info.get(cpid, {})
            if not info:
                pr = env_sudo['product.product'].browse(cpid)
                if pr.exists():
                    info = {'default_code': pr.default_code or '',
                            'name': pr.name or ''}
            scaled = float(qty or 0.0) * chain
            unit_usd = 0.0 if cpid in path else unit_map.get(cpid, 0.0)
            items.append({
                'product_id': cpid,
                'code': info.get('default_code') or '',
                'name': info.get('name') or '',
                'usage_per_parent': float(qty or 0.0),
                'scaled_qty': scaled,
                'uom': _mpp_uom_en(uom_names.get(cpid) or ''),
                'has_bom': bool(children.get(cpid)),
                'is_cycle': bool(cpid in path),
                'unit_usd': round(unit_usd, 4),
                'ext_usd': round(unit_usd * scaled, 2),
            })
        items.sort(key=lambda r: (r['code'] or '', r['name'] or ''))
        return {'items': items, 'count': len(items)}

    @api.model
    def search_tree(self, query):
        """Full-forest code/name search over the 4 kit BOMs (Cost tab).

        Same match shape as the Production Plan search, but plan-independent:
        walks ALL kit tops so parts buried inside collapsed sub-BOMs are
        found with a single cheap RPC (cap 100, depth 10).

        @param query: raw search text (min 2 chars).
        @return: {'matches': [...], 'total': int}.
        """
        env_sudo = _mpp_env_sudo(self)
        return _mpp_search_kit_forest(env_sudo, query)

    # ----------------------------------------------------------
    # RPC: global prices (moved out of the Production Plan page)
    # ----------------------------------------------------------
    @api.model
    def get_prices(self):
        """Every product in the 4 kit BOMs, plan-independent.

        Same row shape as the old plan Prices tab, but sellers and
        last buys always come from live purchases (never a plan
        snapshot) and no plan record is created or required.

        @return: {'items': [...], 'count': int,
            'override_count': int}. Each item also carries the
            standard-price fallback 'std_usd' (per stock UoM),
            'std_usd_display' (per the product's own purchase
            UoM), 'std_rate_date' (month-year of the USD rate
            used) and 'std_rate_latest' (True when no valuation
            layer matched and the latest rate was used).
        """
        # No ensure_one: called model-style (empty recordset) from JS.
        env_sudo = _mpp_env_sudo(self)
        kits, tops, children, prod_info = self._mpc_explode(env_sudo)
        pids = sorted(set(children.keys()) |
                      {c for edges in children.values()
                       for c in edges} |
                      {e['pid'] for entries in tops.values()
                       for e in entries})
        # Kit top products are not BOM children: include them
        # explicitly as 'kit' rows (same as the old tab).
        Product = env_sudo['product.product']
        for kit in kits:
            kbom = kit['bom']
            kpid = kbom.product_id.id if kbom.product_id else False
            if not kpid and kbom.product_tmpl_id:
                kvar = Product.search(
                    [('product_tmpl_id', '=',
                      kbom.product_tmpl_id.id)], limit=1)
                kpid = kvar.id if kvar else False
            if kpid and kpid not in pids:
                pids.append(kpid)
        for kp in Product.browse(
                [p for p in pids if p not in prod_info]).read(
                ['default_code', 'name', 'product_tmpl_id',
                 'uom_id', 'uom_po_id']):
            prod_info[kp['id']] = kp
        if not pids:
            return {'items': [], 'count': 0, 'override_count': 0}
        price_map, routes = self._mpc_price_map(env_sudo, pids)
        std_map = self._mpc_std_usd_map(env_sudo, pids)
        spf_cache = {}
        loc_pending = {}
        items = []
        for pid in pids:
            info = prod_info.get(pid, {})
            pm = price_map.get(pid, {})
            route = routes.get(pid, 'unknown')
            _pu = info.get('uom_id')
            _ppu = info.get('uom_po_id') or _pu
            stock_uid = _pu[0] if _pu else False
            po_uid = _ppu[0] if _ppu else stock_uid
            price_uom_txt = _mpp_uom_en(
                _ppu[1] if _ppu and len(_ppu) > 1 else '')
            uom_txt = _mpp_uom_en(
                _pu[1] if _pu and len(_pu) > 1 else '')
            corr = float(pm.get('corrected') or 0.0)
            lusd = float(pm.get('last_usd') or 0.0)
            eff = corr if corr > 0 else lusd
            pfactor = float(pm.get('price_factor') or 1.0) or 1.0
            corr_disp = corr * pfactor if corr and pfactor \
                else corr
            # Location-aware standard-price fallback, shown per
            # the product's own purchase UoM (the commercial unit
            # save_price_override converts back from), so the
            # displayed value is exactly what Copy Std stores.
            # The UoM conversion (e.g. per mm -> per m) always
            # applies; only the FX step is TR-only (the US company
            # currency is USD). Without a location the cell shows
            # a 'location needed' placeholder instead of a value.
            std = std_map.get(pid, {})
            loc = (pm.get('location') or '').lower()
            std_usd, std_date, std_latest = 0.0, '', False
            std_needs_loc = False
            if loc == 'us':
                std_usd = float(std.get('std_us_usd') or 0.0)
                std_date = std.get('std_us_date') or ''
            elif loc == 'tr':
                std_usd = float(std.get('std_tr_usd') or 0.0)
                std_date = std.get('std_tr_date') or ''
                std_latest = bool(std.get('std_tr_latest'))
            else:
                std_needs_loc = True
            _pt = info.get('product_tmpl_id')
            if loc in ('tr', 'us') and _pt:
                loc_pending[pid] = (_pt[0], loc)
            spf_key = (stock_uid, po_uid)
            if spf_key not in spf_cache:
                spf_cache[spf_key] = _mpp_stock_per_po_factor(
                    env_sudo, stock_uid, po_uid) or 1.0
            spfactor = spf_cache[spf_key]
            items.append({
                'product_id': pid,
                'code': info.get('default_code') or '',
                'name': info.get('name') or '',
                'route': route,
                'route_label': _MPC_ROUTE_LABELS.get(
                    route, 'Unknown'),
                'seller': pm.get('seller') or '',
                'uom': uom_txt,
                'last_uom': pm.get('last_uom') or '',
                'price_uom': price_uom_txt or uom_txt,
                'price_factor': pfactor,
                'corrected_display': corr_disp,
                'last_price': float(pm.get('last_price') or 0.0),
                'last_currency': pm.get('last_currency') or '',
                'last_usd': lusd,
                'last_date': pm.get('last_date') or '',
                'std_usd': std_usd,
                'std_usd_display': std_usd * spfactor
                if std_usd else 0.0,
                'std_rate_date': std_date,
                'std_rate_latest': std_latest,
                'std_needs_location': std_needs_loc,
                'corrected': corr,
                'location': pm.get('location') or '',
                'effective_usd': eff,
                'has_override': bool(
                    corr > 0 or pm.get('location')),
            })
        # Location-scoped Type display: a TR-made product bought
        # in the US shows 'buy' there (and vice versa). Cost math
        # (effective_usd) deliberately stays on the global route.
        if loc_pending:
            by_loc = {}
            for _pid, (_tm, _lc) in loc_pending.items():
                by_loc.setdefault(_lc, []).append(_tm)
            loc_routes = {}
            for _lc, _tms in by_loc.items():
                for _tm, _rt in _mpp_location_routes(
                        env_sudo, _tms, _lc).items():
                    loc_routes[(_lc, _tm)] = _rt
            for it in items:
                _pend = loc_pending.get(it['product_id'])
                if _pend and ((
                        _pend[1], _pend[0]) in loc_routes):
                    it['route'] = loc_routes[(_pend[1], _pend[0])]
                    it['route_label'] = _MPC_ROUTE_LABELS.get(
                        it['route'], 'Unknown')
        items.sort(key=lambda r: (r['code'] or '', r['name'] or ''))
        return {
            # TEMP-REV-MARKER: proves which revision staging runs
            # (remove after deploy verification).
            'rev': '5d0e831-fx2',
            'items': items,
            'count': len(items),
            'override_count': sum(
                1 for it in items if it['has_override']),
        }

    @api.model
    def reset_prices_to_usd(self, product_ids=False):
        """Copy the computed USD into corrected (multi-select reset).

        Manufactured/kit products take no corrected price and are
        reported as skipped (same guard as the single-row save).

        @param product_ids: product.product IDs to reset.
        @return: {'updated': int, 'skipped': [codes]}.
        """
        # No ensure_one: called model-style (empty recordset) from JS.
        env_sudo = _mpp_env_sudo(self)
        pids = []
        for _p in (product_ids or []):
            try:
                pids.append(int(_p))
            except (TypeError, ValueError):
                continue
        if not pids:
            raise UserError(_('No products selected.'))
        price_map, routes = self._mpc_price_map(env_sudo, pids)
        Mpp = env_sudo['matia.procurement.plan']
        updated = 0
        skipped = []
        Product = env_sudo['product.product']
        for pid in pids:
            route = routes.get(pid, 'unknown')
            pr = Product.browse(pid)
            pr_code = pr.default_code or pr.name or str(pid)
            if route in ('make', 'kit'):
                skipped.append(pr_code)
                continue
            pm = price_map.get(pid, {})
            eff = float(pm.get('effective_usd') or 0.0)
            if eff <= 0:
                # Nothing to copy (no purchase and no override):
                # writing a 0.0 row would only pollute the table.
                skipped.append(pr_code)
                continue
            pfactor = float(pm.get('price_factor') or 1.0) or 1.0
            try:
                # save_price_override expects the commercial
                # (per purchase UoM) input and stores it per
                # stock UoM; location=False keeps the stored one.
                Mpp.save_price_override(
                    pid, eff * pfactor, False)
                updated += 1
            except Exception as exc:
                _logger.warning(
                    'MPC reset skipped product %s: %s', pid, exc)
                skipped.append(pr_code)
        return {'updated': updated, 'skipped': skipped}

    @api.model
    def copy_std_to_corrected(self, product_ids=False):
        """Copy the location-side standard USD into corrected.

        The source side follows the row location (see
        _mpc_std_usd_map): US rows copy the US-company
        standard_price (already USD), TR rows copy the
        TR-company standard_price converted at the estimated
        last-change day rate. Manufactured/kit products take no corrected
        price; rows without a location or without a usable side
        value are reported as skipped (same guard as the
        single-row save).

        @param product_ids: product.product IDs to fill.
        @return: {'updated': int, 'skipped': [codes]}.
        """
        # No ensure_one: called model-style (empty recordset) from JS.
        env_sudo = _mpp_env_sudo(self)
        pids = []
        for _p in (product_ids or []):
            try:
                pids.append(int(_p))
            except (TypeError, ValueError):
                continue
        if not pids:
            raise UserError(_('No products selected.'))
        price_map, routes = self._mpc_price_map(env_sudo, pids)
        std_map = self._mpc_std_usd_map(env_sudo, pids)
        Mpp = env_sudo['matia.procurement.plan']
        Product = env_sudo['product.product']
        prod_uoms = {}
        prod_tmpl = {}
        for pr in Product.browse(pids).read(
                ['uom_id', 'uom_po_id', 'product_tmpl_id']):
            _su = pr.get('uom_id') or pr.get('uom_po_id')
            _pu = pr.get('uom_po_id') or _su
            prod_uoms[pr['id']] = (
                _su[0] if _su else False, _pu[0] if _pu else False)
            _pt = pr.get('product_tmpl_id')
            prod_tmpl[pr['id']] = _pt[0] if _pt else False
        # Location-scoped skip decision (same rule as the Type
        # column): a TR-made product bought in the US copies
        # fine there.
        loc_pending = {}
        for pid in pids:
            _lc = (price_map.get(pid, {}).get('location')
                   or '').lower()
            if _lc in ('tr', 'us') and prod_tmpl.get(pid):
                loc_pending[pid] = (prod_tmpl[pid], _lc)
        loc_routes = {}
        if loc_pending:
            by_loc = {}
            for _pid, (_tm, _lc) in loc_pending.items():
                by_loc.setdefault(_lc, []).append(_tm)
            tm_to_pid = {}
            for _pid, (_tm, _lc) in loc_pending.items():
                tm_to_pid.setdefault((_lc, _tm), []).append(_pid)
            for _lc, _tms in by_loc.items():
                for _tm, _rt in _mpp_location_routes(
                        env_sudo, _tms, _lc).items():
                    for _pid in tm_to_pid.get((_lc, _tm), []):
                        loc_routes[_pid] = _rt
        updated = 0
        skipped = []
        spf_cache = {}
        for pid in pids:
            route = loc_routes.get(
                pid, routes.get(pid, 'unknown'))
            pr = Product.browse(pid)
            pr_code = pr.default_code or pr.name or str(pid)
            if route in ('make', 'kit'):
                skipped.append(pr_code)
                continue
            loc = (price_map.get(pid, {}).get('location')
                   or '').lower()
            side = std_map.get(pid, {})
            if loc == 'us':
                std_usd = float(side.get('std_us_usd') or 0.0)
            elif loc == 'tr':
                std_usd = float(side.get('std_tr_usd') or 0.0)
            else:
                # No location: the Std cell shows the
                # placeholder, there is no side to copy.
                skipped.append(pr_code)
                continue
            if std_usd <= 0:
                # No usable side value (no standard price, no
                # US layer, or no USD rate): writing a 0.0 row
                # would only pollute the table.
                skipped.append(pr_code)
                continue
            _su, _pu = prod_uoms.get(pid, (False, False))
            spf_key = (_su, _pu)
            if spf_key not in spf_cache:
                spf_cache[spf_key] = _mpp_stock_per_po_factor(
                    env_sudo, _su, _pu) or 1.0
            pfactor = spf_cache[spf_key]
            try:
                # save_price_override expects the commercial
                # (per purchase UoM) input and stores it per
                # stock UoM. The row location is passed (not
                # False) so its guard classifies with the same
                # location-scoped route as the skip above.
                Mpp.save_price_override(
                    pid, std_usd * pfactor, loc)
                updated += 1
            except Exception as exc:
                _logger.warning(
                    'MPC std copy skipped product %s: %s', pid, exc)
                skipped.append(pr_code)
        return {'updated': updated, 'skipped': skipped}

    @api.model
    def import_price_overrides(self, rows=False):
        """Bulk upsert of manual prices/locations from a CSV import.

        Each row is {'code': str, 'name': str, 'corrected':
        float/str/False/None, 'location': str/False/None} ('name'
        optional; 'product_id' is accepted but ignored). The product
        is resolved by default_code only: numeric IDs differ between
        databases, so a staging export stays safe to import into
        prod. When the row carries a name and it does not match the
        database product name, the row is skipped with a warning.
        Empty corrected/location means "keep stored" (same False
        semantics as save_price_override); rows with both empty are
        skipped, not cleared. Manufactured/kit price rejections and
        invalid values are collected as per-row errors instead of
        aborting the batch.

        @param rows: list of row dicts (max 2000).
        @return: {'updated': int, 'skipped': [codes],
            'warnings': [messages], 'errors': [messages]}.
        """
        # No ensure_one: called model-style (empty recordset) from JS.
        env_sudo = _mpp_env_sudo(self)
        rows = list(rows or [])
        if not rows:
            raise UserError(_('No rows to import.'))
        if len(rows) > 2000:
            raise UserError(_('Too many rows (max 2000).'))
        Mpp = env_sudo['matia.procurement.plan']
        Product = env_sudo['product.product']
        updated = 0
        skipped = []
        warnings = []
        errors = []
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append('Row %d: not a mapping.' % (idx + 1))
                continue
            code = (row.get('code') or '').strip() \
                if isinstance(row.get('code'), str) else ''
            if not code:
                errors.append('Row %d: no product code.' % (idx + 1))
                continue
            prod = Product.search(
                [('default_code', '=', code)], limit=1)
            if not prod.exists():
                errors.append('Row %d: product not found (%s).' % (
                    idx + 1, code))
                continue
            row_name = (row.get('name') or '').strip() \
                if isinstance(row.get('name'), str) else ''
            db_name = (prod.name or '').strip()
            if row_name and row_name != db_name:
                warnings.append(
                    'Row %d [%s]: name mismatch, skipped '
                    '(file "%s" vs database "%s").' % (
                        idx + 1, code, row_name, db_name))
                continue
            label = prod.default_code or prod.name or str(prod.id)
            raw_corr = row.get('corrected', '')
            corr = False
            if raw_corr is not False and raw_corr is not None \
                    and str(raw_corr).strip() != '':
                try:
                    corr = float(str(raw_corr).strip().replace(',', '.'))
                except (TypeError, ValueError):
                    errors.append('Row %d [%s]: invalid price.' % (
                        idx + 1, label))
                    continue
                if corr < 0:
                    errors.append('Row %d [%s]: negative price.' % (
                        idx + 1, label))
                    continue
            raw_loc = row.get('location', '')
            loc = False
            if raw_loc is not False and raw_loc is not None \
                    and str(raw_loc).strip() != '':
                loc = str(raw_loc).strip().lower()
                if loc not in ('tr', 'us'):
                    errors.append('Row %d [%s]: invalid location.' % (
                        idx + 1, label))
                    continue
            if corr is False and loc is False:
                skipped.append(label)
                continue
            try:
                Mpp.save_price_override(prod.id, corr, loc)
                updated += 1
            except Exception as exc:
                _logger.warning(
                    'MPC import skipped product %s: %s', prod.id, exc)
                skipped.append(label)
        return {'updated': updated, 'skipped': skipped,
                'warnings': warnings, 'errors': errors[:50]}
