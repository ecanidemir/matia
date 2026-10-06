# -*- coding: utf-8 -*-
"""Preview Excel export (separate route; existing Capacity export untouched)."""
import io
import json
from datetime import datetime

from odoo import http
from odoo.http import request

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


def _last_str(itm):
    if not itm.get('last_price'):
        return ''
    cur = itm.get('last_currency') or ''
    return '%s %s' % (itm.get('last_price'), cur)


class MatiaProcurementPlanController(http.Controller):

    @http.route('/matia_procurement_plan/export_xlsx', type='http',
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
        plan_name = data.get('plan_name', 'Plan')
        kits = data.get('kits', [])
        rolled_total = data.get('rolled_total', 0)
        if data.get('mode') == 'tree':
            return self._export_tree(data, plan_name, kits, rolled_total)
        groups = data.get('groups', [])
        total = data.get('total', 0)

        if not xlsxwriter:
            lines = ['\ufeff' + 'Supplier Preview - %s' % plan_name]
            lines.append('Rolled total (USD): %s' % rolled_total)
            for kit in kits:
                lines.append('Kit: %s | %s | %s' % (
                    kit.get('name', ''), kit.get('count', 0),
                    kit.get('cost', 0)))
            for grp in groups:
                lines.append('--- %s (%.2f) ---' % (
                    grp.get('title', ''), grp.get('cost', 0)))
                for itm in grp.get('items', []):
                    lines.append('%s;%s;%s;%s;%s;%s;%s;%s;%s' % (
                        itm.get('code', ''), itm.get('name', ''),
                        itm.get('order_qty', ''), _last_str(itm),
                        itm.get('last_usd', ''), itm.get('last_date', ''),
                        itm.get('unit_usd', ''), itm.get('rolled_usd', ''),
                        itm.get('subtotal', '')))
            content = '\r\n'.join(lines).encode('utf-8')
            filename = 'Supplier_Preview_%s.csv' % datetime.now().strftime(
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
        ws = workbook.add_worksheet('Supplier Preview')
        title_fmt = workbook.add_format(
            {'bold': True, 'font_size': 14})
        header_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#7c2d12', 'font_color': '#ffffff',
             'border': 1})
        num_fmt = workbook.add_format({'border': 1, 'align': 'center'})
        text_fmt = workbook.add_format({'border': 1})
        row = 0
        ws.write(row, 0, 'Supplier Preview - %s' % plan_name, title_fmt)
        row += 1
        ws.write(row, 0, 'Total: %.2f' % (total or 0))
        row += 1
        ws.write(row, 0, 'Rolled total (USD): %s' % rolled_total)
        row += 1
        for kit in kits:
            ws.write(row, 0, 'Kit: %s (%s) - %s' % (
                kit.get('name', ''), kit.get('count', 0),
                kit.get('cost', 0)))
            row += 1
        row += 1
        for grp in groups:
            ws.write(row, 0, '%s (%.2f)' % (
                grp.get('title', ''), grp.get('cost', 0)), header_fmt)
            row += 1
            ws.write_row(row, 0, ['Code', 'Product', 'Order', 'Last Price',
                                  'USD', 'Last Buy', 'Unit USD',
                                  'Rolled USD', 'Subtotal'],
                         header_fmt)
            row += 1
            for itm in grp.get('items', []):
                ws.write(row, 0, itm.get('code', ''), text_fmt)
                ws.write(row, 1, itm.get('name', ''), text_fmt)
                ws.write(row, 2, itm.get('order_qty', 0) or 0, num_fmt)
                ws.write(row, 3, _last_str(itm), text_fmt)
                ws.write(row, 4, itm.get('last_usd', 0) or 0, num_fmt)
                ws.write(row, 5, itm.get('last_date', ''), text_fmt)
                ws.write(row, 6, itm.get('unit_usd', 0) or 0, num_fmt)
                ws.write(row, 7, itm.get('rolled_usd', 0) or 0, num_fmt)
                ws.write(row, 8, itm.get('subtotal', 0) or 0, num_fmt)
                row += 1
            row += 1
        workbook.close()
        output.seek(0)
        filename = 'Supplier_Preview_%s.xlsx' % datetime.now().strftime(
            '%Y%m%d_%H%M')
        return request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument'
                 '.spreadsheetml.sheet'),
                ('Content-Disposition',
                 'attachment; filename=%s' % filename),
            ])

    def _export_tree(self, data, plan_name, kits, rolled_total):
        """Capacity-style indented tree export (visible rows only).

        Columns mirror the Plan tab: TR / US unreserved, Producible
        (TR+US), editable Needed, net Planned. Est. USD = rolled_usd x
        order/net.
        """
        rows = data.get('tree_rows', [])
        headers = ['Part', 'Usage', 'TR', 'US',
                   'Producible', 'Needed', 'Planned', 'Seller',
                   'Source', 'Last Price', 'USD', 'Last Buy', 'Rolled USD',
                   'Est. USD', 'Per-top']
        if not xlsxwriter:
            lines = ['\ufeff' + 'Tree - %s' % plan_name]
            lines.append('Rolled total USD: %s' % rolled_total)
            lines.append(';'.join(headers))
            for r in rows:
                if r.get('is_header'):
                    lines.append('--- %s ---' % r.get('code', ''))
                    continue
                pad = '  ' * int(r.get('level') or 0)
                lines.append(
                    '%s%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s'
                    % (
                        pad, r.get('code', ''), r.get('name', ''),
                        '%s %s' % (r.get('bom_qty', ''),
                                   r.get('uom', '')),
                        r.get('tr', ''), r.get('us', ''),
                        r.get('producible', ''), r.get('need', ''),
                        r.get('planned', ''), r.get('seller', ''),
                        r.get('source', ''),
                        r.get('last', ''), r.get('usd', ''),
                        r.get('date', ''), r.get('rolled_usd', ''),
                        r.get('est_usd', ''), r.get('breakdown', '')))
            content = '\r\n'.join(lines).encode('utf-8')
            filename = 'Tree_%s.csv' % datetime.now().strftime('%Y%m%d_%H%M')
            return request.make_response(
                content,
                headers=[
                    ('Content-Type', 'text/csv; charset=utf-8'),
                    ('Content-Disposition',
                     'attachment; filename=%s' % filename),
                ])
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = workbook.add_worksheet('Tree')
        title_fmt = workbook.add_format({'bold': True, 'font_size': 14})
        header_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#7c2d12', 'font_color': '#ffffff',
             'border': 1})
        num_fmt = workbook.add_format({'border': 1, 'align': 'center'})
        text_fmt = workbook.add_format({'border': 1})
        child_fmt = workbook.add_format(
            {'border': 1, 'bg_color': '#FFFBEB'})
        row = 0
        ws.write(row, 0, 'Tree - %s' % plan_name, title_fmt)
        row += 1
        ws.write(row, 0, 'Rolled total USD: %s' % rolled_total)
        row += 2
        ws.write_row(row, 0, headers, header_fmt)
        row += 1
        for r in rows:
            if r.get('is_header'):
                ws.write(row, 0, r.get('code', ''), header_fmt)
                row += 1
                continue
            lvl = int(r.get('level') or 0)
            pad = '    ' * lvl + ('↳ ' if lvl else '')
            fmt = child_fmt if lvl else text_fmt
            ws.write(row, 0, pad + str(r.get('code', '')), fmt)
            ws.write(row, 1, str(r.get('name', '')), fmt)
            ws.write(row, 2, '%s %s' % (
                r.get('bom_qty', ''), r.get('uom', '')), fmt)
            ws.write(row, 3, r.get('tr', '') or 0, num_fmt)
            ws.write(row, 4, r.get('us', '') or 0, num_fmt)
            ws.write(row, 5, r.get('producible', '') or 0, num_fmt)
            ws.write(row, 6, r.get('need', '') or 0, num_fmt)
            ws.write(row, 7, r.get('planned', '') or 0, num_fmt)
            ws.write(row, 8, r.get('seller', ''), fmt)
            ws.write(row, 9, r.get('source', ''), fmt)
            ws.write(row, 10, r.get('last', ''), fmt)
            ws.write(row, 11, r.get('usd', '') or 0, num_fmt)
            ws.write(row, 12, r.get('date', ''), fmt)
            ws.write(row, 13, r.get('rolled_usd', '') or 0, num_fmt)
            ws.write(row, 14, r.get('est_usd', '') or 0, num_fmt)
            ws.write(row, 15, r.get('breakdown', ''), fmt)
            row += 1
        workbook.close()
        output.seek(0)
        filename = 'Tree_%s.xlsx' % datetime.now().strftime('%Y%m%d_%H%M')
        return request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument'
                 '.spreadsheetml.sheet'),
                ('Content-Disposition',
                 'attachment; filename=%s' % filename),
            ])
