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
        scratch_total = data.get('scratch_total', 0)
        if data.get('mode') == 'tree':
            return self._export_tree(data, plan_name, kits, scratch_total)
        groups = data.get('groups', [])
        total = data.get('total', 0)

        if not xlsxwriter:
            lines = ['\ufeff' + 'Supplier Preview - %s' % plan_name]
            lines.append('Scratch total (USD): %s' % scratch_total)
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
        ws.write(row, 0, 'Scratch total (USD): %s' % scratch_total)
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
                                   'USD', 'Last Buy', 'Net Unit USD',
                                   'Net Total USD', 'Subtotal'],
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

    def _export_tree(self, data, plan_name, kits, scratch_total):
        """Capacity-style indented tree export (visible rows only).

        Columns mirror the Plan tab: TR / US unreserved, Producible
        (TR+US), editable Needed, net Planned. Net USD = stock-netted
        gap unit, Scratch USD = zero-from-scratch unit (Product Cost
        base), Est. USD = net unit x order/net.
        """
        rows = data.get('tree_rows', []) or []
        detail = [r for r in rows if not r.get('is_header')]
        has_level = any(int(r.get('level') or 0) > 0 for r in detail)
        headers = ['Part Code', 'Part Name', 'Usage', 'TR', 'US',
                   'Producible', 'Needed', 'Planned', 'Seller',
                   'Source', 'Last Price', 'USD', 'Last Buy', 'Net USD',
                   'Scratch USD', 'Est. USD']
        if has_level:
            headers.insert(1, 'Level')
        if not xlsxwriter:
            lines = ['\ufeff' + 'Plan - %s' % plan_name]
            lines.append('Scratch total USD: %s' % scratch_total)
            lines.append(';'.join(headers))
            for r in rows:
                if r.get('is_header'):
                    lines.append('--- %s ---' % r.get('code', ''))
                    continue
                lvl = int(r.get('level') or 0)
                cells = [str(r.get('code', ''))]
                if has_level:
                    cells.append('L%d' % lvl if lvl else '')
                cells.extend([
                    str(r.get('name', '')),
                    '%s %s' % (r.get('bom_qty', ''),
                               r.get('uom', '')),
                    str(r.get('tr', '')), str(r.get('us', '')),
                    str(r.get('producible', '')), str(r.get('need', '')),
                    str(r.get('planned', '')), str(r.get('seller', '')),
                    str(r.get('source', '')), str(r.get('last', '')),
                    str(r.get('usd', '')), str(r.get('date', '')),
                    str(r.get('rolled_usd', '')),
                    str(r.get('scratch_usd', '')),
                    str(r.get('est_usd', ''))])
                lines.append(';'.join(cells))
            content = '\r\n'.join(lines).encode('utf-8')
            filename = 'Plan_%s.csv' % datetime.now().strftime('%Y%m%d_%H%M')
            return request.make_response(
                content,
                headers=[
                    ('Content-Type', 'text/csv; charset=utf-8'),
                    ('Content-Disposition',
                     'attachment; filename=%s' % filename),
                ])
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = workbook.add_worksheet('Plan')
        title_fmt = workbook.add_format({'bold': True, 'font_size': 14})
        combo_fmt = workbook.add_format({'bold': True})
        header_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#7c2d12', 'font_color': '#ffffff',
             'border': 1})
        num_fmt = workbook.add_format({'border': 1, 'align': 'center'})
        text_fmt = workbook.add_format({'border': 1})
        money_fmt = workbook.add_format(
            {'border': 1, 'num_format': '"$"#,##0.00'})
        child_fmt = workbook.add_format(
            {'border': 1, 'bg_color': '#FFFBEB'})
        child_money_fmt = workbook.add_format(
            {'border': 1, 'bg_color': '#FFFBEB',
             'num_format': '"$"#,##0.00'})

        def _fnum(val):
            try:
                return float(val or 0)
            except (TypeError, ValueError):
                return 0

        row = 0
        ws.write(row, 0, 'Plan - %s' % plan_name, title_fmt)
        row += 1
        # Single-cell bold summary (rounded, no cents).
        try:
            scratch_txt = '$%s' % '{:,.0f}'.format(
                float(scratch_total or 0))
        except (TypeError, ValueError):
            scratch_txt = '$0'
        ws.write(row, 0, 'Scratch total USD: %s' % scratch_txt,
                 combo_fmt)
        row += 2
        _C = {name: idx for idx, name in enumerate(headers)}
        qty_keys = {'TR': 'tr', 'US': 'us', 'Producible': 'producible',
                    'Needed': 'need', 'Planned': 'planned'}
        money_keys = {'USD': 'usd', 'Net USD': 'rolled_usd',
                      'Scratch USD': 'scratch_usd', 'Est. USD': 'est_usd'}
        caps = {'Part Code': 22, 'Level': 8, 'Part Name': 60,
                'Usage': 16, 'TR': 12, 'US': 12, 'Producible': 12,
                'Needed': 12, 'Planned': 12, 'Seller': 26,
                'Source': 16, 'Last Price': 16, 'USD': 14,
                'Last Buy': 14, 'Net USD': 16, 'Scratch USD': 16,
                'Est. USD': 16}
        widths = [len(h) for h in headers]

        def _bump(col, val):
            """Track the widest display value per column."""
            if val is None:
                return
            widths[col] = max(widths[col], len(str(val)))

        header_row = row
        ws.write_row(header_row, 0, headers, header_fmt)
        row += 1
        for r in rows:
            if r.get('is_header'):
                ws.write(row, 0, r.get('code', ''), header_fmt)
                if has_level:
                    ws.write(row, _C['Level'], '', header_fmt)
                _bump(0, r.get('code', ''))
                row += 1
                continue
            lvl = int(r.get('level') or 0)
            fmt = child_fmt if lvl else text_fmt
            mfmt = child_money_fmt if lvl else money_fmt
            code = str(r.get('code', ''))
            name = str(r.get('name', ''))
            usage = '%s %s' % (r.get('bom_qty', ''), r.get('uom', ''))
            ws.write(row, _C['Part Code'], code, fmt)
            if has_level:
                ws.write(row, _C['Level'],
                         'L%d' % lvl if lvl else '', fmt)
            ws.write(row, _C['Part Name'], name, fmt)
            ws.write(row, _C['Usage'], usage, fmt)
            for col, key in qty_keys.items():
                ws.write_number(row, _C[col], _fnum(r.get(key)), num_fmt)
            ws.write(row, _C['Seller'], r.get('seller', ''), fmt)
            ws.write(row, _C['Source'], r.get('source', ''), fmt)
            ws.write(row, _C['Last Price'], r.get('last', ''), fmt)
            for col, key in money_keys.items():
                ws.write_number(row, _C[col], _fnum(r.get(key)), mfmt)
            ws.write(row, _C['Last Buy'], r.get('date', ''), fmt)
            _bump(_C['Part Code'], code)
            _bump(_C['Part Name'], name)
            _bump(_C['Usage'], usage)
            _bump(_C['Seller'], r.get('seller', ''))
            _bump(_C['Source'], r.get('source', ''))
            _bump(_C['Last Price'], r.get('last', ''))
            _bump(_C['Last Buy'], r.get('date', ''))
            for col, key in money_keys.items():
                _bump(_C[col], '$%.2f' % _fnum(r.get(key)))
            row += 1
        last_row = row - 1
        # Auto widths (measured, capped), filter, freeze, print.
        for idx, h in enumerate(headers):
            ws.set_column(idx, idx, min(widths[idx] + 2, caps[h]))
        if last_row > header_row:
            ws.autofilter(header_row, 0, last_row, len(headers) - 1)
        ws.freeze_panes(header_row + 1, 0)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        workbook.close()
        output.seek(0)
        filename = 'Plan_%s.xlsx' % datetime.now().strftime('%Y%m%d_%H%M')
        return request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument'
                 '.spreadsheetml.sheet'),
                ('Content-Disposition',
                 'attachment; filename=%s' % filename),
            ])
