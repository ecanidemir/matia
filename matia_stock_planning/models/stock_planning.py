# -*- coding: utf-8 -*-
import math
from datetime import datetime
from odoo import models, api, _
from odoo.exceptions import UserError
from .matia_procurement_plan import (
    _MPP_MAX_LEVEL,
    _mpp_find_kit_boms,
    _mpp_search_kit_forest,
)

# Common UoM name translations (Odoo stores them in the language of the DB)
_UOM_NAME_MAP = {
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
}

# Company roots are independent (see docs/discovery.md): TR = 1, US = 2.
_MSP_TR_COMPANY_ID = 1
_MSP_US_COMPANY_ID = 2

# Float-noise guard for display-only requirement math: e.g. 20 * 0.3 can
# evaluate to 6.000000000001, which would push math.ceil one unit up and
# wrongly show NEED. Subtracting eps keeps exact integers exact while
# leaving genuine fractions untouched.
_MSP_FLOAT_EPS = 1e-9


def _msp_company_stock(env_sudo, product_ids, loc_ids):
    """Single read_group for one company's stock locations.

    @return: (stock, reserved) dicts keyed by product id.
    """
    stock, reserved = {}, {}
    if product_ids and loc_ids:
        for sq in env_sudo['stock.quant'].read_group(
            [
                ('product_id', 'in', list(product_ids)),
                ('location_id', 'in', list(loc_ids))
            ],
            ['product_id', 'quantity', 'reserved_quantity'],
            ['product_id']
        ):
            pid = sq['product_id'][0]
            stock[pid] = float(sq.get('quantity') or 0.0)
            reserved[pid] = float(sq.get('reserved_quantity') or 0.0)
    return stock, reserved


def _msp_clamped_avail(tr_stock, tr_res, us_stock, us_res):
    """Combined unreserved avail with per-company clamp.

    Same policy as the Production page (_mpp_stock_split consumers):
    a negative avail in one company never eats the other company's
    stock (known 3745 negative quants must not inflate needs).
    """
    return (max(0.0, float(tr_stock or 0.0) - float(tr_res or 0.0))
            + max(0.0, float(us_stock or 0.0) - float(us_res or 0.0)))

