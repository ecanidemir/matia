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
_COMBO_OVERFLOW_CAP = 12


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
                else [_WIDTH_CAPS_BASE[0]]) + _WIDTH_CAPS_BASE[1:] + \
            [_COMBO_OVERFLOW_CAP]
        _C = {name: idx for idx, name in enumerate(columns)}
        bom_letter = chr(ord('A') + _C['BOM Cost USD'])

        if not xlsxwriter:
            def _usd0(val):
                """Rounded USD display, no cents (e.g. $4,598)."""
                try:
                    return '$%s' % '{:,.0f}'.format(float(val or 0))
                except (TypeError, ValueError):
                    return '$0'

            lines = ['\ufeffProduct Cost - 1-device set (USD)']
            lines.append('Full: %s | Base+Outdoor: %s | Base+Seat: %s'
                         % (
                             _usd0(combos.get('full')),
                             _usd0(combos.get('base_outdoor')),
                             _usd0(combos.get('base_seat'))))
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
        usd0_fmt = workbook.add_format(
            {'num_format': '"$"#,##0'})
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
        combo_pairs = [
            ('Full:', combos.get('full', 0) or 0),
            ('Base+Outdoor:', combos.get('base_outdoor', 0) or 0),
            ('Base+Seat:', combos.get('base_seat', 0) or 0),
        ]
        for idx, (lab, val) in enumerate(combo_pairs):
            ws.write(row, idx * 2, lab)
            ws.write_number(row, idx * 2 + 1, float(val), usd0_fmt)
        row += 2
        header_row = row
        ws.write_row(header_row, 0, columns, header_fmt)
        row += 1
        # Auto-width tracking (header seeds the minimum; last slot is
        # the combo-summary overflow column).
        widths = [len(c) for c in columns] + [0]

        def _bump(col, val):
            """Track the widest display value per column."""
            if val is None:
                return
            widths[col] = max(widths[col], len(str(val)))

        for idx, (lab, val) in enumerate(combo_pairs):
            _bump(idx * 2, lab)
            _bump(idx * 2 + 1, '$%.0f' % float(val))

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
            ws.write_number(global_row, _C['Unit USD'], unit, usd_fmt)
            ws.write_number(global_row, _C['BOM Cost USD'], ext, usd_fmt)
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
            refs = ','.join('%s%d:%s%d' % (bom_letter, a, bom_letter, b)
                            for a, b in label_spans)
            ws.write(sr, _C['Group'], label, sub_label_fmt)
            for c in range(1, _C['BOM Cost USD']):
                if c == _C['Part']:
                    ws.write(sr, c, '%s Subtotal' % label, sub_label_fmt)
                else:
                    ws.write(sr, c, '', sub_label_fmt)
            ws.write_formula(sr, _C['BOM Cost USD'],
                             '=SUBTOTAL(109,%s)' % refs, sub_usd_fmt)
            _bump(_C['Part'], '%s Subtotal' % label)
            _write_detail.row += 1
            filter_end = sr
        row = _write_detail.row
        # Grand total lives OUTSIDE the autofilter range (blank Group
        # cell would be hidden by a Group filter otherwise) and sums
        # detail rows only (subtotal rows excluded, no double count).
        all_refs = ','.join('%s%d:%s%d' % (bom_letter, a, bom_letter, b)
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
            _bump(_C['Part'], 'GRAND TOTAL')
        last_row = row
        # Auto widths (measured, capped), filter, freeze, print.
        for idx, (w, cap) in enumerate(zip(widths, caps)):
            ws.set_column(idx, idx, min(w + 2, cap))
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
