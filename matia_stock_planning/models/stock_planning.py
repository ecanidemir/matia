# -*- coding: utf-8 -*-
import math
from odoo import models, api, _
from odoo.exceptions import UserError

class MatiaStockPlanning(models.AbstractModel):
    _name = 'matia.stock.planning'
    _description = 'Matia TekRMD Cihaz Kapasite ve Stok Planlama'

    @api.model
    def get_capacity_planning_data(self, include_tr=True, include_usa=True, dynamic_targets=None):
        """
        TekRMD Common Parts v2, Outdoor Parts ve Seat Parts reçeteleri üzerinden
        TR ve USA lokasyonlarındaki stokları ve üretilebilir cihaz kapasitelerini hesaplar.
        """
        if not include_tr and not include_usa:
            raise UserError(_("En az bir lokasyon (TR veya USA) seçilmelidir!"))

        if dynamic_targets is None:
            dynamic_targets = []
        # En fazla 3 dinamik hedef kabul et
        dynamic_targets = [int(t) for t in dynamic_targets if str(t).isdigit() and int(t) > 0][:3]

        # 1. Konumları belirle
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

        # 2. Reçeteleri tanımla
        bom_configs = [
            {
                'key': 'base',
                'title': 'TekRMD Common Parts (Base)',
                'badge': 'Base',
                'color_class': 'badge-primary',
                'names': ['TekRMD Common Parts v2', 'TekRMD Common Parts'],
            },
            {
                'key': 'outdoor',
                'title': 'TekRMD Outdoor Parts (Outdoor)',
                'badge': 'Outdoor',
                'color_class': 'badge-success',
                'names': ['TekRMD Outdoor Parts'],
            },
            {
                'key': 'seat',
                'title': 'TekRMD Seat Parts (Seat)',
                'badge': 'Seat',
                'color_class': 'badge-warning',
                'names': ['TekRMD Seat Parts'],
            },
        ]

        all_product_ids = set()
        groups_data = []

        for cfg in bom_configs:
            bom = self.env['mrp.bom'].search([
                '|',
                ('product_tmpl_id.name', 'in', cfg['names']),
                ('code', 'in', cfg['names'])
            ], limit=1)

            if not bom:
                # İkincil arama (ilike)
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
                        'uom_name': line.product_uom_id.name or 'Adet',
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

        # 3. Stok ve NCR Miktarlarını oku
        product_stock = {pid: 0.0 for pid in all_product_ids}
        product_ncr = {pid: 0.0 for pid in all_product_ids}

        if all_product_ids:
            # Geçerli internal stok miktarları
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
                    product_stock[pid] = sq['quantity']

            # NCR miktarları (bilgi amaçlı)
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
                    product_ncr[pid] = nq['quantity']

        # 4. Tablo satırlarını ve KPI'ları hesapla
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

                # Üretilebilecek maksimum cihaz sayısı
                if b_qty > 0:
                    max_dev = math.floor(s_qty / b_qty)
                    if max_dev < 0:
                        max_dev = 0
                else:
                    max_dev = 0

                # 20 Cihaz için ihtiyaç hesabı: (20 * bom_qty) - stock_qty
                needed_20 = (20.0 * b_qty) - s_qty
                if needed_20 <= 0:
                    req_20_status = 'OK'
                    req_20_val = 0
                else:
                    req_20_status = 'NEED'
                    req_20_val = int(math.ceil(needed_20))

                # Dinamik sütun hesapları
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

                item['stock_qty'] = s_qty
                item['ncr_qty'] = n_qty
                item['max_devices'] = max_dev
                item['req_20_status'] = req_20_status
                item['req_20_val'] = req_20_val
                item['req_20_text'] = 'OK' if req_20_status == 'OK' else str(req_20_val)
                item['dynamic_needs'] = dynamic_needs

                # Grup darboğazı
                if max_dev < grp_min_devices:
                    grp_min_devices = max_dev
                    grp_bottleneck_product = item['display_name']

                # Genel darboğaz
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
