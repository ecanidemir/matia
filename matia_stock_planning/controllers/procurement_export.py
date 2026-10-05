# -*- coding: utf-8 -*-
"""Onizleme Excel export (ayri route; mevcut Capacity export'a dokunmaz)."""
import io
import json
from datetime import datetime

from odoo import http
from odoo.http import request

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class MatiaProcurementPlanController(http.Controller):

    @http.route('/matia_procurement_plan/export_xlsx', type='http',
                auth='user', methods=['POST'], csrf=False)
    def export_xlsx(self, **kwargs):
        data_json = kwargs.get('data')
        if not data_json:
            return request.not_found()
        # Sadece admin grubu indirebilir
        if not request.env.user.has_group('base.group_system'):
            return request.not_found()
        data = json.loads(data_json)
        groups = data.get('groups', [])
        plan_name = data.get('plan_name', 'Plan')
        total = data.get('total', 0)

        if not xlsxwriter:
            lines = ['\ufeff' + 'Tedarikci Onizleme - %s' % plan_name]
            for grp in groups:
                lines.append('--- %s (%.2f) ---' % (
                    grp.get('title', ''), grp.get('cost', 0)))
                for itm in grp.get('items', []):
                    lines.append('%s;%s;%s;%s' % (
                        itm.get('code', ''), itm.get('name', ''),
                        itm.get('order_qty', ''), itm.get('subtotal', '')))
            content = '\r\n'.join(lines).encode('utf-8')
            filename = 'Tedarik_Onizleme_%s.csv' % datetime.now().strftime(
                '%Y%m%d_%H%M')
            return request.make_response(
                content,
                headers=[
                    ('Content-Type', 'text/csv; charset=utf-8'),
                    ('Content-Disposition',
                     'attachment; filename=%s' % filename),
                ])

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = workbook.add_worksheet('Tedarikci Onizleme')
        title_fmt = workbook.add_format(
            {'bold': True, 'font_size': 14})
        header_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#7c2d12', 'font_color': '#ffffff',
             'border': 1})
        num_fmt = workbook.add_format({'border': 1, 'align': 'center'})
        text_fmt = workbook.add_format({'border': 1})
        row = 0
        ws.write(row, 0, 'Tedarikci Onizleme - %s' % plan_name, title_fmt)
        row += 1
        ws.write(row, 0, 'Toplam: %.2f' % (total or 0))
        row += 2
        for grp in groups:
            ws.write(row, 0, '%s (%.2f)' % (
                grp.get('title', ''), grp.get('cost', 0)), header_fmt)
            row += 1
            ws.write_row(row, 0, ['Kod', 'Urun', 'Siparis', 'Tutar'],
                         header_fmt)
            row += 1
            for itm in grp.get('items', []):
                ws.write(row, 0, itm.get('code', ''), text_fmt)
                ws.write(row, 1, itm.get('name', ''), text_fmt)
                ws.write(row, 2, itm.get('order_qty', 0) or 0, num_fmt)
                ws.write(row, 3, itm.get('subtotal', 0) or 0, num_fmt)
                row += 1
            row += 1
        workbook.close()
        output.seek(0)
        filename = 'Tedarik_Onizleme_%s.xlsx' % datetime.now().strftime(
            '%Y%m%d_%H%M')
        return request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument'
                 '.spreadsheetml.sheet'),
                ('Content-Disposition',
                 'attachment; filename=%s' % filename),
            ])