class MatiaStockPlanning(models.AbstractModel):
    _name = 'matia.stock.planning'
    _description = 'Matia TekRMD Device Capacity and Stock Planning'

    @api.model
    def search_tree(self, query):
        """Full-forest code/name search over the 4 kit BOMs (Capacity page).

        Same match shape as the Production Plan search, but plan-independent:
        walks ALL kit tops so parts buried inside collapsed sub-BOMs are
        found with a single cheap RPC (cap 100, depth 10).

        @param query: raw search text (min 2 chars).
        @return: {'matches': [...], 'total': int}.
        """
        all_company_ids = self.env['res.company'].with_context(
            active_test=False).sudo().search([]).ids
        env_sudo = self.with_context(
            allowed_company_ids=all_company_ids,
            active_test=False
        ).sudo().env
        return _mpp_search_kit_forest(env_sudo, query)

    @api.model
    def get_capacity_planning_data(self, include_tr=True, include_usa=True, dynamic_targets=None):
        """
        Calculates available stock and producible device capacity across TR and USA locations
        for TekRMD Common Parts v2, Outdoor Parts, and Seat Parts BOMs.
        """
        if not include_tr and not include_usa:
            raise UserError(_("At least one location (TR or USA) must be selected!"))

        if dynamic_targets is None:
            dynamic_targets = []
        # Accept at most 3 dynamic targets
        dynamic_targets = [int(t) for t in dynamic_targets if str(t).isdigit() and int(t) > 0][:3]

        # 0. Multi-company context: include ALL companies (even inactive/archived ones)
        # Odoo 15 pattern: use with_context().sudo().env — Environment has no .sudo()
        all_company_ids = self.env['res.company'].with_context(active_test=False).sudo().search([]).ids
        env_sudo = self.with_context(
            allowed_company_ids=all_company_ids,
            active_test=False
        ).sudo().env

        # 1. Identify locations
        all_locs = env_sudo['stock.location'].search([('usage', '=', 'internal')])
        
        tr_stock_locs = []
        usa_stock_locs = []
        tr_ncr_locs = []
        usa_ncr_locs = []

        for loc in all_locs:
            cname = loc.complete_name or ''
            cid = loc.company_id.id if loc.company_id else False
            is_ncr = 'NCR' in cname

            if 'WHTR' in cname or cid == _MSP_TR_COMPANY_ID:
                if is_ncr:
                    tr_ncr_locs.append(loc.id)
                elif cname.startswith('WHTR/Stock'):
                    tr_stock_locs.append(loc.id)
            elif 'WHUS' in cname or cid == _MSP_US_COMPANY_ID:
                if is_ncr:
                    usa_ncr_locs.append(loc.id)
                elif cname.startswith('WHUS/Stock'):
                    usa_stock_locs.append(loc.id)

        selected_ncr_ids = []

        if include_tr:
            selected_ncr_ids.extend(tr_ncr_locs)
        if include_usa:
            selected_ncr_ids.extend(usa_ncr_locs)

        # 2. Define BOM configurations
        bom_configs = [
            {
                'key': 'base',
                'title': 'TekRMD Common Parts v2 (Base)',
                'badge': 'Base',
                'color_class': 'badge-primary',
                'preferred_id': 1766,
                'names': ['TekRMD Common Parts v2', 'TekRMD Common Parts'],
            },
            {
                'key': 'outdoor',
                'title': 'TekRMD Outdoor Parts (Outdoor)',
                'badge': 'Outdoor',
                'color_class': 'badge-success',
                'preferred_id': 1737,
                'names': ['TekRMD Outdoor Parts'],
            },
            {
                'key': 'seat',
                'title': 'TekRMD Seat Parts (Seat)',
                'badge': 'Seat',
                'color_class': 'badge-warning',
                'preferred_id': 1738,
                'names': ['TekRMD Seat Parts'],
            },
            {
                'key': 'screws',
                'title': 'TekRMD Common Screws',
                'badge': 'Screws',
                'color_class': 'badge-secondary',
                'preferred_id': 1736,
                'names': ['TekRMD Common Screws'],
            },
        ]

        all_product_ids = set()
        groups_data = []

        for cfg in bom_configs:
            bom = False
            # 1. Try preferred direct ID if exists
            pref_id = cfg.get('preferred_id')
            if pref_id:
                pref_bom = env_sudo['mrp.bom'].browse(pref_id)
                if pref_bom.exists() and pref_bom.active:
                    bom = pref_bom

            # 2. Sequential priority search by exact product template name
            if not bom:
                for n in cfg['names']:
                    bom = env_sudo['mrp.bom'].search([
                        ('product_tmpl_id.name', '=', n)
                    ], limit=1)
                    if bom:
                        break

            # 3. Fallback search with ilike
            if not bom:
                for n in cfg['names']:
                    bom = env_sudo['mrp.bom'].search([
                        '|',
                        ('product_tmpl_id.name', 'ilike', n),
                        ('code', 'ilike', n)
                    ], limit=1)
                    if bom:
                        break

            lines_list = []
            if bom:
                # Batch has_bom lookup: one query instead of one per line.
                # Same semantics as bool(p.product_tmpl_id.bom_ids) under
                # this env (active_test=False, no extra domain).
                bom_lines = bom.bom_line_ids
                tmpl_ids = list({l.product_id.product_tmpl_id.id for l in bom_lines})
                tmpl_with_bom = set()
                if tmpl_ids:
                    for br in env_sudo['mrp.bom'].search_read(
                        [('product_tmpl_id', 'in', tmpl_ids)],
                        ['product_tmpl_id']
                    ):
                        t = br.get('product_tmpl_id')
                        if t:
                            tmpl_with_bom.add(t[0])
                for line in bom_lines:
                    p = line.product_id
                    all_product_ids.add(p.id)
                    lines_list.append({
                        'product_id': p.id,
                        'product_code': p.default_code or '',
                        'product_name': p.name or '',
                        'display_name': p.display_name or p.name,
                        'bom_qty': line.product_qty or 1.0,
                        'uom_name': _UOM_NAME_MAP.get(line.product_uom_id.name or '', line.product_uom_id.name or 'Units'),
                        'has_bom': p.product_tmpl_id.id in tmpl_with_bom,
                    })

            groups_data.append({
                'key': cfg['key'],
                'title': cfg['title'],
                'badge': cfg['badge'],
                'color_class': cfg['color_class'],
                'bom_id': bom.id if bom else False,
                'bom_name': bom.display_name if bom else cfg['title'],
                'items': lines_list,
            })

        # 3. Read stock and NCR quantities per company, then clamp each
        # company separately (same policy as the Production page).
        sel_tr = tr_stock_locs if include_tr else []
        sel_us = usa_stock_locs if include_usa else []
        product_stock = {pid: 0.0 for pid in all_product_ids}
        product_reserved = {pid: 0.0 for pid in all_product_ids}
        tr_stock, tr_reserved = _msp_company_stock(
            env_sudo, all_product_ids, sel_tr)
        us_stock, us_reserved = _msp_company_stock(
            env_sudo, all_product_ids, sel_us)
        for _pid in all_product_ids:
            product_stock[_pid] = (tr_stock.get(_pid, 0.0)
                                   + us_stock.get(_pid, 0.0))
            product_reserved[_pid] = (tr_reserved.get(_pid, 0.0)
                                      + us_reserved.get(_pid, 0.0))
        product_ncr = {pid: 0.0 for pid in all_product_ids}

        if selected_ncr_ids:
            ncr_quants = env_sudo['stock.quant'].read_group(
                [
                    ('product_id', 'in', list(all_product_ids)),
                    ('location_id', 'in', selected_ncr_ids)
                ],
                ['product_id', 'quantity'],
                ['product_id']
            )
            for nq in ncr_quants:
                pid = nq['product_id'][0]
                product_ncr[pid] = float(nq.get('quantity') or 0.0)

        # 4. Compute items and KPIs
        overall_min_devices = 999999
        overall_bottleneck_product = "-"
        
        for grp in groups_data:
            grp_min_devices = 999999 if grp['items'] else 0
            grp_bottleneck_product = "-"

            for item in grp['items']:
                pid = item['product_id']
                b_qty = item['bom_qty']
                s_qty = product_stock.get(pid, 0.0)
                r_qty = product_reserved.get(pid, 0.0)
                n_qty = product_ncr.get(pid, 0.0)

                # Available stock, clamped per company (Production-page
                # policy): a negative avail in one company never eats the
                # other company's stock or inflates the need.
                avail_qty = _msp_clamped_avail(
                    tr_stock.get(pid, 0.0), tr_reserved.get(pid, 0.0),
                    us_stock.get(pid, 0.0), us_reserved.get(pid, 0.0))

                # Maximum devices producible (based on available stock)
                if b_qty > 0:
                    max_dev = math.floor(max(0.0, avail_qty) / b_qty)
                else:
                    max_dev = 0

                # Requirement for 20 devices: (20 * bom_qty) - available_stock
                needed_20 = (20.0 * b_qty) - avail_qty
                if needed_20 <= 0:
                    req_20_status = 'OK'
                    req_20_val = 0
                else:
                    req_20_status = 'NEED'
                    req_20_val = int(math.ceil(needed_20 - _MSP_FLOAT_EPS))

                # Dynamic columns
                dynamic_needs = {}
                for target in dynamic_targets:
                    needed_target = (float(target) * b_qty) - avail_qty
                    if needed_target <= 0:
                        dynamic_needs[str(target)] = {
                            'status': 'OK',
                            'val': 0,
                            'text': 'OK'
                        }
                    else:
                        c_val = int(math.ceil(needed_target - _MSP_FLOAT_EPS))
                        dynamic_needs[str(target)] = {
                            'status': 'NEED',
                            'val': c_val,
                            'text': str(c_val)
                        }

                s_clean = float(s_qty or 0.0)
                r_clean = float(r_qty or 0.0)
                n_clean = float(n_qty or 0.0)
                s_disp = int(s_clean) if s_clean.is_integer() else round(s_clean, 2)
                r_disp = int(r_clean) if r_clean.is_integer() else round(r_clean, 2)
                avail_clean = max(0.0, avail_qty)
                avail_disp = int(avail_clean) if avail_clean.is_integer() else round(avail_clean, 2)

                item['stock_qty'] = s_disp
                item['total_stock_qty'] = s_disp
                item['reserved_qty'] = r_disp
                item['avail_qty'] = avail_disp
                item['ncr_qty'] = int(n_clean) if n_clean.is_integer() else round(n_clean, 2)
                item['max_devices'] = max_dev
                item['req_20_status'] = req_20_status
                item['req_20_val'] = req_20_val
                item['req_20_text'] = 'OK' if req_20_status == 'OK' else str(req_20_val)
                item['dynamic_needs'] = dynamic_needs

                # Group bottleneck with available stock amount
                if max_dev < grp_min_devices:
                    grp_min_devices = max_dev
                    grp_bottleneck_product = f"{item['display_name']} ({avail_disp} {item['uom_name']})"

                # Overall bottleneck with available stock amount
                if max_dev < overall_min_devices:
                    overall_min_devices = max_dev
                    overall_bottleneck_product = f"{item['display_name']} ({avail_disp} {item['uom_name']})"

            grp['min_devices'] = grp_min_devices if grp_min_devices != 999999 else 0
            grp['bottleneck_product'] = grp_bottleneck_product

        if overall_min_devices == 999999:
            overall_min_devices = 0

        return {
            'groups': groups_data,
            'dynamic_targets': dynamic_targets,
            'include_tr': include_tr,
            'include_usa': include_usa,
            'summary': {
                'overall_min_devices': overall_min_devices,
                'overall_bottleneck': overall_bottleneck_product,
                'total_products': len(all_product_ids),
                'tr_locations_count': len(tr_stock_locs),
                'usa_locations_count': len(usa_stock_locs),
            }
        }

    @api.model
    def get_sub_bom_details(self, product_id, parent_bom_qty=1.0, dynamic_targets=None, include_tr=True, include_usa=True,
                            parent_req_20=None, parent_dynamic_needs=None):
        """
        Fetches the Bill of Materials (BOM) components and their current stock levels
        for a specific sub-assembly product, scaled to the main device requirements.

        @param product_id: parent (sub-assembly) product id being expanded.
        @param parent_bom_qty: qty of this parent used per one device (scales display bom_qty).
        @param parent_req_20: NET shortage of the parent for the 20-device target,
            in parent units (0 means parent stock covers the target). When given,
            each child need is computed as dependent demand:
            ``max(0, parent_need * sub_qty_per_parent - avail_child)``.
            When None (old clients), falls back to the legacy gross formula.
        @param parent_dynamic_needs: dict {str(target): net parent need} with the same
            dependent-demand semantics per dynamic target column.
        @return: dict with has_bom, items (each with stock/need fields), min_producible.
        """
        # Multi-company context: include ALL companies (even inactive/archived ones)
        # Odoo 15 pattern: use with_context().sudo().env — Environment has no .sudo()
        all_company_ids = self.env['res.company'].with_context(active_test=False).sudo().search([]).ids
        env_sudo = self.with_context(
            allowed_company_ids=all_company_ids,
            active_test=False
        ).sudo().env

        product = env_sudo['product.product'].browse(product_id)
        if not product.exists():
            return {'has_bom': False, 'message': 'Product not found'}

        if dynamic_targets is None:
            dynamic_targets = []
        dynamic_targets = [int(t) for t in dynamic_targets if str(t).isdigit() and int(t) > 0][:3]
        parent_bom_qty = float(parent_bom_qty or 1.0)

        # Parent NET shortages (dependent demand basis). None = legacy gross mode.
        if parent_req_20 is None:
            _parent_need_20 = None
        else:
            try:
                _parent_need_20 = max(0.0, float(parent_req_20 or 0.0))
            except (TypeError, ValueError):
                _parent_need_20 = None
        _parent_dyn = {}
        if isinstance(parent_dynamic_needs, dict):
            for _k, _v in parent_dynamic_needs.items():
                try:
                    _parent_dyn[str(_k)] = max(0.0, float(_v or 0.0))
                except (TypeError, ValueError):
                    continue

        # Find BOM for this product: variant-specific first, then the
        # generic template BOM (same deterministic order as the
        # Production page). A single OR-search leaves the winner
        # undefined when both exist.
        bom = env_sudo['mrp.bom'].search([
            ('product_id', '=', product.id),
        ], limit=1)

        if not bom:
            bom = env_sudo['mrp.bom'].search([
                ('product_id', '=', False),
                ('product_tmpl_id', '=', product.product_tmpl_id.id)
            ], limit=1)

        if not bom:
            # Fallback search by template
            bom = env_sudo['mrp.bom'].search([
                ('product_tmpl_id', '=', product.product_tmpl_id.id)
            ], limit=1)

        if not bom:
            return {
                'has_bom': False,
                'product_name': product.display_name,
                'message': 'No BOM defined for this product'
            }

        # 1. Identify locations across all companies
        all_locs = env_sudo['stock.location'].search([('usage', '=', 'internal')])
        selected_ncr_ids = []
        sel_tr_ids = []
        sel_us_ids = []

        for loc in all_locs:
            cname = loc.complete_name or ''
            cid = loc.company_id.id if loc.company_id else False
            is_ncr = 'NCR' in cname

            if 'WHTR' in cname or cid == _MSP_TR_COMPANY_ID:
                if is_ncr and include_tr:
                    selected_ncr_ids.append(loc.id)
                elif cname.startswith('WHTR/Stock') and include_tr:
                    sel_tr_ids.append(loc.id)
            elif 'WHUS' in cname or cid == _MSP_US_COMPANY_ID:
                if is_ncr and include_usa:
                    selected_ncr_ids.append(loc.id)
                elif cname.startswith('WHUS/Stock') and include_usa:
                    sel_us_ids.append(loc.id)

        # 2. Extract lines (has_bom batched: one query, not one per line)
        lines_list = []
        sub_product_ids = set()

        bom_lines = bom.bom_line_ids
        tmpl_ids = list({l.product_id.product_tmpl_id.id for l in bom_lines})
        tmpl_with_bom = set()
        if tmpl_ids:
            for br in env_sudo['mrp.bom'].search_read(
                [('product_tmpl_id', 'in', tmpl_ids)],
                ['product_tmpl_id']
            ):
                t = br.get('product_tmpl_id')
                if t:
                    tmpl_with_bom.add(t[0])

        for line in bom_lines:
            p = line.product_id
            sub_product_ids.add(p.id)
            sub_qty = float(line.product_qty or 1.0)
            effective_qty = sub_qty * parent_bom_qty
            eff_clean = int(effective_qty) if effective_qty.is_integer() else round(effective_qty, 3)

            lines_list.append({
                'product_id': p.id,
                'product_code': p.default_code or '',
                'product_name': p.name or '',
                'display_name': p.display_name or p.name,
                'sub_bom_qty': sub_qty,
                'parent_bom_qty': parent_bom_qty,
                'bom_qty': eff_clean,
                'uom_name': _UOM_NAME_MAP.get(line.product_uom_id.name or '', line.product_uom_id.name or 'Units'),
                'has_bom': p.product_tmpl_id.id in tmpl_with_bom,
            })

        # 3. Read stock per company, then clamp each company separately
        # (same policy as the top-level tree and the Production page).
        product_stock = {pid: 0.0 for pid in sub_product_ids}
        product_reserved = {pid: 0.0 for pid in sub_product_ids}
        product_ncr = {pid: 0.0 for pid in sub_product_ids}

        sub_tr_stock, sub_tr_res = _msp_company_stock(
            env_sudo, sub_product_ids, sel_tr_ids)
        sub_us_stock, sub_us_res = _msp_company_stock(
            env_sudo, sub_product_ids, sel_us_ids)
        for _pid in sub_product_ids:
            product_stock[_pid] = (sub_tr_stock.get(_pid, 0.0)
                                   + sub_us_stock.get(_pid, 0.0))
            product_reserved[_pid] = (sub_tr_res.get(_pid, 0.0)
                                      + sub_us_res.get(_pid, 0.0))

            if selected_ncr_ids:
                ncr_quants = env_sudo['stock.quant'].read_group(
                    [
                        ('product_id', 'in', list(sub_product_ids)),
                        ('location_id', 'in', selected_ncr_ids)
                    ],
                    ['product_id', 'quantity'],
                    ['product_id']
                )
                for nq in ncr_quants:
                    pid = nq['product_id'][0]
                    product_ncr[pid] = float(nq.get('quantity') or 0.0)

        # 4. Attach stock and producible device capacity
        min_producible = 999999
        bottleneck_product = "-"

        for item in lines_list:
            pid = item['product_id']
            b_qty = float(item['bom_qty']) # Effective qty per 1 device
            sub_qty = float(item.get('sub_bom_qty') or 0.0)
            s_qty = product_stock.get(pid, 0.0)
            r_qty = product_reserved.get(pid, 0.0)
            n_qty = product_ncr.get(pid, 0.0)

            avail_qty = _msp_clamped_avail(
                sub_tr_stock.get(pid, 0.0), sub_tr_res.get(pid, 0.0),
                sub_us_stock.get(pid, 0.0), sub_us_res.get(pid, 0.0))

            if b_qty > 0:
                max_dev = math.floor(max(0.0, avail_qty) / b_qty)
            else:
                max_dev = 0

            # Requirement for 20 devices. With parent net shortage known, the
            # child need is dependent demand: parent_need * sub_qty - avail.
            # Otherwise (legacy) fall back to gross: (20 * bom_qty) - avail.
            # NOTE: dependent branch clamps avail at 0 — with over-reserved
            # stock (avail < 0) and parent_need == 0 the child must stay OK.
            if _parent_need_20 is not None:
                needed_20 = (_parent_need_20 * sub_qty) - max(0.0, avail_qty)
            else:
                needed_20 = (20.0 * b_qty) - avail_qty
            if needed_20 <= 0:
                req_20_status = 'OK'
                req_20_val = 0
            else:
                req_20_status = 'NEED'
                req_20_val = int(math.ceil(needed_20 - _MSP_FLOAT_EPS))

            # Dynamic columns (same dependent-demand rule per target)
            dynamic_needs = {}
            for target in dynamic_targets:
                tkey = str(target)
                if tkey in _parent_dyn:
                    needed_target = (_parent_dyn[tkey] * sub_qty) - max(0.0, avail_qty)
                else:
                    needed_target = (float(target) * b_qty) - avail_qty
                if needed_target <= 0:
                    dynamic_needs[str(target)] = {
                        'status': 'OK',
                        'val': 0,
                        'text': 'OK'
                    }
                else:
                    c_val = int(math.ceil(needed_target - _MSP_FLOAT_EPS))
                    dynamic_needs[str(target)] = {
                        'status': 'NEED',
                        'val': c_val,
                        'text': str(c_val)
                    }

            s_clean = float(s_qty or 0.0)
            r_clean = float(r_qty or 0.0)
            n_clean = float(n_qty or 0.0)
            s_disp = int(s_clean) if s_clean.is_integer() else round(s_clean, 2)
            r_disp = int(r_clean) if r_clean.is_integer() else round(r_clean, 2)
            avail_clean = max(0.0, avail_qty)
            avail_disp = int(avail_clean) if avail_clean.is_integer() else round(avail_clean, 2)

            item['stock_qty'] = s_disp
            item['total_stock_qty'] = s_disp
            item['reserved_qty'] = r_disp
            item['avail_qty'] = avail_disp
            item['ncr_qty'] = int(n_clean) if n_clean.is_integer() else round(n_clean, 2)
            item['max_devices'] = max_dev
            item['req_20_status'] = req_20_status
            item['req_20_val'] = req_20_val
            item['req_20_text'] = 'OK' if req_20_status == 'OK' else str(req_20_val)
            item['dynamic_needs'] = dynamic_needs

            if max_dev < min_producible:
                min_producible = max_dev
                bottleneck_product = f"{item['display_name']} ({avail_disp} {item['uom_name']})"

        if min_producible == 999999:
            min_producible = 0

        return {
            'has_bom': True,
            'bom_id': bom.id,
            'bom_name': bom.display_name,
            'product_id': product.id,
            'product_name': product.display_name,
            'parent_bom_qty': parent_bom_qty,
            'items': lines_list,
            'min_producible': min_producible,
            'bottleneck_product': bottleneck_product,
            'total_items': len(lines_list),
        }

    @api.model
    def get_count_sheet(self, company):
        """Printable stock-count lists for one company (Count List pages).

        Four scope lists, each showing only products with stock
        (quantity > 0):
        - tekrmd: the 4 kit BOMs exploded to the lowest level (variant
          BOM wins, depth + cycle guards mirror the price-overview
          walk), kept only in that company's Stock locations. Rows
          carry Main/Sub Part type and sort Main first, then location,
          code, name.
        - other: Stock locations, products NOT in the 4 BOMs.
        - ncr: that company's NCR locations, BOM-independent.
        - spare: that company's Spare locations, BOM-independent
          (matched by name, so it works both under Stock/ and as a
          sibling after the manual move; spare never joins the stock
          scope to avoid double counting).

        One row per product: code, name, stock location names (a
        location is listed once even with several serial/lot quants),
        total quantity with UoM and comma-separated lot/serial names.
        Labels are fixed per company (TR page Turkish, US page
        English), independent of the user's language.

        @param company: 'tr' or 'us'.
        @return: {'company', 'lang', 'title', 'subtitle', 'generated',
            'print_label', 'excel_label', 'empty_label', 'file_base',
            'scopes', 'lists'} plus backwards-compatible top-level
            'headers'/'rows'/'count' of the tekrmd list. Each list
            carries 'key', 'title', 'headers', 'show_type', 'rows',
            'count'; each row carries 'no', 'code', 'name',
            'type_label' (tekrmd only), 'locs', 'qty', 'uom',
            'qty_text', 'lots'.
        """
        company = (company or '').strip().lower()
        if company not in ('tr', 'us'):
            raise UserError(_("Count sheet company must be 'tr' or 'us'."))
        is_tr = company == 'tr'
        if is_tr:
            labels = {
                'lang': 'tr',
                'title': 'TR Stok Sayım Listesi',
                'print_label': 'Yazdır',
                'excel_label': "Excel'e Aktar",
                'empty_label': 'Kayıt yok',
                'file_base': 'TekRMD_TR_Sayim_Listesi',
                'scope_titles': {
                    'tekrmd': 'Stok - TekRMD (4 BOM)',
                    'other': 'Stok - Diğer Parçalar',
                    'ncr': 'NCR',
                    'spare': 'Spare',
                },
                'tekrmd_headers': ['Kod', 'Ürün Adı', 'Tür',
                                   'Depo / Lokasyon', 'Miktar',
                                   'Lot/Seri'],
                'plain_headers': ['Kod', 'Ürün Adı', 'Depo / Lokasyon',
                                  'Miktar', 'Lot/Seri'],
            }
        else:
            labels = {
                'lang': 'en',
                'title': 'US Stock Count List',
                'print_label': 'Print',
                'excel_label': 'Export Excel',
                'empty_label': 'No records',
                'file_base': 'TekRMD_US_Count_List',
                'scope_titles': {
                    'tekrmd': 'Stock - TekRMD (4 BOMs)',
                    'other': 'Stock - Other Parts',
                    'ncr': 'NCR',
                    'spare': 'Spare',
                },
                'tekrmd_headers': ['Code', 'Product Name', 'Type',
                                   'Warehouse Location', 'Quantity',
                                   'Lot/Serial'],
                'plain_headers': ['Code', 'Product Name',
                                   'Warehouse Location', 'Quantity',
                                   'Lot/Serial'],
            }

        all_company_ids = self.env['res.company'].with_context(
            active_test=False).sudo().search([]).ids
        env_sudo = self.with_context(
            allowed_company_ids=all_company_ids,
            active_test=False
        ).sudo().env

        # 1. Company locations split into stock / NCR / spare scopes.
        # Internal + Subcontracting locations stay out. 'Spare' is
        # matched by name so it works both under Stock/ (before the
        # manual move) and as a sibling (after); spare never joins the
        # stock scope to avoid double counting.
        mark = 'WHTR' if is_tr else 'WHUS'
        own_company = _MSP_TR_COMPANY_ID if is_tr else _MSP_US_COMPANY_ID
        prefix = mark + '/Stock'
        stock_ids, ncr_ids, spare_ids = [], [], []
        for loc in env_sudo['stock.location'].search(
                [('usage', '=', 'internal')]):
            cname = loc.complete_name or ''
            cid = loc.company_id.id if loc.company_id else False
            if mark not in cname and cid != own_company:
                continue
            if 'NCR' in cname:
                ncr_ids.append(loc.id)
            elif 'Spare' in cname:
                spare_ids.append(loc.id)
            elif 'Subcontract' in cname:
                continue
            elif cname.startswith(prefix):
                stock_ids.append(loc.id)

        generated = datetime.now().strftime('%Y-%m-%d %H:%M')

        def _blank_lists():
            """Four empty scope lists (same shape as the result)."""
            out = []
            for key in ('tekrmd', 'other', 'ncr', 'spare'):
                show_type = key == 'tekrmd'
                out.append({
                    'key': key,
                    'title': labels['scope_titles'][key],
                    'headers': list(labels['tekrmd_headers'])
                    if show_type else list(labels['plain_headers']),
                    'show_type': show_type,
                    'rows': [],
                    'count': 0,
                })
            return out

        def _shell(lists):
            """Wrap scope lists in the page-level result dict."""
            scopes = [{'key': lst['key'], 'label': lst['title'],
                       'count': lst['count']} for lst in lists]
            tekrmd = lists[0]
            result = dict(labels)
            result.update({
                'company': company,
                'subtitle': generated,
                'generated': generated,
                'scopes': scopes,
                'lists': lists,
                # Backwards-compatible top-level tekrmd list.
                'headers': tekrmd['headers'],
                'rows': tekrmd['rows'],
                'count': tekrmd['count'],
            })
            return result

        if not (stock_ids or ncr_ids or spare_ids):
            return _shell(_blank_lists())

        # 2. Explode the 4 kit BOMs to the lowest level.
        kits = _mpp_find_kit_boms(env_sudo)
        if not kits:
            raise UserError(_('No kit BOM found.'))
        Product = env_sudo['product.product']
        Bom = env_sudo['mrp.bom']
        # Variant BOMs cache by product (a template's variants may each
        # carry their own BOM); template BOMs cache by template.
        variant_bom_cache = {}
        tmpl_bom_cache = {}
        seen = set()
        pids = set()
        # Shallowest explosion level per product (top-level kit lines
        # are level 0 -> Main Part, deeper levels -> Sub Part).
        pid_level = {}
        stack = []
        for kit in kits:
            for bl in kit['bom'].bom_line_ids:
                stack.append((bl.product_id.id, 0, ()))
        guard = 0
        while stack:
            guard += 1
            if guard > 60000:
                raise UserError(
                    _('Tree too deep/wide, explosion limited.'))
            pid, level, path = stack.pop()
            if pid in path or level > _MPP_MAX_LEVEL:
                continue
            pids.add(pid)
            if pid not in pid_level or level < pid_level[pid]:
                pid_level[pid] = level
            if pid in seen:
                continue
            seen.add(pid)
            prod = Product.browse(pid)
            if not prod.exists():
                continue
            tmpl_id = prod.product_tmpl_id.id
            if pid in variant_bom_cache:
                bom = variant_bom_cache[pid]
            else:
                bom = Bom.search([('product_id', '=', pid)], limit=1)
                if bom:
                    variant_bom_cache[pid] = bom
                else:
                    if tmpl_id not in tmpl_bom_cache:
                        tmpl_bom_cache[tmpl_id] = Bom.search(
                            [('product_tmpl_id', '=', tmpl_id)], limit=1)
                    bom = tmpl_bom_cache[tmpl_id]
            if bom:
                for bl in bom.bom_line_ids:
                    stack.append(
                        (bl.product_id.id, level + 1, path + (pid,)))
        if not pids:
            return _shell(_blank_lists())

        # 3. Per-(product, location, lot) stock over all three scopes
        # in one read_group (lazy=False: with several groupbys the
        # default lazy mode drops the trailing keys). Only quantity
        # > 0 groups are kept, so every list shows stocked parts only.
        scope_of_loc = {}
        for lid in stock_ids:
            scope_of_loc[lid] = 'stock'
        for lid in ncr_ids:
            scope_of_loc[lid] = 'ncr'
        for lid in spare_ids:
            scope_of_loc[lid] = 'spare'
        # pid -> {lid: qty} per scope list.
        buckets = {'tekrmd': {}, 'other': {}, 'ncr': {}, 'spare': {}}
        # (scope list, pid) -> distinct lot/serial names.
        lots = {}
        for rg in env_sudo['stock.quant'].read_group(
                [('location_id', 'in', list(scope_of_loc))],
                ['product_id', 'location_id', 'lot_id', 'quantity'],
                ['product_id', 'location_id', 'lot_id'], lazy=False):
            _p = rg.get('product_id')
            _l = rg.get('location_id')
            if not _p or not _l:
                continue
            qty = float(rg.get('quantity') or 0.0)
            if qty <= 0.0:
                continue
            loc_scope = scope_of_loc.get(_l[0])
            if not loc_scope:
                continue
            if loc_scope == 'stock':
                key = 'tekrmd' if _p[0] in pids else 'other'
            else:
                key = loc_scope
            per_loc = buckets[key].setdefault(_p[0], {})
            per_loc[_l[0]] = per_loc.get(_l[0], 0.0) + qty
            lot = rg.get('lot_id')
            if lot:
                lots.setdefault((key, _p[0]), set()).add(lot[1])

        # 4. Bulk identity + location names, then one row per product
        # per scope list.
        used_loc_ids = {lid for bucket in buckets.values()
                        for loc_qty in bucket.values()
                        for lid in loc_qty}
        loc_names = {loc.id: (loc.complete_name or loc.name or '')
                     for loc in env_sudo['stock.location'].browse(
                         list(used_loc_ids))}
        all_pids = set()
        for bucket in buckets.values():
            all_pids.update(bucket)
        info = {}
        if all_pids:
            for pr in Product.browse(list(all_pids)).read(
                    ['default_code', 'name', 'uom_id']):
                info[pr['id']] = pr
        lists = []
        for key in ('tekrmd', 'other', 'ncr', 'spare'):
            show_type = key == 'tekrmd'
            rows = []
            for pid, loc_qty in buckets[key].items():
                pr = info.get(pid) or {}
                names = sorted({loc_names.get(lid, '')
                                for lid in loc_qty})
                names = [n for n in names if n]
                total = sum(loc_qty.values())
                total_disp = (int(total) if float(total).is_integer()
                              else round(total, 2))
                uom = (pr.get('uom_id') or [False, ''])[1] or 'Units'
                if is_tr and uom == 'Units':
                    uom = 'Adet'
                code = pr.get('default_code') or ''
                name = pr.get('name') or ''
                lot_text = ', '.join(
                    sorted(lots.get((key, pid), set())))
                row = {
                    'code': code,
                    'name': name,
                    'locs': names,
                    'qty': total_disp,
                    'uom': uom,
                    'qty_text': '%s %s' % (total_disp, uom),
                    'lots': lot_text,
                }
                if show_type:
                    is_main = pid_level.get(pid, 1) == 0
                    row['is_main'] = is_main
                    row['type_label'] = ('Main Part' if is_main
                                         else 'Sub Part')
                rows.append(row)
            if show_type:
                rows.sort(key=lambda r: (
                    0 if r['is_main'] else 1,
                    [n.lower() for n in r['locs']],
                    (r['code'] or '').lower(),
                    (r['name'] or '').lower()))
            else:
                rows.sort(key=lambda r: (
                    [n.lower() for n in r['locs']],
                    (r['code'] or '').lower(),
                    (r['name'] or '').lower()))
            for idx, row in enumerate(rows, 1):
                row['no'] = idx
            lists.append({
                'key': key,
                'title': labels['scope_titles'][key],
                'headers': list(labels['tekrmd_headers'])
                if show_type else list(labels['plain_headers']),
                'show_type': show_type,
                'rows': rows,
                'count': len(rows),
            })
        return _shell(lists)

