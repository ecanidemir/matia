# -*- coding: utf-8 -*-
"""Product Cost Excel export (separate route; existing exports untouched)."""
import io
import json
from datetime import datetime

from odoo import http
from odoo.http import request

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class MatiaProductCostController(http.Controller):

    @http.route('/matia_product_cost/export_xlsx', type='http',
                auth='user', methods=['POST'], csrf=False)
    def export_xlsx(self, **kwargs):
        data_json = kwargs.get('data')
        if not data_json:
            return request.not_found()
        # Admin group only
        if not request.env.user.has_group('base.group_system'):
            return request.not_found()
        try:
            data = json.loads(data_json)
        except (TypeError, ValueError):
            return request.not_found()
        combos = data.get('combos', {}) or {}
        groups = data.get('groups', []) or []

        if not xlsxwriter:
            lines = ['\ufeffProduct Cost - 1-device set (USD)']
            lines.append('Base (incl. screws): %s | Full: %s | '
                         'Base+Outdoor: %s | Base+Seat: %s' % (
                             combos.get('base', 0),
                             combos.get('full', 0),
                             combos.get('base_outdoor', 0),
                             combos.get('base_seat', 0)))
            for grp in groups:
                lines.append('--- %s (%.2f) ---' % (
                    grp.get('title', ''), grp.get('set_total', 0)))
                for itm in grp.get('items', []):
                    lines.append('%s;%s;%s;%s;%s;%s' % (
                        '  ' * int(itm.get('level', 0) or 0) +
                        (itm.get('code', '') or ''),
                        itm.get('name', ''), itm.get('usage', ''),
                        itm.get('uom', ''), itm.get('unit_usd', ''),
                        itm.get('ext_usd', '')))
            content = '\r\n'.join(lines).encode('utf-8')
            filename = 'Product_Cost_%s.csv' % datetime.now().strftime(
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
        ws = workbook.add_worksheet('Product Cost')
        title_fmt = workbook.add_format(
            {'bold': True, 'font_size': 14})
        header_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#1e40af', 'font_color': '#ffffff',
             'border': 1})
        group_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#dbeafe', 'border': 1})
        num_fmt = workbook.add_format({'border': 1, 'align': 'center'})
        text_fmt = workbook.add_format({'border': 1})
        indent_fmt = workbook.add_format(
            {'border': 1, 'indent': 2})
        row = 0
        ws.write(row, 0, 'Product Cost - 1-device set (USD)', title_fmt)
        row += 1
        ws.write(row, 0, 'Base (incl. screws): %.2f | Full: %.2f | '
                         'Base+Outdoor: %.2f | Base+Seat: %.2f' % (
                             combos.get('base', 0) or 0,
                             combos.get('full', 0) or 0,
                             combos.get('base_outdoor', 0) or 0,
                             combos.get('base_seat', 0) or 0))
        row += 2
        for grp in groups:
            ws.write(row, 0, '%s (%.2f / set)' % (
                grp.get('title', ''), grp.get('set_total', 0) or 0),
                group_fmt)
            row += 1
            ws.write_row(row, 0, ['Code', 'Part', 'Usage Qty', 'UoM',
                                  'Unit USD', 'BOM Cost USD'],
                         header_fmt)
            row += 1
            for itm in grp.get('items', []):
                lvl = int(itm.get('level', 0) or 0)
                fmt = indent_fmt if lvl else text_fmt
                ws.write(row, 0, itm.get('code', ''), fmt)
                ws.write(row, 1, itm.get('name', ''), fmt)
                ws.write(row, 2, itm.get('usage', 0) or 0, num_fmt)
                ws.write(row, 3, itm.get('uom', ''), text_fmt)
                ws.write(row, 4, itm.get('unit_usd', 0) or 0, num_fmt)
                ws.write(row, 5, itm.get('ext_usd', 0) or 0, num_fmt)
                row += 1
            row += 1
        workbook.close()
        output.seek(0)
        filename = 'Product_Cost_%s.xlsx' % datetime.now().strftime(
            '%Y%m%d_%H%M')
        return request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument'
                 '.spreadsheetml.sheet'),
                ('Content-Disposition',
                 'attachment; filename=%s' % filename),
            ])
