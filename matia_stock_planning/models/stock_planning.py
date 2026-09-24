# -*- coding: utf-8 -*-
import math
from odoo import models, api, _
from odoo.exceptions import UserError

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

class MatiaStockPlanning(models.AbstractModel):
    _name = 'matia.stock.planning'
    _description = 'Matia TekRMD Device Capacity and Stock Planning'

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

        # 1. Identify locations
        all_locs = self.env['stock.location'].search([('usage', '=', 'internal')])
        
        tr_stock_locs = []
        usa_stock_locs = []
        tr_ncr_locs = []
        usa_ncr_locs = []

        for loc in all_locs:
            cname = loc.complete_name or ''
            cid = loc.company_id.id if loc.company_id else False
            is_ncr = 'NCR' in cname

            if 'WHTR' in cname or cid == 1:
                if is_ncr:
                    tr_ncr_locs.append(loc.id)
                elif cname.startswith('WHTR/Stock'):
                    tr_stock_locs.append(loc.id)
            elif 'WHUS' in cname or cid == 2:
                if is_ncr:
                    usa_ncr_locs.append(loc.id)
                elif cname.startswith('WHUS/Stock'):
                    usa_stock_locs.append(loc.id)

        selected_loc_ids = []
        selected_ncr_ids = []

        if include_tr:
            selected_loc_ids.extend(tr_stock_locs)
            selected_ncr_ids.extend(tr_ncr_locs)
        if include_usa:
            selected_loc_ids.extend(usa_stock_locs)
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
        ]

        all_product_ids = set()
        groups_data = []

        for cfg in bom_configs:
            bom = False
            # 1. Try preferred direct ID if exists
            pref_id = cfg.get('preferred_id')
            if pref_id:
                pref_bom = self.env['mrp.bom'].browse(pref_id)
                if pref_bom.exists() and pref_bom.active:
                    bom = pref_bom

            # 2. Sequential priority search by exact product template name
            if not bom:
                for n in cfg['names']:
                    bom = self.env['mrp.bom'].search([
                        ('product_tmpl_id.name', '=', n)
                    ], limit=1)
                    if bom:
                        break

            # 3. Fallback search with ilike
            if not bom:
                for n in cfg['names']:
                    bom = self.env['mrp.bom'].search([
                        '|',
                        ('product_tmpl_id.name', 'ilike', n),
                        ('code', 'ilike', n)
                    ], limit=1)
                    if bom:
                        break

            lines_list = []
            if bom:
                for line in bom.bom_line_ids:
                    p = line.product_id
                    all_product_ids.add(p.id)
                    lines_list.append({
                        'product_id': p.id,
                        'product_code': p.default_code or '',
                        'product_name': p.name or '',
                        'display_name': p.display_name or p.name,
                        'bom_qty': line.product_qty or 1.0,
                        'uom_name': _UOM_NAME_MAP.get(line.product_uom_id.name or '', line.product_uom_id.name or 'Units'),
                        'has_bom': bool(p.product_tmpl_id.bom_ids),
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

        # 3. Read stock and NCR quantities
        product_stock = {pid: 0.0 for pid in all_product_ids}
        product_ncr = {pid: 0.0 for pid in all_product_ids}

        if all_product_ids:
            if selected_loc_ids:
                stock_quants = self.env['stock.quant'].read_group(
                    [
                        ('product_id', 'in', list(all_product_ids)),
                        ('location_id', 'in', selected_loc_ids)
                    ],
                    ['product_id', 'quantity'],
                    ['product_id']
                )
                for sq in stock_quants:
                    pid = sq['product_id'][0]
                    product_stock[pid] = float(sq.get('quantity') or 0.0)

            if selected_ncr_ids:
                ncr_quants = self.env['stock.quant'].read_group(
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
                n_qty = product_ncr.get(pid, 0.0)

                # Maximum devices producible
                if b_qty > 0:
                    max_dev = math.floor(s_qty / b_qty)
                    if max_dev < 0:
                        max_dev = 0
                else:
                    max_dev = 0

                # Requirement for 20 devices: (20 * bom_qty) - stock_qty
                needed_20 = (20.0 * b_qty) - s_qty
                if needed_20 <= 0:
                    req_20_status = 'OK'
                    req_20_val = 0
                else:
                    req_20_status = 'NEED'
                    req_20_val = int(math.ceil(needed_20))

                # Dynamic columns
                dynamic_needs = {}
                for target in dynamic_targets:
                    needed_target = (float(target) * b_qty) - s_qty
                    if needed_target <= 0:
                        dynamic_needs[str(target)] = {
                            'status': 'OK',
                            'val': 0,
                            'text': 'OK'
                        }
                    else:
                        c_val = int(math.ceil(needed_target))
                        dynamic_needs[str(target)] = {
                            'status': 'NEED',
                            'val': c_val,
                            'text': str(c_val)
                        }

                s_clean = float(s_qty or 0.0)
                n_clean = float(n_qty or 0.0)
                item['stock_qty'] = int(s_clean) if s_clean.is_integer() else round(s_clean, 2)
                item['ncr_qty'] = int(n_clean) if n_clean.is_integer() else round(n_clean, 2)
                item['max_devices'] = max_dev
                item['req_20_status'] = req_20_status
                item['req_20_val'] = req_20_val
                item['req_20_text'] = 'OK' if req_20_status == 'OK' else str(req_20_val)
                item['dynamic_needs'] = dynamic_needs

                # Group bottleneck
                if max_dev < grp_min_devices:
                    grp_min_devices = max_dev
                    grp_bottleneck_product = item['display_name']

                # Overall bottleneck
                if max_dev < overall_min_devices:
                    overall_min_devices = max_dev
                    overall_bottleneck_product = item['display_name']

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
    def get_sub_bom_details(self, product_id, parent_bom_qty=1.0, dynamic_targets=None, include_tr=True, include_usa=True):
        """
        Fetches the Bill of Materials (BOM) components and their current stock levels
        for a specific sub-assembly product, scaled to the main device requirements.
        """
        product = self.env['product.product'].browse(product_id)
        if not product.exists():
            return {'has_bom': False, 'message': 'Product not found'}

        if dynamic_targets is None:
            dynamic_targets = []
        dynamic_targets = [int(t) for t in dynamic_targets if str(t).isdigit() and int(t) > 0][:3]
        parent_bom_qty = float(parent_bom_qty or 1.0)

        # Find BOM for this product
        bom = self.env['mrp.bom'].search([
            '|',
            ('product_id', '=', product.id),
            '&',
            ('product_id', '=', False),
            ('product_tmpl_id', '=', product.product_tmpl_id.id)
        ], limit=1)

        if not bom:
            # Fallback search by template
            bom = self.env['mrp.bom'].search([
                ('product_tmpl_id', '=', product.product_tmpl_id.id)
            ], limit=1)

        if not bom:
            return {
                'has_bom': False,
                'product_name': product.display_name,
                'message': 'No BOM defined for this product'
            }

        # 1. Identify locations
        all_locs = self.env['stock.location'].search([('usage', '=', 'internal')])
        selected_loc_ids = []
        selected_ncr_ids = []

        for loc in all_locs:
            cname = loc.complete_name or ''
            cid = loc.company_id.id if loc.company_id else False
            is_ncr = 'NCR' in cname

            if 'WHTR' in cname or cid == 1:
                if is_ncr and include_tr:
                    selected_ncr_ids.append(loc.id)
                elif cname.startswith('WHTR/Stock') and include_tr:
                    selected_loc_ids.append(loc.id)
            elif 'WHUS' in cname or cid == 2:
                if is_ncr and include_usa:
                    selected_ncr_ids.append(loc.id)
                elif cname.startswith('WHUS/Stock') and include_usa:
                    selected_loc_ids.append(loc.id)

        # 2. Extract lines
        lines_list = []
        sub_product_ids = set()

        for line in bom.bom_line_ids:
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
                'has_bom': bool(p.product_tmpl_id.bom_ids),
            })

        # 3. Read stock
        product_stock = {pid: 0.0 for pid in sub_product_ids}
        product_ncr = {pid: 0.0 for pid in sub_product_ids}

        if sub_product_ids:
            if selected_loc_ids:
                stock_quants = self.env['stock.quant'].read_group(
                    [
                        ('product_id', 'in', list(sub_product_ids)),
                        ('location_id', 'in', selected_loc_ids)
                    ],
                    ['product_id', 'quantity'],
                    ['product_id']
                )
                for sq in stock_quants:
                    pid = sq['product_id'][0]
                    product_stock[pid] = float(sq.get('quantity') or 0.0)

            if selected_ncr_ids:
                ncr_quants = self.env['stock.quant'].read_group(
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
            s_qty = product_stock.get(pid, 0.0)
            n_qty = product_ncr.get(pid, 0.0)

            if b_qty > 0:
                max_dev = math.floor(s_qty / b_qty)
                if max_dev < 0:
                    max_dev = 0
            else:
                max_dev = 0

            # Requirement for 20 devices: (20 * bom_qty) - stock_qty
            needed_20 = (20.0 * b_qty) - s_qty
            if needed_20 <= 0:
                req_20_status = 'OK'
                req_20_val = 0
            else:
                req_20_status = 'NEED'
                req_20_val = int(math.ceil(needed_20))

            # Dynamic columns
            dynamic_needs = {}
            for target in dynamic_targets:
                needed_target = (float(target) * b_qty) - s_qty
                if needed_target <= 0:
                    dynamic_needs[str(target)] = {
                        'status': 'OK',
                        'val': 0,
                        'text': 'OK'
                    }
                else:
                    c_val = int(math.ceil(needed_target))
                    dynamic_needs[str(target)] = {
                        'status': 'NEED',
                        'val': c_val,
                        'text': str(c_val)
                    }

            s_clean = float(s_qty or 0.0)
            n_clean = float(n_qty or 0.0)
            item['stock_qty'] = int(s_clean) if s_clean.is_integer() else round(s_clean, 2)
            item['ncr_qty'] = int(n_clean) if n_clean.is_integer() else round(n_clean, 2)
            item['max_devices'] = max_dev
            item['req_20_status'] = req_20_status
            item['req_20_val'] = req_20_val
            item['req_20_text'] = 'OK' if req_20_status == 'OK' else str(req_20_val)
            item['dynamic_needs'] = dynamic_needs

            if max_dev < min_producible:
                min_producible = max_dev
                bottleneck_product = item['display_name']

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

