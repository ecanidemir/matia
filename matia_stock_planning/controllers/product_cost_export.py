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
_COLUMNS_BASE = ['Group', 'Code', 'Part', 'Usage Qty', 'UoM',
                 'Unit USD', 'BOM Cost USD']
# Width caps for the base columns (Group, Code, Part, Usage, UoM,
# Unit, BOM). The optional Level column caps at 8, the combo-summary
# overflow column at 12.
_WIDTH_CAPS_BASE = [14, 20, 60, 12, 10, 14, 16]
_LEVEL_CAP = 8


def _usd0_rounded(val):
    """Rounded USD display, no cents (e.g. $4,598)."""
    try:
        return '$%s' % '{:,.0f}'.format(float(val or 0))
    except (TypeError, ValueError):
        return '$0'


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
        # Level column appears only when a sub-BOM is expanded
        # (any item with level > 0): Group | Level | Code | ...
        # Top-level rows keep a blank Level cell. No leading spaces
        # or indent anywhere; depth reads from the Level cell
        # (L1..L10).
        has_level = any(
            int(itm.get('level', 0) or 0) > 0
            for grp in by_key.values()
            for itm in (grp.get('items', []) or []))
        columns = (['Group', 'Level'] if has_level
                   else ['Group']) + _COLUMNS_BASE[1:]
        caps = ([_WIDTH_CAPS_BASE[0], _LEVEL_CAP] if has_level
                else [_WIDTH_CAPS_BASE[0]]) + _WIDTH_CAPS_BASE[1:]
        _C = {name: idx for idx, name in enumerate(columns)}
        bom_letter = chr(ord('A') + _C['BOM Cost USD'])
        # Two formula paths: without Level every row is level 0, so
        # SUBTOTAL(109, ...) ranges over BOM Cost directly (7 cols).
        # With Level, an expanded child's cost is already rolled into
        # its top-level row, so a hidden helper keeps the BOM cost
        # only on blank-Level rows (0 below) and SUBTOTAL ranges
        # over the helper instead (8 cols, helper hidden).
        if has_level:
            level_letter = chr(ord('A') + _C['Level'])
            helper_col = _C['BOM Cost USD'] + 1
            helper_letter = chr(ord('A') + helper_col)
            sum_letter = helper_letter
        else:
            sum_letter = bom_letter

        if not xlsxwriter:
            lines = ['\ufeffProduct Cost - 1-device set (USD)']
            lines.append('Full: %s | Base+Outdoor: %s | Base+Seat: %s'
                         % (
                             _usd0_rounded(combos.get('full')),
                             _usd0_rounded(combos.get('base_outdoor')),
                             _usd0_rounded(combos.get('base_seat'))))
            lines.append(';'.join(columns))
            for label, keys in _PLAN:
                for key in keys:
                    grp = by_key.get(key)
                    if not grp:
                        continue
                    for itm in grp.get('items', []):
                        lvl = int(itm.get('level', 0) or 0)
                        vals = {
                            'Group': label,
                            'Code': itm.get('code', '') or '',
                            'Part': itm.get('name', ''),
                            'Usage Qty': itm.get('usage', ''),
                            'UoM': itm.get('uom', ''),
                            'Unit USD': itm.get('unit_usd', ''),
                            'BOM Cost USD': itm.get('ext_usd', ''),
                        }
                        if has_level:
                            vals['Level'] = 'L%d' % lvl if lvl else ''
                        lines.append(';'.join(
                            str(vals.get(c, '')) for c in columns))
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
        combo_fmt = workbook.add_format({'bold': True})
        header_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#1e40af', 'font_color': '#ffffff',
             'border': 1, 'align': 'center', 'valign': 'vcenter'})
        text_fmt = workbook.add_format({'border': 1})
        level_fmt = workbook.add_format(
            {'border': 1, 'align': 'center'})
        qty_fmt = workbook.add_format(
            {'border': 1, 'align': 'center', 'num_format': '#,##0.00'})
        usd_fmt = workbook.add_format(
            {'border': 1, 'num_format': '"$"#,##0.00'})
        # Child (L1+) prices are breakdown detail already rolled into
        # the top-level row, so they print gray to signal they are
        # not added into the subtotals again.
        usd_child_fmt = workbook.add_format(
            {'border': 1, 'num_format': '"$"#,##0.00',
             'font_color': 'gray'})
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
        # Single-cell bold summary (values pre-rounded as $5,276 text).
        ws.write(row, 0, 'Full: %s | Base+Outdoor: %s | Base+Seat: %s' % (
            _usd0_rounded(combos.get('full')),
            _usd0_rounded(combos.get('base_outdoor')),
            _usd0_rounded(combos.get('base_seat'))), combo_fmt)
        row += 2
        header_row = row
        ws.write_row(header_row, 0, columns, header_fmt)
        if has_level:
            ws.write(header_row, helper_col, 'L0 Cost', header_fmt)
        row += 1
        # Auto-width tracking (header seeds the minimum).
        widths = [len(c) for c in columns]

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
            code = itm.get('code', '') or ''
            name = itm.get('name', '') or ''
            usage = float(itm.get('usage', 0) or 0)
            uom = itm.get('uom', '') or ''
            unit = float(itm.get('unit_usd', 0) or 0)
            ext = float(itm.get('ext_usd', 0) or 0)
            ws.write(global_row, _C['Group'], label, text_fmt)
            if has_level:
                ws.write(global_row, _C['Level'],
                         'L%d' % lvl if lvl else '', level_fmt)
                _bump(_C['Level'], 'L%d' % lvl if lvl else '')
            ws.write(global_row, _C['Code'], code, text_fmt)
            ws.write(global_row, _C['Part'], name, text_fmt)
            ws.write_number(global_row, _C['Usage Qty'], usage, qty_fmt)
            ws.write(global_row, _C['UoM'], uom, text_fmt)
            money_fmt = (usd_child_fmt if lvl > 0 else usd_fmt)
            ws.write_number(global_row, _C['Unit USD'], unit, money_fmt)
            ws.write_number(global_row, _C['BOM Cost USD'], ext, money_fmt)
            if has_level:
                excel_row = global_row + 1
                ws.write_formula(
                    global_row, helper_col,
                    '=IF(%s%d="",%s%d,0)' % (
                        level_letter, excel_row, bom_letter, excel_row))
            # Adjacent detail rows merge into one SUBTOTAL range.
            er = global_row + 1
            rngs = spans.setdefault(label, [])
            if rngs and rngs[-1][1] + 1 == er:
                rngs[-1] = (rngs[-1][0], er)
            else:
                rngs.append((er, er))
            _bump(_C['Group'], label)
            _bump(_C['Code'], code)
            _bump(_C['Part'], name)
            _bump(_C['Usage Qty'], '%.2f' % usage)
            _bump(_C['UoM'], uom)
            _bump(_C['Unit USD'], '$%.2f' % unit)
            _bump(_C['BOM Cost USD'], '$%.2f' % ext)
            _write_detail.row += 1
            return global_row + 1  # Excel 1-based row number

        _write_detail.row = row
        for label, keys in _PLAN:
            for key in keys:
                grp = by_key.get(key)
                items = (grp.get('items', []) or []) if grp else []
                for itm in items:
                    _write_detail(label, itm)
            label_spans = spans.get(label, [])
            if not label_spans:
                continue
            # Subtotal row: Group cell keeps the label so the row
            # stays visible when the table is filtered by Group.
            # SUBTOTAL(109, ...) sums only visible rows, so the
            # subtotal follows the filter instead of going stale.
            sr = _write_detail.row
            refs = ','.join('%s%d:%s%d' % (sum_letter, a, sum_letter, b)
                            for a, b in label_spans)
            ws.write(sr, _C['Group'], label, sub_label_fmt)
            for c in range(1, _C['BOM Cost USD']):
                if c == _C['Part']:
                    ws.write(sr, c, '%s Subtotal' % label, sub_label_fmt)
                else:
                    ws.write(sr, c, '', sub_label_fmt)
            ws.write_formula(sr, _C['BOM Cost USD'],
                             '=SUBTOTAL(109,%s)' % refs, sub_usd_fmt)
            if has_level:
                ws.write(sr, helper_col, '', sub_label_fmt)
            _bump(_C['Part'], '%s Subtotal' % label)
            _write_detail.row += 1
            filter_end = sr
        row = _write_detail.row
        # Grand total lives OUTSIDE the autofilter range (blank Group
        # cell would be hidden by a Group filter otherwise) and sums
        # detail rows only (subtotal rows excluded, no double count).
        all_refs = ','.join('%s%d:%s%d' % (sum_letter, a, sum_letter, b)
                            for rngs in spans.values() for a, b in rngs)
        if all_refs:
            row += 1
            for c in range(0, _C['BOM Cost USD']):
                if c == _C['Part']:
                    ws.write(row, c, 'GRAND TOTAL', total_label_fmt)
                else:
                    ws.write(row, c, '', total_label_fmt)
            ws.write_formula(row, _C['BOM Cost USD'],
                             '=SUBTOTAL(109,%s)' % all_refs,
                             total_usd_fmt)
            if has_level:
                ws.write(row, helper_col, '', total_label_fmt)
            _bump(_C['Part'], 'GRAND TOTAL')
        last_row = row
        # Auto widths (measured, capped), filter, freeze, print.
        for idx, (w, cap) in enumerate(zip(widths, caps)):
            ws.set_column(idx, idx, min(w + 2, cap))
        if has_level:
            ws.set_column(helper_col, helper_col, None, None,
                          {'hidden': True})
        if filter_end > header_row:
            ws.autofilter(header_row, 0, filter_end, len(columns) - 1)
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
