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

# Slot identity colors for the combined export (pastel, pairwise
# distinguishable side by side): slot N -> SLOT_COLORS[N].
SLOT_COLORS = ['#FCE4EC', '#FFE0B2', '#FFF9C4', '#DCEDC8', '#B2DFDB',
               '#B2EBF2', '#BBDEFB', '#C5CAE9', '#E1BEE7', '#FFCCBC']


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
    headers = ['Group', 'Part Code', 'Part Name', 'Usage', 'TR', 'US',
               'Producible', 'Needed', 'Planned', 'Seller',
               'Source', 'Last Price', 'USD', 'Last Buy', 'Net USD',
               'Scratch USD', 'Est. USD']
    if has_level:
        headers.insert(2, 'Level')
    return headers, has_level


def _usd0(val):
    """Whole-USD display ($5,276) for summary lines."""
    try:
        return '$%s' % ('{:,.0f}'.format(float(val or 0)))
    except (TypeError, ValueError):
        return '$0'


def _combo_line(combo, scratch_total):
    """Cost-style single-cell summary: Full | Base+Outdoor | Base+Seat."""
    if isinstance(combo, dict):
        return 'Full: %s | Base+Outdoor: %s | Base+Seat: %s' % (
            _usd0(combo.get('full')), _usd0(combo.get('outdoor')),
            _usd0(combo.get('seat')))
    return 'Scratch total USD: %s' % scratch_total


def _np_txt(r):
    """Slot Needed/Planned cell: '200/189' (planned alone for children)."""
    need = r.get('need', '')
    planned = r.get('planned', '')
    if need is None or need == '':
        return '' if planned in (None, '') else str(planned)
    return '%s/%s' % (need, planned)


