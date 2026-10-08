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


# Single-table layout: the 4 cost groups collapse into ONE flat table.
# Screws belong to Base in Excel (same 1-device set).
_GROUP_LABEL = {'base': 'Base', 'screws': 'Base',
                'outdoor': 'Outdoor', 'seat': 'Seat'}
# Base block stays contiguous: base lines, then screws-as-Base.
_PLAN = [('Base', ['base', 'screws']),
         ('Outdoor', ['outdoor']),
         ('Seat', ['seat'])]
_COLUMNS = ['Group', 'Code', 'Part', 'Usage Qty', 'UoM',
            'Unit USD', 'BOM Cost USD']
# Width caps per column (Group, Code, Part, Usage, UoM, Unit, BOM).
_WIDTH_CAPS = [14, 20, 60, 12, 10, 14, 16]


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
        by_key = {g.get('key'): g for g in groups if g.get('key')}

        if not xlsxwriter:
            lines = ['\ufeffProduct Cost - 1-device set (USD)']
            lines.append('Base (incl. screws): %s | Full: %s | '
                         'Base+Outdoor: %s | Base+Seat: %s' % (
                             combos.get('base', 0),
                             combos.get('full', 0),
                             combos.get('base_outdoor', 0),
                             combos.get('base_seat', 0)))
            lines.append(';'.join(_COLUMNS))
            for label, keys in _PLAN:
                for key in keys:
                    grp = by_key.get(key)
                    if not grp:
                        continue
                    for itm in grp.get('items', []):
                        lines.append('%s;%s;%s;%s;%s;%s;%s' % (
                            label,
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
             'border': 1, 'align': 'center', 'valign': 'vcenter'})
        text_fmt = workbook.add_format({'border': 1})
        indent_fmt = workbook.add_format(
            {'border': 1, 'indent': 2})
        qty_fmt = workbook.add_format(
            {'border': 1, 'align': 'center', 'num_format': '#,##0.00'})
        usd_fmt = workbook.add_format(
            {'border': 1, 'num_format': '"$"#,##0.00'})
        sub_label_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#dbeafe', 'border': 1})
        sub_usd_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#dbeafe', 'border': 1,
             'num_format': '"$"#,##0.00'})
        total_label_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#bfdbfe', 'border': 1})
        total_usd_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#bfdbfe', 'border': 1,
             'num_format': '"$"#,##0.00'})
        # Title + combo summary.
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
        header_row = row
        ws.write_row(header_row, 0, _COLUMNS, header_fmt)
        row += 1
        # Auto-width tracking (header seeds the minimum).
        widths = [len(c) for c in _COLUMNS]

        def _bump(col, val):
            """Track the widest display value per column."""
            if val is None:
                return
            widths[col] = max(widths[col], len(str(val)))

        spans = {}  # label -> list of (first_excel_row, last_excel_row)
        filter_end = header_row

        def _write_detail(label, itm):
            """Write one flat detail row; return its Excel row number."""
            global_row = _write_detail.row
            lvl = int(itm.get('level', 0) or 0)
            fmt = indent_fmt if lvl else text_fmt
            code = itm.get('code', '') or ''
            name = itm.get('name', '') or ''
            usage = float(itm.get('usage', 0) or 0)
            uom = itm.get('uom', '') or ''
            unit = float(itm.get('unit_usd', 0) or 0)
            ext = float(itm.get('ext_usd', 0) or 0)
            ws.write(global_row, 0, label, fmt)
            ws.write(global_row, 1, code, fmt)
            ws.write(global_row, 2, name, fmt)
            ws.write_number(global_row, 3, usage, qty_fmt)
            ws.write(global_row, 4, uom, fmt)
            ws.write_number(global_row, 5, unit, usd_fmt)
            ws.write_number(global_row, 6, ext, usd_fmt)
            _bump(0, label)
            _bump(1, code)
            _bump(2, name)
            _bump(3, '%.2f' % usage)
            _bump(4, uom)
            _bump(5, '$%.2f' % unit)
            _bump(6, '$%.2f' % ext)
            _write_detail.row += 1
            return global_row + 1  # Excel 1-based row number

        _write_detail.row = row
        for label, keys in _PLAN:
            label_spans = []
            for key in keys:
                grp = by_key.get(key)
                items = (grp.get('items', []) or []) if grp else []
                if not items:
                    continue
                first = _write_detail.row + 1
                for itm in items:
                    _write_detail(label, itm)
                label_spans.append((first, _write_detail.row))
            if not label_spans:
                continue
            spans[label] = label_spans
            # Subtotal row: Group cell keeps the label so the row
            # stays visible when the table is filtered by Group.
            # SUBTOTAL(109, ...) sums only visible rows, so the
            # subtotal follows the filter instead of going stale.
            sr = _write_detail.row
            refs = ','.join('G%d:G%d' % (a, b)
                            for a, b in label_spans)
            ws.write(sr, 0, label, sub_label_fmt)
            ws.write(sr, 1, '', sub_label_fmt)
            ws.write(sr, 2, '%s Subtotal' % label, sub_label_fmt)
            ws.write(sr, 3, '', sub_label_fmt)
            ws.write(sr, 4, '', sub_label_fmt)
            ws.write(sr, 5, '', sub_label_fmt)
            ws.write_formula(sr, 6, '=SUBTOTAL(109,%s)' % refs,
                             sub_usd_fmt)
            _bump(2, '%s Subtotal' % label)
            _write_detail.row += 1
            filter_end = sr
        row = _write_detail.row
        # Grand total lives OUTSIDE the autofilter range (blank Group
        # cell would be hidden by a Group filter otherwise) and sums
        # detail rows only (subtotal rows excluded, no double count).
        all_refs = ','.join('G%d:G%d' % (a, b)
                            for rngs in spans.values() for a, b in rngs)
        if all_refs:
            row += 1
            ws.write(row, 0, '', total_label_fmt)
            ws.write(row, 1, '', total_label_fmt)
            ws.write(row, 2, 'GRAND TOTAL', total_label_fmt)
            ws.write(row, 3, '', total_label_fmt)
            ws.write(row, 4, '', total_label_fmt)
            ws.write(row, 5, '', total_label_fmt)
            ws.write_formula(row, 6, '=SUBTOTAL(109,%s)' % all_refs,
                             total_usd_fmt)
            _bump(2, 'GRAND TOTAL')
        last_row = row
        # Auto widths (measured, capped), filter, freeze, print.
        for idx, (w, cap) in enumerate(zip(widths, _WIDTH_CAPS)):
            ws.set_column(idx, idx, min(w + 2, cap))
        if filter_end > header_row:
            ws.autofilter(header_row, 0, filter_end, len(_COLUMNS) - 1)
        ws.freeze_panes(header_row + 1, 0)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
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
