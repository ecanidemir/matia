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
    _mpp_env_sudo,
    _mpp_find_kit_boms,
    _mpp_kit_tmpl_ids,
    _mpp_norm_bom_qty,
    _mpp_price_overrides,
    _mpp_product_routes,
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
        last_buy = Mpp._mpp_last_buys(env_sudo, list(pids or []))
        usd = env_sudo['res.currency'].search(
            [('name', '=', 'USD')], limit=1)
        company = env_sudo['res.company'].browse(_MPP_TR_COMPANY_ID)
        routes = _mpp_product_routes(env_sudo, list(pids or []))
        overrides = _mpp_price_overrides(env_sudo, list(pids or []))
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
                    last_usd = cur_rec._convert(
                        price, usd, company, buy_date) \
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
        """Standard-price fallback in USD, per stock UoM.

        standard_price has no history table, and product write
        dates are unreliable (variant write_date always mirrors
        the last valuation layer; template write_date is stale),
        so the day the standard price last changed is estimated
        from stock valuation: the latest incoming
        (quantity > 0) stock.valuation.layer whose unit_cost
        matches standard_price within max(0.005, 1e-4 * value).
        That unit_cost is converted to USD with the TR-company
        USD rate of that day (base currency is TRY, so USD =
        TRY * rate). Products with no matching layer fall back
        to the latest overall TR USD rate (flagged).

        @param env_sudo: sudo environment.
        @param pids: product.product IDs.
        @return: {pid: {'std_usd': float (per stock UoM),
            'std_rate_date': str (month-year of the rate used),
            'std_rate_latest': bool (True when the fallback
            latest rate was used because no layer matched)}}.
        """
        out = {}
        pids = [p for p in (pids or []) if p]
        if not pids:
            return out
        Product = env_sudo['product.product']
        stds = {}
        for pr in Product.browse(pids).read(['standard_price']):
            try:
                stds[pr['id']] = float(
                    pr.get('standard_price') or 0.0)
            except (TypeError, ValueError):
                stds[pr['id']] = 0.0
        live = {pid: std for pid, std in stds.items() if std > 0}
        if live:
            layers = env_sudo['stock.valuation.layer'].search_read(
                [('product_id', 'in', list(live)),
                 ('quantity', '>', 0)],
                ['product_id', 'unit_cost', 'create_date'],
                order='product_id, create_date desc, id desc')
        else:
            layers = []
        match_date = {}
        for lay in layers:
            _lp = lay.get('product_id')
            pid = _lp[0] if _lp else False
            if not pid or pid in match_date or pid not in live:
                continue
            try:
                cost = float(lay.get('unit_cost') or 0.0)
            except (TypeError, ValueError):
                continue
            std = live[pid]
            if abs(cost - std) <= max(0.005, 1e-4 * abs(std)):
                _cd = lay.get('create_date')
                dt = fields.Datetime.from_string(_cd) \
                    if isinstance(_cd, str) else _cd
                if dt:
                    match_date[pid] = dt.date()
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
            std = stds.get(pid, 0.0)
            if std <= 0 or not rate_points:
                out[pid] = {'std_usd': 0.0, 'std_rate_date': '',
                            'std_rate_latest': False}
                continue
            tgt = match_date.get(pid)
            rate, rdate, latest = rate_points[0][1], \
                rate_points[0][0], True
            if tgt:
                for (rd, rt) in rate_points:
                    if rd <= tgt:
                        rate, rdate, latest = rt, rd, False
                        break
            out[pid] = {'std_usd': std * rate,
                        'std_rate_date': _mpc_month_year(rdate),
                        'std_rate_latest': latest}
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
            # Standard-price fallback: shown per the product's own
            # purchase UoM (the commercial unit save_price_override
            # converts back from), so the displayed value is
            # exactly what Copy Std stores.
            std = std_map.get(pid, {})
            std_usd = float(std.get('std_usd') or 0.0)
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
                'std_rate_date': std.get('std_rate_date') or '',
                'std_rate_latest': bool(
                    std.get('std_rate_latest')),
                'corrected': corr,
                'location': pm.get('location') or '',
                'effective_usd': eff,
                'has_override': bool(
                    corr > 0 or pm.get('location')),
            })
        items.sort(key=lambda r: (r['code'] or '', r['name'] or ''))
        return {
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
        """Copy the standard-price USD into corrected (multi-select).

        Fills corrected from standard_price (converted to USD at
        the rate of the day the standard price last changed, see
        _mpc_std_usd_map) for products with no usable last-buy
        price. Manufactured/kit products take no corrected price
        and are reported as skipped (same guard as the
        single-row save); products without a standard price are
        skipped as well.

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
        _price_map, routes = self._mpc_price_map(env_sudo, pids)
        std_map = self._mpc_std_usd_map(env_sudo, pids)
        Mpp = env_sudo['matia.procurement.plan']
        Product = env_sudo['product.product']
        prod_uoms = {}
        for pr in Product.browse(pids).read(['uom_id', 'uom_po_id']):
            _su = pr.get('uom_id') or pr.get('uom_po_id')
            _pu = pr.get('uom_po_id') or _su
            prod_uoms[pr['id']] = (
                _su[0] if _su else False, _pu[0] if _pu else False)
        updated = 0
        skipped = []
        for pid in pids:
            route = routes.get(pid, 'unknown')
            pr = Product.browse(pid)
            pr_code = pr.default_code or pr.name or str(pid)
            if route in ('make', 'kit'):
                skipped.append(pr_code)
                continue
            std_usd = float(
                std_map.get(pid, {}).get('std_usd') or 0.0)
            if std_usd <= 0:
                # No standard price (or no USD rate): writing a
                # 0.0 row would only pollute the table.
                skipped.append(pr_code)
                continue
            _su, _pu = prod_uoms.get(pid, (False, False))
            pfactor = _mpp_stock_per_po_factor(
                env_sudo, _su, _pu) or 1.0
            try:
                # save_price_override expects the commercial
                # (per purchase UoM) input and stores it per
                # stock UoM; location=False keeps the stored one.
                Mpp.save_price_override(
                    pid, std_usd * pfactor, False)
                updated += 1
            except Exception as exc:
                _logger.warning(
                    'MPC std copy skipped product %s: %s', pid, exc)
                skipped.append(pr_code)
        return {'updated': updated, 'skipped': skipped}