def _plan_csv_lines(plan_name, scratch_total, rows, combo=None):
    """CSV fallback lines for one plan sheet (mirrors the xlsx)."""
    headers, has_level = _plan_headers(rows)
    lines = ['\ufeff' + 'Plan - %s' % plan_name]
    lines.append(_combo_line(combo, scratch_total))
    lines.append(';'.join(headers))
    tot_qty = [0.0] * 5
    tot_money = [0.0] * 3
    for r in rows:
        if r.get('is_header'):
            continue
        lvl = int(r.get('level') or 0)
        cells = [str(r.get('group', '')), str(r.get('code', ''))]
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
        if not lvl:
            for i, k in enumerate(
                    ('tr', 'us', 'producible', 'need', 'planned')):
                tot_qty[i] += _fnum(r.get(k))
            for i, k in enumerate(
                    ('rolled_usd', 'scratch_usd', 'est_usd')):
                tot_money[i] += _fnum(r.get(k))
    total = ['TOTAL', '']
    if has_level:
        total.append('')
    total.extend(['', ''])
    total.extend(['%g' % v for v in tot_qty])
    total.extend(['', '', '', '', ''])
    total.extend(['%g' % tot_money[0],
                  '%g' % tot_money[1], '%g' % tot_money[2]])
    lines.append(';'.join(total))
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
        combo = data.get('combo')
        if not xlsxwriter:
            content = '\r\n'.join(
                _plan_csv_lines(plan_name, scratch_total, rows, combo)
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
                               rows, combo)
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
                          rows, combo=None):
        """Write one full Plan table (title + combo + grid + TOTAL).

        Group-first flat table (no separator rows); child numbers print
        gray like the Cost page; TOTAL sums level-0 rows (static).
        """
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
        child_num_gray_fmt = workbook.add_format(
            {'border': 1, 'align': 'center', 'bg_color': '#FFFBEB',
             'font_color': '#808080'})
        child_money_gray_fmt = workbook.add_format(
            {'border': 1, 'bg_color': '#FFFBEB',
             'font_color': '#808080', 'num_format': '"$"#,##0.00'})
        total_fmt = workbook.add_format({'bold': True, 'border': 1})
        total_num_fmt = workbook.add_format(
            {'bold': True, 'border': 1, 'align': 'center'})
        total_money_fmt = workbook.add_format(
            {'bold': True, 'border': 1, 'num_format': '"$"#,##0.00'})

        row = 0
        ws.write(row, 0, 'Plan - %s' % plan_name, title_fmt)
        row += 1
        # Single-cell bold combo summary (rounded, no cents).
        ws.write(row, 0, _combo_line(combo, scratch_total), combo_fmt)
        row += 2
        _C = {name: idx for idx, name in enumerate(headers)}
        qty_keys = {'TR': 'tr', 'US': 'us', 'Producible': 'producible',
                    'Needed': 'need', 'Planned': 'planned'}
        money_keys = {'USD': 'usd', 'Net USD': 'rolled_usd',
                      'Scratch USD': 'scratch_usd', 'Est. USD': 'est_usd'}
        caps = {'Group': 18, 'Part Code': 22, 'Level': 8,
                'Part Name': 60,
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
        sum_qty = {col: 0.0 for col in qty_keys}
        sum_money = {col: 0.0 for col in
                     ('Net USD', 'Scratch USD', 'Est. USD')}
        for r in rows:
            if r.get('is_header'):
                continue
            lvl = int(r.get('level') or 0)
            fmt = child_fmt if lvl else text_fmt
            qfmt = child_num_gray_fmt if lvl else num_fmt
            mfmt = child_money_gray_fmt if lvl else money_fmt
            code = str(r.get('code', ''))
            name = str(r.get('name', ''))
            usage = '%s %s' % (r.get('bom_qty', ''), r.get('uom', ''))
            ws.write(row, _C['Group'], r.get('group', ''), fmt)
            ws.write(row, _C['Part Code'], code, fmt)
            if has_level:
                ws.write(row, _C['Level'],
                         'L%d' % lvl if lvl else '', fmt)
            ws.write(row, _C['Part Name'], name, fmt)
            ws.write(row, _C['Usage'], usage, fmt)
            for col, key in qty_keys.items():
                ws.write_number(row, _C[col], _fnum(r.get(key)), qfmt)
            ws.write(row, _C['Seller'], r.get('seller', ''), fmt)
            ws.write(row, _C['Source'], r.get('source', ''), fmt)
            ws.write(row, _C['Last Price'], r.get('last', ''), fmt)
            for col, key in money_keys.items():
                ws.write_number(row, _C[col], _fnum(r.get(key)), mfmt)
            ws.write(row, _C['Last Buy'], r.get('date', ''), fmt)
            _bump(_C['Group'], r.get('group', ''))
            _bump(_C['Part Code'], code)
            _bump(_C['Part Name'], name)
            _bump(_C['Usage'], usage)
            _bump(_C['Seller'], r.get('seller', ''))
            _bump(_C['Source'], r.get('source', ''))
            _bump(_C['Last Price'], r.get('last', ''))
            _bump(_C['Last Buy'], r.get('date', ''))
            for col, key in money_keys.items():
                _bump(_C[col], '$%.2f' % _fnum(r.get(key)))
            if not lvl:
                for col, key in qty_keys.items():
                    sum_qty[col] += _fnum(r.get(key))
                for col in sum_money:
                    sum_money[col] += _fnum(r.get(money_keys[col]))
            row += 1
        # TOTAL row (level-0 sums, static); kept out of the filter.
        ws.write(row, _C['Group'], 'TOTAL', total_fmt)
        ws.write(row, _C['Part Code'], '', total_fmt)
        if has_level:
            ws.write(row, _C['Level'], '', total_fmt)
        ws.write(row, _C['Part Name'], '', total_fmt)
        ws.write(row, _C['Usage'], '', total_fmt)
        for col in qty_keys:
            ws.write_number(row, _C[col], sum_qty[col], total_num_fmt)
        for col in ('Seller', 'Source', 'Last Price', 'USD', 'Last Buy'):
            ws.write(row, _C[col], '', total_fmt)
        for col in ('Net USD', 'Scratch USD', 'Est. USD'):
            ws.write_number(row, _C[col], sum_money[col],
                            total_money_fmt)
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
                'combo': p.get('combo')
                if isinstance(p.get('combo'), dict) else None,
                'scratch_total': p.get('scratch_total', 0) or 0,
                'rows': p.get('tree_rows', []) or [],
            })
        if not plans:
            return request.not_found()
        # Canonical rows from the first slot; per-slot overlays key on
        # (group, pid-or-code, level, occurrence).
        def _mbase_key(r):
            pid = r.get('pid')
            if pid is None:
                pid = r.get('code', '')
            return (r.get('group', ''), pid, int(r.get('level') or 0))

        def _overlay(rows):
            d = {}
            seen = {}
            for r in rows:
                if r.get('is_header'):
                    continue
                k = _mbase_key(r)
                seen[k] = seen.get(k, 0) + 1
                d[k + (seen[k],)] = r
            return d

        canon = [r for r in plans[0]['rows'] if not r.get('is_header')]
        canon_keys = []
        seen = {}
        for r in canon:
            k = _mbase_key(r)
            seen[k] = seen.get(k, 0) + 1
            canon_keys.append(k + (seen[k],))
        overlays = [_overlay(p['rows']) for p in plans]
        any_level = any(int(r.get('level') or 0) > 0 for r in canon)
        mbase = ['Group', 'Part Code', 'Part Name', 'Usage', 'TR', 'US',
                 'Producible', 'Scratch USD']
        if any_level:
            mbase.insert(2, 'Level')
        mheaders = list(mbase)
        for p in plans:
            mheaders.append('Slot %d N/P' % p['slot'])
            mheaders.append('Slot %d Est. USD' % p['slot'])
        if not xlsxwriter:
            lines = ['\ufeffCombined Plan - Slots %s' % (
                ', '.join(str(p['slot']) for p in plans))]
            lines.append(';'.join(mheaders))
            m_tot = [0.0] * 4
            m_est = [0.0] * len(plans)
            for ck, r in zip(canon_keys, canon):
                lvl = int(r.get('level') or 0)
                cells = [str(r.get('group', '')),
                         str(r.get('code', ''))]
                if any_level:
                    cells.append('L%d' % lvl if lvl else '')
                cells.extend([
                    str(r.get('name', '')),
                    '%s %s' % (r.get('bom_qty', ''),
                               r.get('uom', '')),
                    str(r.get('tr', '')), str(r.get('us', '')),
                    str(r.get('producible', '')),
                    str(r.get('scratch_usd', ''))])
                if not lvl:
                    for i, k in enumerate(('tr', 'us', 'producible')):
                        m_tot[i] += _fnum(r.get(k))
                    m_tot[3] += _fnum(r.get('scratch_usd'))
                for i, ov in enumerate(overlays):
                    o = ov.get(ck)
                    cells.append(_np_txt(o) if o else '')
                    cells.append(str(o.get('est_usd', ''))
                                 if o else '')
                    if o and not lvl:
                        m_est[i] += _fnum(o.get('est_usd'))
                lines.append(';'.join(cells))
            total = ['TOTAL', '']
            if any_level:
                total.append('')
            total.extend(['', '', '%g' % m_tot[0], '%g' % m_tot[1],
                          '%g' % m_tot[2], '%g' % m_tot[3]])
            for v in m_est:
                total.extend(['', '%g' % v])
            lines.append(';'.join(total))
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
        child_fmt = workbook.add_format(
            {'border': 1, 'bg_color': '#FFFBEB'})
        child_num_gray_fmt = workbook.add_format(
            {'border': 1, 'align': 'center', 'bg_color': '#FFFBEB',
             'font_color': '#808080'})
        child_money_gray_fmt = workbook.add_format(
            {'border': 1, 'bg_color': '#FFFBEB',
             'font_color': '#808080', 'num_format': '"$"#,##0.00'})
        total_fmt = workbook.add_format({'bold': True, 'border': 1})
        total_num_fmt = workbook.add_format(
            {'bold': True, 'border': 1, 'align': 'center'})
        total_money_fmt = workbook.add_format(
            {'bold': True, 'border': 1, 'num_format': '"$"#,##0.00'})
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
        # Combined matrix sheet: slot info block on top (each slot in
        # its own pastel color), then the fixed base columns plus one
        # colored Needed/Planned + Est. USD pair per slot.
        mC = {name: idx for idx, name in enumerate(mheaders)}
        ws = workbook.add_worksheet('Combined')
        slot_fmts = []
        for p in plans:
            color = SLOT_COLORS[p['slot'] % len(SLOT_COLORS)]
            slot_fmts.append({
                'text': workbook.add_format(
                    {'border': 1, 'bg_color': color}),
                'gray': workbook.add_format(
                    {'border': 1, 'bg_color': color,
                     'font_color': '#808080'}),
                'money': workbook.add_format(
                    {'border': 1, 'bg_color': color,
                     'num_format': '"$"#,##0.00'}),
                'money_gray': workbook.add_format(
                    {'border': 1, 'bg_color': color,
                     'font_color': '#808080',
                     'num_format': '"$"#,##0.00'}),
                'header': workbook.add_format(
                    {'bold': True, 'border': 1, 'bg_color': color}),
                'total': workbook.add_format(
                    {'bold': True, 'border': 1, 'bg_color': color,
                     'num_format': '"$"#,##0.00'}),
            })
        mwidths = [len(h) for h in mheaders]

        def _mbump(col, val):
            if val is None:
                return
            mwidths[col] = max(mwidths[col], len(str(val)))

        ws.write(0, 0, 'Combined Plan (USD)', title_fmt)
        ws.write_row(1, 0, ['Slot', 'Study', 'Scratch Total USD'],
                     header_fmt)
        for i, p in enumerate(plans):
            f = slot_fmts[i]
            r = i + 2
            ws.write(r, 0, 'Slot %d' % p['slot'], f['header'])
            ws.write(r, 1, p['name'], f['text'])
            ws.write_number(r, 2, _fnum(p['scratch_total']), f['money'])
            _mbump(0, 'Slot %d' % p['slot'])
            _mbump(1, p['name'])
            _mbump(2, '$%.2f' % _fnum(p['scratch_total']))
        hrow = len(plans) + 3
        ws.write_row(hrow, 0, mheaders, header_fmt)
        for i, p in enumerate(plans):
            f = slot_fmts[i]
            ws.write(hrow, mC['Slot %d N/P' % p['slot']],
                     'Slot %d N/P' % p['slot'], f['header'])
            ws.write(hrow, mC['Slot %d Est. USD' % p['slot']],
                     'Slot %d Est. USD' % p['slot'], f['header'])
        m_tot = [0.0] * 4
        m_est = [0.0] * len(plans)
        r = hrow + 1
        for ck, row in zip(canon_keys, canon):
            lvl = int(row.get('level') or 0)
            fmt = child_fmt if lvl else text_fmt
            qfmt = child_num_gray_fmt if lvl else num_fmt
            mfmt = child_money_gray_fmt if lvl else money_fmt
            ws.write(r, mC['Group'], row.get('group', ''), fmt)
            ws.write(r, mC['Part Code'], str(row.get('code', '')), fmt)
            if any_level:
                ws.write(r, mC['Level'],
                         'L%d' % lvl if lvl else '', fmt)
            ws.write(r, mC['Part Name'], str(row.get('name', '')), fmt)
            usage = '%s %s' % (row.get('bom_qty', ''),
                               row.get('uom', ''))
            ws.write(r, mC['Usage'], usage, fmt)
            for col, key in (('TR', 'tr'), ('US', 'us'),
                             ('Producible', 'producible')):
                ws.write_number(r, mC[col], _fnum(row.get(key)), qfmt)
            ws.write_number(r, mC['Scratch USD'],
                            _fnum(row.get('scratch_usd')), mfmt)
            _mbump(mC['Group'], row.get('group', ''))
            _mbump(mC['Part Code'], row.get('code', ''))
            _mbump(mC['Part Name'], row.get('name', ''))
            _mbump(mC['Usage'], usage)
            _mbump(mC['Scratch USD'],
                   '$%.2f' % _fnum(row.get('scratch_usd')))
            if not lvl:
                for i, key in enumerate(('tr', 'us', 'producible')):
                    m_tot[i] += _fnum(row.get(key))
                m_tot[3] += _fnum(row.get('scratch_usd'))
            for i, ov in enumerate(overlays):
                f = slot_fmts[i]
                o = ov.get(ck)
                np_col = mC['Slot %d N/P' % plans[i]['slot']]
                est_col = mC['Slot %d Est. USD' % plans[i]['slot']]
                if o is None:
                    ws.write(r, np_col, '', f['text'])
                    ws.write(r, est_col, '', f['text'])
                    continue
                np_txt = _np_txt(o)
                if lvl:
                    ws.write(r, np_col, np_txt, f['gray'])
                    ws.write_number(r, est_col, _fnum(o.get('est_usd')),
                                    f['money_gray'])
                else:
                    ws.write(r, np_col, np_txt, f['text'])
                    ws.write_number(r, est_col, _fnum(o.get('est_usd')),
                                    f['money'])
                    m_est[i] += _fnum(o.get('est_usd'))
                _mbump(np_col, np_txt)
                _mbump(est_col, '$%.2f' % _fnum(o.get('est_usd')))
            r += 1
        # TOTAL row (level-0 sums, static); kept out of the filter.
        ws.write(r, mC['Group'], 'TOTAL', total_fmt)
        ws.write(r, mC['Part Code'], '', total_fmt)
        if any_level:
            ws.write(r, mC['Level'], '', total_fmt)
        ws.write(r, mC['Part Name'], '', total_fmt)
        ws.write(r, mC['Usage'], '', total_fmt)
        for i, col in enumerate(('TR', 'US', 'Producible')):
            ws.write_number(r, mC[col], m_tot[i], total_num_fmt)
        ws.write_number(r, mC['Scratch USD'], m_tot[3], total_money_fmt)
        for i, p in enumerate(plans):
            ws.write(r, mC['Slot %d N/P' % p['slot']], '',
                     total_fmt)
            ws.write_number(r, mC['Slot %d Est. USD' % p['slot']],
                            m_est[i], slot_fmts[i]['total'])
        last_m = r - 1
        mcaps = {'Group': 18, 'Part Code': 40, 'Level': 8,
                 'Part Name': 60, 'Usage': 16, 'TR': 12, 'US': 12,
                 'Producible': 12, 'Scratch USD': 16}
        for idx, h in enumerate(mheaders):
            if h in mcaps:
                cap = mcaps[h]
            elif h.endswith('N/P'):
                cap = 16
            else:
                cap = 16
            ws.set_column(idx, idx, min(mwidths[idx] + 2, cap))
        if last_m > hrow:
            ws.autofilter(hrow, 0, last_m, len(mheaders) - 1)
        ws.freeze_panes(hrow + 1, 0)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        for p in plans:
            sheet = workbook.add_worksheet('Slot %d' % p['slot'])
            self._write_plan_sheet(
                workbook, sheet,
                'Slot %d - %s' % (p['slot'], p['name']),
                p['scratch_total'], p['rows'], p.get('combo'))
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
