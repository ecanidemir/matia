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


def _fnum(val):
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0


def _plan_headers(rows):
    """Plan table headers; Level appears only when a row is nested."""
    detail = [r for r in rows if not r.get('is_header')]
    has_level = any(int(r.get('level') or 0) > 0 for r in detail)
    headers = ['Part Code', 'Part Name', 'Usage', 'TR', 'US',
               'Producible', 'Needed', 'Planned', 'Seller',
               'Source', 'Last Price', 'USD', 'Last Buy', 'Net USD',
               'Scratch USD', 'Est. USD']
    if has_level:
        headers.insert(1, 'Level')
    return headers, has_level


def _plan_csv_lines(plan_name, scratch_total, rows):
    """CSV fallback lines for one plan sheet (mirrors the xlsx)."""
    headers, has_level = _plan_headers(rows)
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
    return lines


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
        if data.get('mode') == 'slots':
            return self._export_slots(data)
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
        if not xlsxwriter:
            content = '\r\n'.join(
                _plan_csv_lines(plan_name, scratch_total, rows)
            ).encode('utf-8')
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
        self._write_plan_sheet(workbook, ws, plan_name, scratch_total,
                               rows)
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

    def _write_plan_sheet(self, workbook, ws, plan_name, scratch_total,
                          rows):
        """Write one full Plan table (title + summary + grid) on ws."""
        headers, has_level = _plan_headers(rows)
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

    def _export_slots(self, data):
        """Combined multi-slot export: Compare sheet + one sheet per slot.

        The client fully expands each selected slot and posts its rows,
        so this only assembles the workbook (no recompute server-side).
        """
        plans = []
        seen = set()
        for p in (data.get('plans', []) or [])[:10]:
            if not isinstance(p, dict):
                continue
            try:
                slot = int(p.get('slot'))
            except (TypeError, ValueError):
                continue
            if slot < 0 or slot > 9 or slot in seen:
                continue
            seen.add(slot)
            plans.append({
                'slot': slot,
                'name': p.get('name', '') or '',
                'scratch_total': p.get('scratch_total', 0) or 0,
                'rows': p.get('tree_rows', []) or [],
            })
        if not plans:
            return request.not_found()
        if not xlsxwriter:
            lines = []
            for p in plans:
                lines.append('=== Slot %d - %s ===' % (
                    p['slot'], p['name']))
                lines.extend(_plan_csv_lines(
                    'Slot %d - %s' % (p['slot'], p['name']),
                    p['scratch_total'], p['rows']))
                lines.append('')
            content = '\r\n'.join(lines).encode('utf-8')
            filename = 'Plan_Compare_%s.csv' % datetime.now().strftime(
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
        # Compare sheet: one line per slot.
        ws = workbook.add_worksheet('Compare')
        title_fmt = workbook.add_format({'bold': True, 'font_size': 14})
        header_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#7c2d12', 'font_color': '#ffffff',
             'border': 1})
        num_fmt = workbook.add_format({'border': 1, 'align': 'center'})
        text_fmt = workbook.add_format({'border': 1})
        money_fmt = workbook.add_format(
            {'border': 1, 'num_format': '"$"#,##0.00'})
        ws.write(0, 0, 'Plan Comparison (USD)', title_fmt)
        cmp_headers = ['Slot', 'Study', 'Scratch Total USD',
                       'Detail Lines']
        cmp_caps = [10, 40, 18, 14]
        cmp_widths = [len(h) for h in cmp_headers]
        ws.write_row(1, 0, cmp_headers, header_fmt)
        for i, p in enumerate(plans):
            r = i + 2
            detail_n = len([x for x in p['rows']
                            if not x.get('is_header')])
            ws.write_number(r, 0, p['slot'], num_fmt)
            ws.write(r, 1, p['name'], text_fmt)
            ws.write_number(r, 2, _fnum(p['scratch_total']), money_fmt)
            ws.write_number(r, 3, detail_n, num_fmt)
            cmp_widths[0] = max(cmp_widths[0], len(str(p['slot'])))
            cmp_widths[1] = max(cmp_widths[1], len(p['name']))
            cmp_widths[2] = max(
                cmp_widths[2], len('$%.2f' % _fnum(p['scratch_total'])))
            cmp_widths[3] = max(cmp_widths[3], len(str(detail_n)))
        last_cmp = len(plans) + 1
        for idx, h in enumerate(cmp_headers):
            ws.set_column(idx, idx, min(cmp_widths[idx] + 2, cmp_caps[idx]))
        ws.autofilter(1, 0, last_cmp, len(cmp_headers) - 1)
        ws.freeze_panes(2, 0)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        for p in plans:
            sheet = workbook.add_worksheet('Slot %d' % p['slot'])
            self._write_plan_sheet(
                workbook, sheet,
                'Slot %d - %s' % (p['slot'], p['name']),
                p['scratch_total'], p['rows'])
        workbook.close()
        output.seek(0)
        filename = 'Plan_Compare_%s.xlsx' % datetime.now().strftime(
            '%Y%m%d_%H%M')
        return request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument'
                 '.spreadsheetml.sheet'),
                ('Content-Disposition',
                 'attachment; filename=%s' % filename),
            ])
