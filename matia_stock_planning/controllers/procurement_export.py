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


def _usd0num(val):
    """Whole-USD number for the combined export (no cents)."""
    try:
        return round(float(val or 0))
    except (TypeError, ValueError):
        return 0


def _combined_supplier_table(plans):
    """Condense per-slot supplier breakdowns for the combined sheet.

    One table for all locations: rows are (location, supplier)
    pairs, so each location block (TR, USA, ...) closes with its
    own SUBTOTAL row and the sheet ends with a grand TOTAL. Values
    are the slot's supplier cost, split by line Source label.
    @return (locs, blocks, present): locations in block order
        ('' last), {loc: {supplier: [per-slot floats]}},
        {(supplier, plan_idx)} seen in that slot.
    """
    blocks = {}
    present = set()
    n = len(plans)
    for i, p in enumerate(plans):
        sup = p.get('supplier') or {}
        for g in sup.get('groups', []) or []:
            title = g.get('title', '') or ''
            present.add((title, i))
            per_loc = {}
            for itm in g.get('items', []) or []:
                lc = (itm.get('last_company', '') or '').strip()
                v = itm.get('subtotal', None)
                if v is None:
                    v = itm.get('total_usd', 0)
                try:
                    v = float(v or 0)
                except (TypeError, ValueError):
                    v = 0
                per_loc[lc] = per_loc.get(lc, 0) + v
            if not per_loc:
                try:
                    c = float(g.get('cost') or 0)
                except (TypeError, ValueError):
                    c = 0
                per_loc[''] = c
            for lc, c in per_loc.items():
                arr = blocks.setdefault(lc, {}).setdefault(
                    title, [0.0] * n)
                arr[i] += c
    locs = sorted(blocks, key=lambda l: (l == '', l.lower()))
    return locs, blocks, present


def _supplier_csv_lines(plan_name, groups, total, kits, scratch_total):
    """CSV fallback lines for one supplier sheet (mirrors the xlsx)."""
    lines = ['\ufeff' + 'Supplier Preview - %s' % plan_name]
    lines.append('Total: %s' % (total or 0))
    lines.append('Scratch total (USD): %s' % scratch_total)
    for kit in kits or []:
        lines.append('Kit: %s | %s | %s' % (
            kit.get('name', ''), kit.get('count', 0),
            kit.get('cost', 0)))
    for grp in groups or []:
        lines.append('--- %s (%s) ---' % (
            grp.get('title', ''), grp.get('cost', 0)))
        for itm in grp.get('items', []):
            lines.append('%s;%s;%s;%s;%s;%s;%s;%s;%s' % (
                itm.get('code', ''), itm.get('name', ''),
                itm.get('order_qty', ''), _last_str(itm),
                itm.get('last_usd', ''), itm.get('last_date', ''),
                itm.get('unit_usd', ''), itm.get('rolled_usd', ''),
                itm.get('subtotal', '')))
    return lines


def _plan_csv_lines(plan_name, scratch_total, rows, combo=None):
    """CSV fallback lines for one plan sheet (mirrors the xlsx)."""
    headers, has_level = _plan_headers(rows)
    lines = ['\ufeff' + 'Plan - %s' % plan_name]
    lines.append(_combo_line(combo, scratch_total))
    lines.append(';'.join(headers))
    tot_est = 0.0
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
            tot_est += _fnum(r.get('est_usd'))
    total = ['TOTAL', '']
    if has_level:
        total.append('')
    total.extend(['', ''])
    total.extend(['', '', '', '', ''])
    total.extend(['', '', '', '', ''])
    total.extend(['', '', '%g' % tot_est])
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
        if data.get('mode') == 'plan_supplier':
            return self._export_plan_supplier(data)
        groups = data.get('groups', [])
        total = data.get('total', 0)

        if not xlsxwriter:
            content = '\r\n'.join(
                _supplier_csv_lines(
                    plan_name, groups, total, kits, scratch_total)
            ).encode('utf-8')
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
        self._write_supplier_sheet(workbook, ws, plan_name, groups,
                                   total, kits, scratch_total)
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

    @staticmethod
    def _write_supplier_sheet(workbook, ws, plan_name, groups, total,
                              kits, scratch_total):
        """Write one supplier breakdown table (shared by all modes)."""
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
        for kit in kits or []:
            ws.write(row, 0, 'Kit: %s (%s) - %s' % (
                kit.get('name', ''), kit.get('count', 0),
                kit.get('cost', 0)))
            row += 1
        row += 1
        for grp in groups or []:
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

    def _export_plan_supplier(self, data):
        """Single slot + suppliers: Plan sheet + Suppliers sheet."""
        plan_name = data.get('plan_name', 'Plan')
        rows = data.get('tree_rows', []) or []
        combo = data.get('combo')
        kits = data.get('kits', [])
        scratch_total = data.get('scratch_total', 0)
        sup = data.get('supplier') or {}
        groups = sup.get('groups', [])
        total = sup.get('total', 0)
        sup_kits = sup.get('kits', kits)
        sup_scratch = sup.get('scratch_total', scratch_total)
        if not xlsxwriter:
            lines = _plan_csv_lines(
                plan_name, scratch_total, rows, combo)
            lines.append('')
            lines.extend(_supplier_csv_lines(
                sup.get('plan_name', plan_name), groups, total,
                sup_kits, sup_scratch))
            content = '\r\n'.join(lines).encode('utf-8')
            filename = 'Plan_Supplier_%s.csv' % datetime.now().strftime(
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
        ws = workbook.add_worksheet('Plan')
        self._write_plan_sheet(workbook, ws, plan_name, scratch_total,
                               rows, combo)
        ws2 = workbook.add_worksheet('Suppliers')
        self._write_supplier_sheet(
            workbook, ws2, sup.get('plan_name', plan_name), groups,
            total, sup_kits, sup_scratch)
        workbook.close()
        output.seek(0)
        filename = 'Plan_Supplier_%s.xlsx' % datetime.now().strftime(
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
        gray like the Cost page; TOTAL shows the Est. USD level-0 sum
        (static).
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
        sum_est = 0.0
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
                sum_est += _fnum(r.get('est_usd'))
            row += 1
        # TOTAL row: Est. USD only (level-0 sum, static); kept out of
        # the filter.
        ws.write(row, _C['Group'], 'TOTAL', total_fmt)
        ws.write(row, _C['Part Code'], '', total_fmt)
        if has_level:
            ws.write(row, _C['Level'], '', total_fmt)
        ws.write(row, _C['Part Name'], '', total_fmt)
        ws.write(row, _C['Usage'], '', total_fmt)
        for col in qty_keys:
            ws.write(row, _C[col], '', total_fmt)
        for col in ('Seller', 'Source', 'Last Price', 'USD', 'Last Buy'):
            ws.write(row, _C[col], '', total_fmt)
        for col in ('Net USD', 'Scratch USD'):
            ws.write(row, _C[col], '', total_fmt)
        ws.write_number(row, _C['Est. USD'], sum_est, total_money_fmt)
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
        """Combined multi-slot export: single Combined sheet, BOM closed.

        The client posts fully expanded rows per slot, but the combined
        matrix always uses level-0 rows only (never the BOM-open
        version). All money in the Combined sheet is whole-USD
        (rounded, no cents). With the supplier option a single
        Suppliers sheet is appended: Supplier | Location | one
        rounded total column per slot (slot description as header,
        slot pastel). Suppliers share one table across locations:
        each location block (TR, USA, ...) closes with a SUBTOTAL
        row, then a grand TOTAL.
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
                'kits': p.get('kits', []) or [],
                'supplier': p.get('supplier')
                if isinstance(p.get('supplier'), dict) else None,
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
                if int(r.get('level') or 0) > 0:
                    continue
                k = _mbase_key(r)
                seen[k] = seen.get(k, 0) + 1
                d[k + (seen[k],)] = r
            return d

        canon = [r for r in plans[0]['rows']
                 if not r.get('is_header')
                 and int(r.get('level') or 0) == 0]
        canon_keys = []
        seen = {}
        for r in canon:
            k = _mbase_key(r)
            seen[k] = seen.get(k, 0) + 1
            canon_keys.append(k + (seen[k],))
        overlays = [_overlay(p['rows']) for p in plans]
        # Combined is always BOM-closed: level-0 rows only, no Level col.
        mbase = ['Group', 'Part Code', 'Part Name', 'Usage', 'Unit Cost']
        mheaders = list(mbase)
        # One Est. USD column per slot, headed by the slot description.
        slot_titles = []
        for p in plans:
            title = (p.get('name') or '').strip()
            if not title or title in slot_titles:
                title = 'Slot %d' % p['slot']
            slot_titles.append(title)
            mheaders.append(title)
        with_supplier = any(p.get('supplier') for p in plans)
        if not xlsxwriter:
            lines = ['\ufeffCombined Plan - Slots %s' % (
                ', '.join(str(p['slot']) for p in plans))]
            lines.append(';'.join(mheaders))
            m_est = [0] * len(plans)
            for ck, r in zip(canon_keys, canon):
                lvl = int(r.get('level') or 0)
                cells = [str(r.get('group', '')),
                         str(r.get('code', '')),
                         str(r.get('name', '')),
                         '%s %s' % (r.get('bom_qty', ''),
                                    r.get('uom', '')),
                         '%d' % _usd0num(r.get('scratch_usd'))]
                for i, ov in enumerate(overlays):
                    o = ov.get(ck)
                    est = _usd0num(o.get('est_usd')) if o else ''
                    cells.append(str(est))
                    if o and not lvl:
                        m_est[i] += _usd0num(o.get('est_usd'))
                lines.append(';'.join(cells))
            total = ['TOTAL', '', '', '', '']
            for v in m_est:
                total.append('%d' % v)
            lines.append(';'.join(total))
            if with_supplier:
                locs, blocks, present = _combined_supplier_table(
                    plans)
                lines.append('')
                lines.append('Suppliers (USD)')
                lines.append(';'.join(
                    ['Supplier', 'Location'] + slot_titles))
                s_est = [0] * len(plans)
                for loc in locs:
                    b_est = [0] * len(plans)
                    for name in sorted(blocks[loc],
                                       key=lambda t: t.lower()):
                        arr = blocks[loc][name]
                        cells = [name, loc or '—']
                        for i in range(len(plans)):
                            if (name, i) in present:
                                v = _usd0num(arr[i])
                                cells.append('%d' % v)
                                b_est[i] += v
                                s_est[i] += v
                            else:
                                cells.append('')
                        lines.append(';'.join(cells))
                    slab = ['%s SUBTOTAL' % (loc or '—'), '']
                    for v in b_est:
                        slab.append('%d' % v)
                    lines.append(';'.join(slab))
                stotal = ['TOTAL', '']
                for v in s_est:
                    stotal.append('%d' % v)
                lines.append(';'.join(stotal))
            content = '\r\n'.join(lines).encode('utf-8')
            filename = 'Plan_Combined_%s.csv' % datetime.now().strftime(
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
        title_fmt = workbook.add_format({'bold': True, 'font_size': 14})
        header_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#7c2d12', 'font_color': '#ffffff',
             'border': 1})
        num_fmt = workbook.add_format({'border': 1, 'align': 'center'})
        text_fmt = workbook.add_format({'border': 1})
        # Combined money is whole-USD (rounded, no cents).
        money_fmt = workbook.add_format(
            {'border': 1, 'num_format': '"$"#,##0'})
        child_fmt = workbook.add_format(
            {'border': 1, 'bg_color': '#FFFBEB'})
        child_num_gray_fmt = workbook.add_format(
            {'border': 1, 'align': 'center', 'bg_color': '#FFFBEB',
             'font_color': '#808080'})
        child_money_gray_fmt = workbook.add_format(
            {'border': 1, 'bg_color': '#FFFBEB',
             'font_color': '#808080', 'num_format': '"$"#,##0'})
        total_fmt = workbook.add_format({'bold': True, 'border': 1})
        total_num_fmt = workbook.add_format(
            {'bold': True, 'border': 1, 'align': 'center'})
        total_money_fmt = workbook.add_format(
            {'bold': True, 'border': 1, 'num_format': '"$"#,##0'})
        # Combined matrix sheet: fixed base columns plus one Est. USD
        # column per slot (slot description as header, slot pastel).
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
                     'num_format': '"$"#,##0'}),
                'money_gray': workbook.add_format(
                    {'border': 1, 'bg_color': color,
                     'font_color': '#808080',
                     'num_format': '"$"#,##0'}),
                'header': workbook.add_format(
                    {'bold': True, 'border': 1, 'bg_color': color}),
                'total': workbook.add_format(
                    {'bold': True, 'border': 1, 'bg_color': color,
                     'num_format': '"$"#,##0'}),
            })
        mwidths = [len(h) for h in mheaders]

        def _mbump(col, val):
            if val is None:
                return
            mwidths[col] = max(mwidths[col], len(str(val)))

        ws.write(0, 0, 'Combined Plan (USD)', title_fmt)
        hrow = 2
        ws.write_row(hrow, 0, mheaders, header_fmt)
        for i, title in enumerate(slot_titles):
            ws.write(hrow, len(mbase) + i, title,
                     slot_fmts[i]['header'])
        m_est = [0] * len(plans)
        r = hrow + 1
        for ck, row in zip(canon_keys, canon):
            lvl = int(row.get('level') or 0)
            fmt = child_fmt if lvl else text_fmt
            mfmt = child_money_gray_fmt if lvl else money_fmt
            unit = _usd0num(row.get('scratch_usd'))
            ws.write(r, mC['Group'], row.get('group', ''), fmt)
            ws.write(r, mC['Part Code'], str(row.get('code', '')), fmt)
            ws.write(r, mC['Part Name'], str(row.get('name', '')), fmt)
            usage = '%s %s' % (row.get('bom_qty', ''),
                               row.get('uom', ''))
            ws.write(r, mC['Usage'], usage, fmt)
            ws.write_number(r, mC['Unit Cost'], unit, mfmt)
            _mbump(mC['Group'], row.get('group', ''))
            _mbump(mC['Part Code'], row.get('code', ''))
            _mbump(mC['Part Name'], row.get('name', ''))
            _mbump(mC['Usage'], usage)
            _mbump(mC['Unit Cost'], '$%d' % unit)
            for i, ov in enumerate(overlays):
                f = slot_fmts[i]
                o = ov.get(ck)
                est_col = len(mbase) + i
                if o is None:
                    ws.write(r, est_col, '', f['text'])
                    continue
                est = _usd0num(o.get('est_usd'))
                if lvl:
                    ws.write_number(r, est_col, est, f['money_gray'])
                else:
                    ws.write_number(r, est_col, est, f['money'])
                    m_est[i] += est
                _mbump(est_col, '$%d' % est)
            r += 1
        # TOTAL row: per-slot Est. USD only (level-0 sums, static);
        # kept out of the filter.
        ws.write(r, mC['Group'], 'TOTAL', total_fmt)
        ws.write(r, mC['Part Code'], '', total_fmt)
        ws.write(r, mC['Part Name'], '', total_fmt)
        ws.write(r, mC['Usage'], '', total_fmt)
        ws.write(r, mC['Unit Cost'], '', total_fmt)
        for i in range(len(plans)):
            ws.write_number(r, len(mbase) + i, m_est[i],
                            slot_fmts[i]['total'])
        last_m = r - 1
        mcaps = {'Group': 18, 'Part Code': 40,
                 'Part Name': 60, 'Usage': 16, 'Unit Cost': 16}
        for idx, h in enumerate(mheaders):
            ws.set_column(idx, idx, min(mwidths[idx] + 2,
                                        mcaps.get(h, 16)))
        if last_m > hrow:
            ws.autofilter(hrow, 0, last_m, len(mheaders) - 1)
        ws.freeze_panes(hrow + 1, 0)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        if with_supplier:
            locs, blocks, present = _combined_supplier_table(plans)
            sheaders = ['Supplier', 'Location'] + slot_titles
            ws2 = workbook.add_worksheet('Suppliers')
            ws2.write(0, 0, 'Suppliers (USD)', title_fmt)
            shrow = 2
            ws2.write_row(shrow, 0, sheaders, header_fmt)
            for i, title in enumerate(slot_titles):
                ws2.write(shrow, 2 + i, title,
                          slot_fmts[i]['header'])
            swidths = [len(h) for h in sheaders]

            def _sbump(col, val):
                if val is None:
                    return
                swidths[col] = max(swidths[col], len(str(val)))

            s_est = [0] * len(plans)
            r2 = shrow + 1
            for loc in locs:
                b_est = [0] * len(plans)
                for name in sorted(blocks[loc],
                                   key=lambda t: t.lower()):
                    arr = blocks[loc][name]
                    ws2.write(r2, 0, name, text_fmt)
                    ws2.write(r2, 1, loc or '—', text_fmt)
                    _sbump(0, name)
                    _sbump(1, loc or '—')
                    for i in range(len(plans)):
                        scol = 2 + i
                        if (name, i) in present:
                            est = _usd0num(arr[i])
                            ws2.write_number(r2, scol, est,
                                             slot_fmts[i]['money'])
                            b_est[i] += est
                            s_est[i] += est
                            _sbump(scol, '$%d' % est)
                        else:
                            ws2.write(r2, scol, '',
                                      slot_fmts[i]['text'])
                    r2 += 1
                slab = '%s SUBTOTAL' % (loc or '—')
                ws2.write(r2, 0, slab, total_fmt)
                ws2.write(r2, 1, '', total_fmt)
                for i in range(len(plans)):
                    ws2.write_number(r2, 2 + i, b_est[i],
                                     slot_fmts[i]['total'])
                _sbump(0, slab)
                r2 += 1
            # Grand TOTAL, kept out of the filter.
            ws2.write(r2, 0, 'TOTAL', total_fmt)
            ws2.write(r2, 1, '', total_fmt)
            for i in range(len(plans)):
                ws2.write_number(r2, 2 + i, s_est[i],
                                 slot_fmts[i]['total'])
            last_s = r2 - 1
            scaps = [40, 20] + [16] * len(plans)
            for idx in range(len(sheaders)):
                ws2.set_column(idx, idx,
                               min(swidths[idx] + 2, scaps[idx]))
            if last_s > shrow:
                ws2.autofilter(shrow, 0, last_s, len(sheaders) - 1)
            ws2.freeze_panes(shrow + 1, 0)
            ws2.set_landscape()
            ws2.fit_to_pages(1, 0)
        workbook.close()
        output.seek(0)
        prefix = 'Plan_Combined_Supplier' if with_supplier \
            else 'Plan_Combined'
        filename = '%s_%s.xlsx' % (
            prefix, datetime.now().strftime('%Y%m%d_%H%M'))
        return request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument'
                 '.spreadsheetml.sheet'),
                ('Content-Disposition',
                 'attachment; filename=%s' % filename),
            ])
