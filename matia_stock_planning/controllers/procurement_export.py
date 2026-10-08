# -*- coding: utf-8 -*-
"""Preview Excel export (separate route; existing Capacity export untouched)."""
import io
import json
import logging
import math
from datetime import datetime

from odoo import http
from odoo.http import request


_logger = logging.getLogger(__name__)

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None

from .product_cost_export import cost_csv_lines, write_cost_sheet

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


# Canonical group order for the combined Products sheet (user rule):
# Base first, then Outdoor, then Seat. Screws rows are shown inside
# the Base block, below the Base rows.
_GROUP_RANK = {'base': 0, 'screws': 0, 'outdoor': 1, 'seat': 2}
_TITLE_TO_KEY = {'Base': 'base', 'Screws': 'screws',
                 'Outdoor': 'outdoor', 'Seat': 'seat'}


def _row_group_key(r):
    """Canonical group key of an export row.

    New clients send `gkey`; older payloads carry only the Group
    title, which is mapped back (titles are server-controlled).
    """
    gk = (r.get('gkey') or '').strip().lower()
    if gk in _GROUP_RANK:
        return gk
    return _TITLE_TO_KEY.get((r.get('group') or '').strip(), '')


def _canon_sort_key(r):
    """Combined-sheet row order: Base, Outdoor, Seat; Screws last
    inside Base; code/name order inside each block (deterministic
    across slots so the per-slot overlays stay aligned)."""
    gk = _row_group_key(r)
    return (_GROUP_RANK.get(gk, 99), 1 if gk == 'screws' else 0,
            (r.get('code') or '').lower(), (r.get('name') or '').lower())


def _display_group(r):
    """Group cell text: Screws rows read as Base (user rule)."""
    if _row_group_key(r) in ('base', 'screws'):
        return 'Base'
    return r.get('group', '')


# Below this, even 2 decimals would print $0.00, so 4 decimals
# are kept (the never-show-0 rule wins over the 2-decimal rule).
_TINY_USD = 0.005


def _usd_kind(val, small_under=1.0):
    """Display rule for money cells (user rule: never show 0).

    @return (kind, num): 'blank' for missing/true-zero (the cell
        stays empty instead of $0), 'small' for non-zero values
        below small_under (2 decimals, or 4 when below _TINY_USD),
        'whole' otherwise (raw value; the xlsx number format rounds
        the display, the CSV twin rounds half-up itself).
    """
    try:
        f = float(val)
    except (TypeError, ValueError):
        return 'blank', 0.0
    if not f:
        return 'blank', 0.0
    if abs(f) < small_under:
        return 'small', f
    return 'whole', f


def _small_fmt_no(num, fmt_small, fmt_tiny):
    """2-decimal format unless the value needs 4 (tiny)."""
    if abs(num) < _TINY_USD:
        return fmt_tiny or fmt_small
    return fmt_small


def _write_usd(ws, row, col, val, fmt_whole, fmt_small, fmt_blank,
               small_under=1.0, fmt_tiny=None):
    """Write one money cell with the never-show-0 rule."""
    kind, num = _usd_kind(val, small_under)
    if kind == 'blank':
        ws.write(row, col, '', fmt_blank)
    elif kind == 'small':
        ws.write_number(row, col, num,
                        _small_fmt_no(num, fmt_small, fmt_tiny))
    else:
        ws.write_number(row, col, num, fmt_whole)


def _usd_csv(val, small_under=1.0, dec=0):
    """CSV twin of the never-show-0 rule.

    @param dec decimals for regular values (0 = whole-USD columns,
        2 = cents columns); half-up rounding (banker's round(0.5)
        would print a 0).
    """
    kind, num = _usd_kind(val, small_under)
    if kind == 'blank':
        return ''
    if kind == 'small':
        return '%.4f' % num if abs(num) < _TINY_USD else '%.2f' % num
    if dec:
        _p = 10 ** dec
        return ('%.{}f'.format(dec)
                % (math.floor(num * _p + 0.5) / _p))
    return '%d' % math.floor(num + 0.5)


def _usd_text(val):
    """Prose total: '$1,234', '$0.12' when sub-dollar, '$0'
    only for a genuine zero total (data cells stay blank instead)."""
    kind, num = _usd_kind(val)
    if kind == 'small':
        return '$%.4f' % num if abs(num) < _TINY_USD else '$%.2f' % num
    if kind == 'blank':
        return '$0'
    return '$%s' % ('{:,.0f}'.format(math.floor(num + 0.5)))


def _supsummary_v2(sup):
    """Normalize a get_supplier_summary result for Excel (USD basis).

    PO-value USD per (seller, company) group -- the same figures the
    Suppliers tab shows (own last-buy USD x order; unknown-route
    lines listed but out of the cash total).
    """
    groups = []
    for sp in sup.get('suppliers') or []:
        groups.append({
            'title': sp.get('seller_name', '') or '',
            'company': sp.get('company', '') or '',
            'cost': sp.get('total_usd', 0) or 0,
            'items': sp.get('lines', []) or [],
        })
    return {
        'v': 2,
        'plan_name': sup.get('plan_name', '') or '',
        'groups': groups,
        'total': sup.get('grand_total_usd', 0) or 0,
        'grand_rolled_usd': sup.get('grand_rolled_usd', 0) or 0,
        'unpriced_count': sup.get('unpriced_count', 0) or 0,
        'unsourced_count': sup.get('unsourced_count', 0) or 0,
        'unknown_total_usd': sup.get('unknown_total_usd', 0) or 0,
        'unknown_count': sup.get('unknown_count', 0) or 0,
        'kits': sup.get('kits', []) or [],
        'scratch_total': sup.get('scratch_total_usd', 0) or 0,
    }


def _combined_supplier_table(plans):
    """Condense per-slot supplier breakdowns for the combined sheet.

    One table for all buy-from companies: rows are (company,
    supplier) pairs, so each company block (TR, USA, ...) closes
    with its own SUBTOTAL row and the sheet ends with a grand
    TOTAL. v2 payloads carry the company + PO-value USD per group
    (the Suppliers tab basis); legacy payloads (no `v`) fall back
    to the old per-line Source split.
    @return (locs, blocks, present): companies in block order
        ('' last), {loc: {supplier: [per-slot floats]}},
        {(supplier, loc, plan_idx)} seen in that slot.
    """
    blocks = {}
    present = set()
    n = len(plans)
    for i, p in enumerate(plans):
        sup = p.get('supplier') or {}
        if (sup.get('v') or 0) == 2:
            for g in sup.get('groups', []) or []:
                title = g.get('title', '') or ''
                loc = (g.get('company', '') or '').strip()
                try:
                    c = float(g.get('cost') or 0)
                except (TypeError, ValueError):
                    c = 0
                present.add((title, loc, i))
                arr = blocks.setdefault(loc, {}).setdefault(
                    title, [0.0] * n)
                arr[i] += c
            continue
        for g in sup.get('groups', []) or []:
            title = g.get('title', '') or ''
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
                present.add((title, lc, i))
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


def _supplier_csv_lines_v2(sup):
    """CSV fallback for the v2 supplier sheet (USD PO-value)."""
    lines = ['\ufeff' + 'Supplier Preview - %s (USD, PO-value)'
             % (sup.get('plan_name', '') or 'Plan')]
    lines.append('Total PO value: %s' % _usd_text(sup.get('total')))
    if sup.get('unsourced_count'):
        lines.append('No supplier lines: %d'
                     % sup.get('unsourced_count'))
    if sup.get('unpriced_count'):
        lines.append('Unpriced lines: %d' % sup.get('unpriced_count'))
    if sup.get('unknown_count'):
        lines.append('Unknown-route lines: %d (not in total)'
                     % sup.get('unknown_count'))
    for kit in sup.get('kits', []) or []:
        lines.append('Kit: %s | %s | %s' % (
            kit.get('name', ''), kit.get('count', 0),
            kit.get('cost', 0)))
    lines.append(';'.join(
        ['Supplier', 'Buy From', 'Code', 'Product', 'Order',
         'Last Price', 'USD', 'Last Buy', 'Net Unit USD',
         'Net Total USD', 'PO Total USD']))
    for grp in sup.get('groups', []) or []:
        lines.append('--- %s [%s] (%s) ---' % (
            grp.get('title', ''), grp.get('company', ''),
            _usd_text(grp.get('cost'))))
        for itm in grp.get('items', []) or []:
            badges = ''
            if itm.get('no_seller'):
                badges += ' [No supplier]'
            if (itm.get('route') or '') == 'unknown':
                badges += ' [Unknown route]'
            if itm.get('no_price'):
                badges += ' [No price]'
            lines.append(';'.join([
                str(grp.get('title', '')),
                str(grp.get('company', '')),
                str(itm.get('code', '')),
                '%s%s' % (itm.get('name', ''), badges),
                str(itm.get('order_qty', '')),
                '%s %s' % (itm.get('last_price', ''),
                           itm.get('last_currency', '')),
                _usd_csv(itm.get('last_usd'), 0.005, 2),
                str(itm.get('last_date', '')),
                _usd_csv(itm.get('rolled_usd'), 0.005, 2),
                _usd_csv(itm.get('rolled_total_usd'), 0.005, 2),
                _usd_csv(itm.get('total_usd'), 0.005, 2)]))
    lines.append(';'.join(
        ['TOTAL', '', '', '', '', '', '', '', '', '',
         _usd_csv(sup.get('total'), 0.005, 2)]))
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


def _js_round(val):
    """JS Math.round port (half-up; export money is non-negative)."""
    try:
        return math.floor(float(val or 0) + 0.5)
    except (TypeError, ValueError):
        return 0


def _first_num(*vals):
    """parseFloat(v)||0 of the first set value (None/'' skipped)."""
    for v in vals:
        if v is None or v == '':
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _row_net(r):
    """_rowNet port: net ?? planned ?? gross (0.0 counts as set)."""
    return _first_num(r.get('net'), r.get('planned'), r.get('gross'))


def _avail_total(r):
    """_availTotal port: avail_total ?? avail_tr."""
    a = r.get('avail_total')
    if a is None or a == '':
        return _fnum(r.get('avail_tr'))
    try:
        return float(a)
    except (TypeError, ValueError):
        return _fnum(r.get('avail_tr'))


def _producible_of(r, avail):
    """_producible port: field, else floor(avail/bom_qty), else avail."""
    p = r.get('producible')
    if p is None or p == '':
        bq = _fnum(r.get('bom_qty'))
        if bq > 0:
            return max(0, math.floor(avail / bq))
        return max(0, avail)
    return _fnum(p)


def _est_usd(r, row_net, level=0):
    """_estUsd port: level-0 rows use the retained kit share (the same
    cents as the screen cards and the supplier grand total); sub-rows
    and pre-rebuild payloads keep rolled_usd x (order_qty or row net).
    """
    if not level:
        try:
            ret = float(r.get('retained_total_usd') or 0)
        except (TypeError, ValueError):
            ret = 0.0
        if ret > 0:
            return ret
    try:
        ru = float(r.get('rolled_usd') or 0)
    except (TypeError, ValueError):
        ru = 0.0
    q = r.get('order_qty')
    if q is None or q == '':
        q = row_net
    try:
        q = float(q)
    except (TypeError, ValueError):
        q = 0.0
    return ru * q


def _jsnum(val):
    """int when integral (JS JSON number shape: 200.0 serializes 200)."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return val
    return int(f) if f.is_integer() else f


def _fmt_en2(val):
    """_fmtNum(v, 2) port (en-style; browser locale may differ)."""
    try:
        return '{:,.2f}'.format(float(val or 0))
    except (TypeError, ValueError):
        return '0.00'


def _fmt_last(itm):
    """_fmtLast port: '12.50 USD' (no trailing space without currency)."""
    if not itm.get('last_price'):
        return ''
    cur = itm.get('last_currency') or ''
    return '%s%s' % (_fmt_en2(itm.get('last_price')),
                     (' ' + cur) if cur else '')


def _port_row(r, group, level, targets=None, gkey=None):
    """One client-shape export row from a server tree item.

    Mirrors _collectExportRows mapping (group/gkey/pid/code/name/
    level/bom_qty/uom/tr/us/producible/need/planned/seller/source/
    last/usd/date/rolled_usd/scratch_usd/est_usd). UoM values arrive
    server-mapped; the client _uomEn leaves them unchanged.
    """
    pid = r.get('product_id')
    net = _row_net(r)
    avail = _avail_total(r)
    if level == 0:
        need = r.get('need')
        if need is None or need == '':
            need = 0
            if targets:
                need = targets.get(pid, targets.get(str(pid), 0))
        need = _jsnum(_fnum(need))
    else:
        need = ''
    return {
        'group': group, 'gkey': gkey or '', 'pid': pid,
        'code': r.get('code', '') or '',
        'name': r.get('name', '') or '',
        'level': level,
        'bom_qty': r.get('bom_qty', ''),
        'uom': r.get('uom', '') or '',
        'tr': _jsnum(_fnum(r.get('avail_tr'))),
        'us': _jsnum(_fnum(r.get('avail_us'))),
        'producible': _jsnum(_producible_of(r, avail)),
        'need': need,
        'planned': _jsnum(net),
        'seller': r.get('seller', '') or '',
        'source': r.get('last_company', '') or '',
        'last': _fmt_last(r),
        'usd': r.get('last_usd') or '',
        'date': r.get('last_date') or '',
        'rolled_usd': r.get('rolled_usd') or '',
        'scratch_usd': r.get('scratch_usd') or '',
        'est_usd': _jsnum(_est_usd(r, net, level)),
    }


def _server_combo(tree_groups):
    """_planCombos port: retained sums when present, else rolled sums.

    Retained (same cents as the supplier grand total) keeps the Excel
    Full Set identical to the screen cards; pre-rebuild payloads
    without retained values fall back to rolled_total_usd.
    """
    tot = {}
    for g in tree_groups or []:
        s = 0.0
        for it in g.get('items', []) or []:
            _r = it.get('retained_total_usd')
            if _r is None or _r == '':
                _r = it.get('rolled_total_usd')
            s += _fnum(_r)
        tot[g.get('key')] = s
    base = tot.get('base', 0) + tot.get('screws', 0)
    outdoor = tot.get('outdoor', 0)
    seat = tot.get('seat', 0)
    return {
        'full': _js_round(base + outdoor + seat),
        'outdoor': _js_round(base + outdoor),
        'seat': _js_round(base + seat),
    }


def _server_supplier(sup, fallback_name, kits=None, scratch=0):
    """Supplier payload for one slot, USD PO-value basis (v2).

    @param sup get_supplier_summary result (or None).
    """
    if not sup:
        return None
    out = _supsummary_v2(sup)
    if not out.get('plan_name'):
        out['plan_name'] = fallback_name
    if kits:
        out['kits'] = kits
    if scratch:
        out['scratch_total'] = scratch
    return out


class MatiaProcurementPlanController(http.Controller):

    @staticmethod
    def _live_cost():
        """Live Product Cost data for the optional Cost sheet.

        Top-level groups only (same writer as the Cost page export).
        """
        cost = request.env['matia.product.cost'].get_cost_tree() or {}
        return cost.get('combos') or {}, cost.get('groups') or []

    @staticmethod
    def _cost_suffix(data):
        return '_Cost' if data.get('withCost') else ''

    # Sheet order is always: Product Cost (if selected) first,
    # then Products, then Suppliers. Unselected sheets are skipped.
    COST_SHEET_NAME = 'Product Cost'
    PRODUCTS_SHEET_NAME = 'Combined Plan - Products'
    SUPPLIERS_SHEET_NAME = 'Combined Plan - Suppliers'
    SINGLE_PRODUCTS_SHEET_NAME = 'Plan - Products'
    SINGLE_SUPPLIERS_SHEET_NAME = 'Plan - Suppliers'

    def _append_cost_sheet(self, workbook, data):
        if not data.get('withCost'):
            return
        combos, groups = self._live_cost()
        ws = workbook.add_worksheet(self.COST_SHEET_NAME)
        write_cost_sheet(workbook, ws, combos, groups)

    def _prepend_cost_csv(self, lines, data):
        if not data.get('withCost'):
            return
        combos, groups = self._live_cost()
        new = cost_csv_lines(combos, groups)
        new.append('')
        new.extend(lines)
        lines[:] = new

    def _export_cost_only(self, data):
        """Cost sheet alone (popup: only Product Cost checked)."""
        if not xlsxwriter:
            combos, groups = self._live_cost()
            lines = cost_csv_lines(combos, groups)
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
        combos, groups = self._live_cost()
        ws = workbook.add_worksheet(self.COST_SHEET_NAME)
        write_cost_sheet(workbook, ws, combos, groups)
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
        if data.get('mode') == 'supplier':
            return self._export_supplier(data)
        if data.get('mode') == 'cost_slots':
            return self._export_cost_slots(data)
        if data.get('mode') == 'cost_only':
            return self._export_cost_only(data)
        groups = data.get('groups', [])
        total = data.get('total', 0)

        if not xlsxwriter:
            lines = _supplier_csv_lines(
                plan_name, groups, total, kits, scratch_total)
            self._prepend_cost_csv(lines, data)
            content = '\r\n'.join(lines).encode('utf-8')
            filename = 'Supplier_Preview%s_%s.csv' % (
                self._cost_suffix(data),
                datetime.now().strftime('%Y%m%d_%H%M'))
            return request.make_response(
                content,
                headers=[
                    ('Content-Type', 'text/csv; charset=utf-8'),
                    ('Content-Disposition',
                      'attachment; filename=%s' % filename),
                ])
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        self._append_cost_sheet(workbook, data)
        ws = workbook.add_worksheet('Supplier Preview')
        self._write_supplier_sheet(workbook, ws, {
            'plan_name': plan_name, 'groups': groups,
            'total': total, 'kits': kits,
            'scratch_total': scratch_total})
        workbook.close()
        output.seek(0)
        filename = 'Supplier_Preview%s_%s.xlsx' % (
            self._cost_suffix(data),
            datetime.now().strftime('%Y%m%d_%H%M'))
        return request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument'
                 '.spreadsheetml.sheet'),
                ('Content-Disposition',
                 'attachment; filename=%s' % filename),
            ])

    @classmethod
    def _write_supplier_sheet(cls, workbook, ws, sup):
        """Write one supplier breakdown table (shared by all modes).

        v2 payloads (USD PO-value, Suppliers-tab basis) use the new
        renderer; legacy payloads (plan-currency subtotals) keep the
        old renderer untouched.
        """
        if isinstance(sup, dict) and (sup.get('v') or 0) == 2:
            cls._write_supplier_sheet_v2(workbook, ws, sup)
        else:
            sup = sup or {}
            cls._write_supplier_sheet_legacy(
                workbook, ws, sup.get('plan_name', 'Plan'),
                sup.get('groups', []), sup.get('total', 0),
                sup.get('kits', []), sup.get('scratch_total', 0))

    @staticmethod
    def _write_supplier_sheet_legacy(workbook, ws, plan_name, groups,
                                     total, kits, scratch_total):
        """Legacy supplier table (plan-currency subtotals)."""
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

    @staticmethod
    def _write_supplier_sheet_v2(workbook, ws, sup):
        """Single-slot supplier table, USD PO-value basis (v2).

        Same figures as the Suppliers tab: per-(seller, buy-from
        company) groups, line PO value = own last-buy USD x order;
        unknown-route lines are listed but out of the cash total.
        """
        title_fmt = workbook.add_format({'bold': True, 'font_size': 14})
        info_fmt = workbook.add_format(
            {'font_size': 9, 'italic': True, 'font_color': '#64748b'})
        header_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#7c2d12', 'font_color': '#ffffff',
             'border': 1})
        group_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#fef3c7', 'border': 1})
        text_fmt = workbook.add_format({'border': 1})
        num_fmt = workbook.add_format({'border': 1, 'align': 'center'})
        money_fmt = workbook.add_format(
            {'border': 1, 'num_format': '"$"#,##0.00'})
        money_small_fmt = workbook.add_format(
            {'border': 1, 'num_format': '"$"#,##0.0000'})
        total_fmt = workbook.add_format({'bold': True, 'border': 1})
        total_money_fmt = workbook.add_format(
            {'bold': True, 'border': 1, 'num_format': '"$"#,##0.00'})
        total_small_fmt = workbook.add_format(
            {'bold': True, 'border': 1,
             'num_format': '"$"#,##0.0000'})
        headers = ['Supplier', 'Buy From', 'Code', 'Product', 'Order',
                   'Last Price', 'USD', 'Last Buy', 'Net Unit USD',
                   'Net Total USD', 'PO Total USD']
        _C = {name: idx for idx, name in enumerate(headers)}

        def _last2(itm):
            if not itm.get('last_price'):
                return ''
            cur = itm.get('last_currency') or ''
            try:
                p = '{:,.2f}'.format(float(itm.get('last_price') or 0))
            except (TypeError, ValueError):
                p = str(itm.get('last_price'))
            return ('%s %s' % (p, cur)).strip()

        row = 0
        ws.write(row, 0, 'Supplier Preview - %s (USD, PO-value)'
                 % (sup.get('plan_name', '') or 'Plan'), title_fmt)
        row += 1
        ws.write(row, 0, 'Total PO value: %s'
                 % _usd_text(sup.get('total')), info_fmt)
        row += 1
        if sup.get('unsourced_count'):
            ws.write(row, 0, '%d ordered line(s) have no supplier '
                     '(assign a seller first).'
                     % sup.get('unsourced_count'), info_fmt)
            row += 1
        if sup.get('unpriced_count'):
            ws.write(row, 0, '%d line(s) have no price '
                     '(counted as 0 USD).' % sup.get('unpriced_count'),
                     info_fmt)
            row += 1
        if sup.get('unknown_count'):
            ws.write(row, 0, '%d unknown-route line(s) listed below '
                     'but not in the total.' % sup.get('unknown_count'),
                     info_fmt)
            row += 1
        if sup.get('grand_rolled_usd'):
            ws.write(row, 0, 'Net gap value (info, not summed): %s'
                     % _usd_text(sup.get('grand_rolled_usd')), info_fmt)
            row += 1
        for kit in sup.get('kits', []) or []:
            ws.write(row, 0, 'Kit: %s (%s) - %s' % (
                kit.get('name', ''), kit.get('count', 0),
                kit.get('cost', 0)))
            row += 1
        row += 1
        header_row = row
        ws.write_row(header_row, 0, headers, header_fmt)
        row += 1
        widths = [len(h) for h in headers]

        def _bump(col, val):
            if val is None:
                return
            widths[col] = max(widths[col], len(str(val)))

        for grp in sup.get('groups', []) or []:
            title = grp.get('title', '') or ''
            company = grp.get('company', '') or ''
            ws.write(row, _C['Supplier'],
                     '%s (%s)' % (title, _usd_text(grp.get('cost'))),
                     group_fmt)
            ws.write(row, _C['Buy From'], company, group_fmt)
            for c in range(2, len(headers)):
                ws.write(row, c, '', group_fmt)
            _bump(_C['Supplier'], title)
            row += 1
            for itm in grp.get('items', []) or []:
                badges = ''
                if itm.get('no_seller'):
                    badges += ' [No supplier]'
                if (itm.get('route') or '') == 'unknown':
                    badges += ' [Unknown route]'
                if itm.get('no_price'):
                    badges += ' [No price]'
                name = '%s%s' % (itm.get('name', '') or '', badges)
                try:
                    qty = float(itm.get('order_qty') or 0)
                except (TypeError, ValueError):
                    qty = 0
                ws.write(row, _C['Supplier'], '', text_fmt)
                ws.write(row, _C['Buy From'], company, text_fmt)
                ws.write(row, _C['Code'], itm.get('code', ''), text_fmt)
                ws.write(row, _C['Product'], name, text_fmt)
                ws.write_number(row, _C['Order'], qty, num_fmt)
                ws.write(row, _C['Last Price'], _last2(itm), text_fmt)
                _write_usd(ws, row, _C['USD'], itm.get('last_usd'),
                           money_fmt, money_small_fmt, text_fmt,
                           small_under=0.005)
                ws.write(row, _C['Last Buy'], itm.get('last_date', ''),
                         text_fmt)
                _write_usd(ws, row, _C['Net Unit USD'],
                           itm.get('rolled_usd'),
                           money_fmt, money_small_fmt, text_fmt,
                           small_under=0.005)
                _write_usd(ws, row, _C['Net Total USD'],
                           itm.get('rolled_total_usd'),
                           money_fmt, money_small_fmt, text_fmt,
                           small_under=0.005)
                _write_usd(ws, row, _C['PO Total USD'],
                           itm.get('total_usd'),
                           money_fmt, money_small_fmt, text_fmt,
                           small_under=0.005)
                _bump(_C['Buy From'], company)
                _bump(_C['Code'], itm.get('code', ''))
                _bump(_C['Product'], name)
                _bump(_C['Last Price'], _last2(itm))
                _bump(_C['Last Buy'], itm.get('last_date', ''))
                row += 1
        last_row = row - 1
        ws.write(row, _C['Supplier'], 'TOTAL', total_fmt)
        ws.write(row, _C['Buy From'], '', total_fmt)
        for c in range(2, _C['PO Total USD']):
            ws.write(row, c, '', total_fmt)
        _write_usd(ws, row, _C['PO Total USD'], sup.get('total'),
                   total_money_fmt, total_small_fmt, total_fmt)
        caps = [40, 12, 16, 60, 12, 16, 14, 14, 16, 16, 16]
        for idx, (w, cap) in enumerate(zip(widths, caps)):
            ws.set_column(idx, idx, min(w + 2, cap))
        if last_row > header_row:
            ws.autofilter(header_row, 0, last_row, len(headers) - 1)
        ws.freeze_panes(header_row + 1, 0)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)

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
            if (sup.get('v') or 0) == 2:
                _sup = dict(sup)
                _sup.setdefault('plan_name', plan_name)
                _sup.setdefault('kits', sup_kits)
                _sup.setdefault('scratch_total', sup_scratch)
                lines.extend(_supplier_csv_lines_v2(_sup))
            else:
                lines.extend(_supplier_csv_lines(
                    sup.get('plan_name', plan_name), groups, total,
                    sup_kits, sup_scratch))
            self._prepend_cost_csv(lines, data)
            content = '\r\n'.join(lines).encode('utf-8')
            filename = 'Plan_Supplier%s_%s.csv' % (
                self._cost_suffix(data),
                datetime.now().strftime('%Y%m%d_%H%M'))
            return request.make_response(
                content,
                headers=[
                    ('Content-Type', 'text/csv; charset=utf-8'),
                    ('Content-Disposition',
                      'attachment; filename=%s' % filename),
                ])
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        self._append_cost_sheet(workbook, data)
        ws = workbook.add_worksheet(
            self.SINGLE_PRODUCTS_SHEET_NAME)
        self._write_plan_sheet(workbook, ws, plan_name, scratch_total,
                               rows, combo)
        ws2 = workbook.add_worksheet(
            self.SINGLE_SUPPLIERS_SHEET_NAME)
        if (sup.get('v') or 0) == 2:
            _sup = dict(sup)
            _sup.setdefault('plan_name', plan_name)
            _sup.setdefault('kits', sup_kits)
            _sup.setdefault('scratch_total', sup_scratch)
        else:
            _sup = {'plan_name': sup.get('plan_name', plan_name),
                    'groups': groups, 'total': total,
                    'kits': sup_kits, 'scratch_total': sup_scratch}
        self._write_supplier_sheet(workbook, ws2, _sup)
        workbook.close()
        output.seek(0)
        filename = 'Plan_Supplier%s_%s.xlsx' % (
            self._cost_suffix(data),
            datetime.now().strftime('%Y%m%d_%H%M'))
        return request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument'
                 '.spreadsheetml.sheet'),
                ('Content-Disposition',
                 'attachment; filename=%s' % filename),
            ])

    def _export_supplier(self, data):
        """Supplier-only export, v2 USD basis (popup: supplier on,
        no slot picked)."""
        sup = data.get('supplier') or {}
        if not xlsxwriter:
            lines = _supplier_csv_lines_v2(sup)
            self._prepend_cost_csv(lines, data)
            content = '\r\n'.join(lines).encode('utf-8')
            filename = 'Supplier_Preview%s_%s.csv' % (
                self._cost_suffix(data),
                datetime.now().strftime('%Y%m%d_%H%M'))
            return request.make_response(
                content,
                headers=[
                    ('Content-Type', 'text/csv; charset=utf-8'),
                    ('Content-Disposition',
                     'attachment; filename=%s' % filename),
                ])
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        self._append_cost_sheet(workbook, data)
        ws = workbook.add_worksheet('Supplier Preview')
        self._write_supplier_sheet(workbook, ws, sup)
        workbook.close()
        output.seek(0)
        filename = 'Supplier_Preview%s_%s.xlsx' % (
            self._cost_suffix(data),
            datetime.now().strftime('%Y%m%d_%H%M'))
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
            lines = _plan_csv_lines(
                plan_name, scratch_total, rows, combo)
            self._prepend_cost_csv(lines, data)
            content = '\r\n'.join(lines).encode('utf-8')
            filename = 'Plan%s_%s.csv' % (
                self._cost_suffix(data),
                datetime.now().strftime('%Y%m%d_%H%M'))
            return request.make_response(
                content,
                headers=[
                    ('Content-Type', 'text/csv; charset=utf-8'),
                    ('Content-Disposition',
                      'attachment; filename=%s' % filename),
                ])
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        self._append_cost_sheet(workbook, data)
        ws = workbook.add_worksheet(
            self.SINGLE_PRODUCTS_SHEET_NAME)
        self._write_plan_sheet(workbook, ws, plan_name, scratch_total,
                               rows, combo)
        workbook.close()
        output.seek(0)
        filename = 'Plan%s_%s.xlsx' % (
            self._cost_suffix(data),
            datetime.now().strftime('%Y%m%d_%H%M'))
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
        money_small_fmt = workbook.add_format(
            {'border': 1, 'num_format': '"$"#,##0.0000'})
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
        child_money_small_fmt = workbook.add_format(
            {'border': 1, 'bg_color': '#FFFBEB',
             'font_color': '#808080', 'num_format': '"$"#,##0.0000'})
        total_fmt = workbook.add_format({'bold': True, 'border': 1})
        total_money_fmt = workbook.add_format(
            {'bold': True, 'border': 1, 'num_format': '"$"#,##0.00'})
        total_small_fmt = workbook.add_format(
            {'bold': True, 'border': 1,
             'num_format': '"$"#,##0.0000'})

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
                if lvl:
                    _write_usd(ws, row, _C[col], r.get(key),
                               child_money_gray_fmt,
                               child_money_small_fmt, child_fmt,
                               small_under=0.005)
                else:
                    _write_usd(ws, row, _C[col], r.get(key),
                               money_fmt, money_small_fmt, text_fmt,
                               small_under=0.005)
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
        _write_usd(ws, row, _C['Est. USD'], sum_est,
                   total_money_fmt, total_small_fmt, total_fmt,
                   small_under=0.005)
        last_row = row - 1
        # Auto widths (measured, capped), filter, freeze, print.
        for idx, h in enumerate(headers):
            ws.set_column(idx, idx, min(widths[idx] + 2, caps[h]))
        if last_row > header_row:
            ws.autofilter(header_row, 0, last_row, len(headers) - 1)
        ws.freeze_panes(header_row + 1, 0)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)

    @staticmethod
    def _parse_slot_plans(raw):
        """Normalize client-posted slot dicts (slot/name/combo/rows)."""
        plans = []
        seen = set()
        for p in (raw or [])[:10]:
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
        return plans

    def _export_slots(self, data):
        plans = self._parse_slot_plans(data.get('plans', []))
        return self._export_slots_from_plans(plans, data)

    def _export_cost_slots(self, data):
        """Cost-page export: collect slots server-side, reuse writers.

        The Cost page holds no plan state, so rows/combos/suppliers
        are rebuilt here (_mpp_slot_plan + get_tree_with_cost +
        get_full_tree with the same mapping as _collectExportRows).
        Single slot delegates to the tree/plan_supplier writers,
        several slots to the combined matrix. Tops use the default
        Planned-desc order (the Cost page has no sort state).
        """
        raw = data.get('slots', []) or []
        slots = []
        for s in raw:
            try:
                s = int(s)
            except (TypeError, ValueError):
                continue
            if 0 <= s <= 9 and s not in slots:
                slots.append(s)
        slots = slots[:10]
        if not slots:
            return request.not_found()
        with_supplier = bool(data.get('withSupplier'))
        Plan = request.env['matia.procurement.plan']
        company_ids = request.env['res.company'].with_context(
            active_test=False).sudo().search([]).ids
        env_sudo = Plan.with_context(
            allowed_company_ids=company_ids,
            active_test=False).sudo().env
        plans = []
        for s in slots:
            plan = Plan._mpp_slot_plan(env_sudo, s)
            if not plan or not plan.exists():
                continue
            res = Plan.get_tree_with_cost(
                plan.id, force=False) or {}
            groups = res.get('tree_groups') or []
            targets = res.get('targets') or {}
            tops = []
            for g in groups:
                gkey = g.get('key', '')
                title = g.get('title', '')
                for it in g.get('items', []) or []:
                    tops.append((gkey, title, it))
            # Default treeSort (planned/-1), stable over code order.
            tops.sort(key=lambda t: _row_net(t[2]), reverse=True)
            top_nets = {}
            rows = []
            infos = []
            for gkey, title, it in tops:
                row = _port_row(it, title, 0, targets, gkey)
                rows.append(row)
                infos.append((gkey, title, row))
                top_nets['%s:%s' % (gkey, it.get('product_id'))] = \
                    _row_net(it)
            full = Plan.get_full_tree(plan.id, top_nets) or {}
            trees = full.get('trees') or {}

            def _walk(uid, level, group_title, group_key, out):
                for ch in trees.get(uid, []) or []:
                    out.append(_port_row(
                        ch, group_title, level, targets, group_key))
                    pid = ch.get('product_id')
                    cu = '%s%s' % (uid, pid) if uid.endswith(':') \
                        else '%s/%s' % (uid, pid)
                    _walk(cu, level + 1, group_title, group_key, out)

            for gkey, title, row in infos:
                uid = '%s:%s' % (gkey, row.get('pid'))
                _walk(uid, 1, title, gkey, rows)
            name = (plan.note or '').strip() or res.get('name') \
                or plan.name
            combo = _server_combo(groups)
            kits = res.get('kits', []) or []
            scratch = res.get('scratch_total_usd', 0)
            sup2 = None
            if with_supplier:
                try:
                    sup2 = _server_supplier(
                        Plan.get_supplier_summary(plan.id),
                        name, kits, scratch)
                except Exception as exc:
                    _logger.warning(
                        'Combined export: supplier summary failed '
                        'for plan %s (slot %s), continuing without '
                        'the Suppliers sheet: %s', plan.id, s, exc)
                    sup2 = None
            plans.append({
                'slot': s,
                'name': name,
                'combo': combo,
                'scratch_total': scratch,
                'rows': rows,
                'kits': kits,
                'supplier': sup2,
            })
        if not plans:
            return request.not_found()
        if len(plans) == 1:
            p = plans[0]
            single = {
                'tree_rows': p['rows'],
                'combo': p['combo'],
                'withCost': data.get('withCost'),
            }
            if p.get('supplier'):
                single['plan_name'] = p['name']
                single['kits'] = p['kits']
                single['scratch_total'] = p['scratch_total']
                single['supplier'] = p['supplier']
                return self._export_plan_supplier(single)
            return self._export_tree(
                single, p['name'], p['kits'], p['scratch_total'])
        return self._export_slots_from_plans(
            plans, {'withCost': data.get('withCost')})

    def _export_slots_from_plans(self, plans, data):
        """Combined matrix from normalized plans (client or server)."""
        # Canonical rows from the first slot, re-sorted into the
        # canonical group order (Base > Outdoor > Seat, Screws last
        # inside Base); per-slot overlays are sorted the same way so
        # the (group, pid-or-code, level, occurrence) keys stay
        # aligned even when clients post another order.
        def _mbase_key(r):
            pid = r.get('pid')
            if pid is None:
                pid = r.get('code', '')
            return (_row_group_key(r), pid, int(r.get('level') or 0))

        def _level0_sorted(rows):
            out = [r for r in rows
                   if not r.get('is_header')
                   and int(r.get('level') or 0) == 0]
            out.sort(key=_canon_sort_key)
            return out

        def _overlay(rows):
            d = {}
            seen = {}
            for r in _level0_sorted(rows):
                k = _mbase_key(r)
                seen[k] = seen.get(k, 0) + 1
                d[k + (seen[k],)] = r
            return d

        canon = _level0_sorted(plans[0]['rows'])
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
            m_est = [0.0] * len(plans)

            def _m_csv_subtotal(disp, acc):
                cells = ['%s SUBTOTAL' % disp, '', '', '', '']
                for v in acc:
                    cells.append(_usd_csv(v))
                lines.append(';'.join(cells))

            cur = None
            acc = [0.0] * len(plans)
            for ck, r in zip(canon_keys, canon):
                disp = _display_group(r)
                if cur is None:
                    cur = disp
                if disp != cur:
                    _m_csv_subtotal(cur, acc)
                    cur = disp
                    acc = [0.0] * len(plans)
                cells = [disp,
                         str(r.get('code', '')),
                         str(r.get('name', '')),
                         '%s %s' % (r.get('bom_qty', ''),
                                    r.get('uom', '')),
                         _usd_csv(r.get('scratch_usd'))]
                for i, ov in enumerate(overlays):
                    o = ov.get(ck)
                    if o is None:
                        cells.append('')
                        continue
                    try:
                        est = float(o.get('est_usd') or 0)
                    except (TypeError, ValueError):
                        est = 0.0
                    cells.append(_usd_csv(est))
                    m_est[i] += est
                    acc[i] += est
                lines.append(';'.join(cells))
            if cur is not None:
                _m_csv_subtotal(cur, acc)
            total = ['TOTAL', '', '', '', '']
            for v in m_est:
                total.append(_usd_csv(v))
            lines.append(';'.join(total))
            if with_supplier:
                locs, blocks, present = _combined_supplier_table(
                    plans)
                lines.append('')
                lines.append('Suppliers (USD)')
                lines.append(';'.join(
                    ['Supplier', 'Buy From'] + slot_titles))
                s_est = [0.0] * len(plans)
                for loc in locs:
                    b_est = [0.0] * len(plans)
                    for name in sorted(blocks[loc],
                                       key=lambda t: t.lower()):
                        arr = blocks[loc][name]
                        cells = [name, loc or '—']
                        for i in range(len(plans)):
                            if (name, loc, i) in present:
                                try:
                                    v = float(arr[i] or 0)
                                except (TypeError, ValueError):
                                    v = 0.0
                                cells.append(_usd_csv(v))
                                b_est[i] += v
                                s_est[i] += v
                            else:
                                cells.append('')
                        lines.append(';'.join(cells))
                    slab = ['%s SUBTOTAL' % (loc or '—'), '']
                    for v in b_est:
                        slab.append(_usd_csv(v))
                    lines.append(';'.join(slab))
                stotal = ['TOTAL', '']
                for v in s_est:
                    stotal.append(_usd_csv(v))
                lines.append(';'.join(stotal))
            self._prepend_cost_csv(lines, data)
            content = '\r\n'.join(lines).encode('utf-8')
            filename = 'Plan_Combined%s_%s.csv' % (
                self._cost_suffix(data),
                datetime.now().strftime('%Y%m%d_%H%M'))
            return request.make_response(
                content,
                headers=[
                    ('Content-Type', 'text/csv; charset=utf-8'),
                    ('Content-Disposition',
                     'attachment; filename=%s' % filename),
                ])
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        self._append_cost_sheet(workbook, data)
        title_fmt = workbook.add_format({'bold': True, 'font_size': 14})
        header_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#7c2d12', 'font_color': '#ffffff',
             'border': 1})
        text_fmt = workbook.add_format({'border': 1})
        # Combined money is whole-USD, except sub-$1 values, which
        # print with decimals (2, or 4 below $0.005 so no $0 shows).
        money_fmt = workbook.add_format(
            {'border': 1, 'num_format': '"$"#,##0'})
        money_small_fmt = workbook.add_format(
            {'border': 1, 'num_format': '"$"#,##0.00'})
        money_tiny_fmt = workbook.add_format(
            {'border': 1, 'num_format': '"$"#,##0.0000'})
        total_fmt = workbook.add_format({'bold': True, 'border': 1})
        total_money_fmt = workbook.add_format(
            {'bold': True, 'border': 1, 'num_format': '"$"#,##0'})
        # Combined matrix sheet: fixed base columns plus one Est. USD
        # column per slot (slot description as header, slot pastel).
        mC = {name: idx for idx, name in enumerate(mheaders)}
        ws = workbook.add_worksheet(self.PRODUCTS_SHEET_NAME)
        slot_fmts = []
        for p in plans:
            color = SLOT_COLORS[p['slot'] % len(SLOT_COLORS)]
            slot_fmts.append({
                'text': workbook.add_format(
                    {'border': 1, 'bg_color': color}),
                'money': workbook.add_format(
                    {'border': 1, 'bg_color': color,
                     'num_format': '"$"#,##0'}),
                'small': workbook.add_format(
                    {'border': 1, 'bg_color': color,
                     'num_format': '"$"#,##0.00'}),
                'tiny': workbook.add_format(
                    {'border': 1, 'bg_color': color,
                     'num_format': '"$"#,##0.0000'}),
                'small_total': workbook.add_format(
                    {'bold': True, 'border': 1, 'bg_color': color,
                     'num_format': '"$"#,##0.00'}),
                'tiny_total': workbook.add_format(
                    {'bold': True, 'border': 1, 'bg_color': color,
                     'num_format': '"$"#,##0.0000'}),
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

        ws.write(0, 0, 'Combined Plan - Products (USD)', title_fmt)
        hrow = 2
        ws.write_row(hrow, 0, mheaders, header_fmt)
        for i, title in enumerate(slot_titles):
            ws.write(hrow, len(mbase) + i, title,
                     slot_fmts[i]['header'])
        m_est = [0.0] * len(plans)
        r = hrow + 1
        # Group blocks in canonical order (Screws already merged into
        # Base by the sort); each block closes with a static SUBTOTAL.
        mblocks = {}
        for ck, row in zip(canon_keys, canon):
            mblocks.setdefault(
                _display_group(row), []).append((ck, row))
        for disp, members in mblocks.items():
            acc = [0.0] * len(plans)
            for ck, row in members:
                code = str(row.get('code', ''))
                name = str(row.get('name', ''))
                usage = '%s %s' % (row.get('bom_qty', ''),
                                   row.get('uom', ''))
                ws.write(r, mC['Group'], disp, text_fmt)
                ws.write(r, mC['Part Code'], code, text_fmt)
                ws.write(r, mC['Part Name'], name, text_fmt)
                ws.write(r, mC['Usage'], usage, text_fmt)
                _write_usd(ws, r, mC['Unit Cost'],
                           row.get('scratch_usd'),
                           money_fmt, money_small_fmt, text_fmt,
                           fmt_tiny=money_tiny_fmt)
                _mbump(mC['Group'], disp)
                _mbump(mC['Part Code'], code)
                _mbump(mC['Part Name'], name)
                _mbump(mC['Usage'], usage)
                _mbump(mC['Unit Cost'],
                       '$' + (_usd_csv(row.get('scratch_usd')) or ''))
                for i, ov in enumerate(overlays):
                    f = slot_fmts[i]
                    o = ov.get(ck)
                    est_col = len(mbase) + i
                    if o is None:
                        ws.write(r, est_col, '', f['text'])
                        continue
                    try:
                        est = float(o.get('est_usd') or 0)
                    except (TypeError, ValueError):
                        est = 0.0
                    _write_usd(ws, r, est_col, est,
                               f['money'], f['small'], f['text'],
                               fmt_tiny=f['tiny'])
                    m_est[i] += est
                    acc[i] += est
                    _mbump(est_col, '$' + (_usd_csv(est) or ''))
                r += 1
            slab = '%s SUBTOTAL' % disp
            ws.write(r, mC['Group'], slab, total_fmt)
            ws.write(r, mC['Part Code'], '', total_fmt)
            ws.write(r, mC['Part Name'], '', total_fmt)
            ws.write(r, mC['Usage'], '', total_fmt)
            ws.write(r, mC['Unit Cost'], '', total_fmt)
            for i in range(len(plans)):
                _write_usd(ws, r, len(mbase) + i, acc[i],
                           slot_fmts[i]['total'],
                           slot_fmts[i]['small_total'],
                           slot_fmts[i]['text'],
                           fmt_tiny=slot_fmts[i]['tiny_total'])
            _mbump(mC['Group'], slab)
            r += 1
        # TOTAL row: per-slot Est. USD only (level-0 sums, static);
        # kept out of the filter.
        ws.write(r, mC['Group'], 'TOTAL', total_fmt)
        ws.write(r, mC['Part Code'], '', total_fmt)
        ws.write(r, mC['Part Name'], '', total_fmt)
        ws.write(r, mC['Usage'], '', total_fmt)
        ws.write(r, mC['Unit Cost'], '', total_fmt)
        for i in range(len(plans)):
            _write_usd(ws, r, len(mbase) + i, m_est[i],
                       slot_fmts[i]['total'],
                       slot_fmts[i]['small_total'],
                       slot_fmts[i]['text'],
                       fmt_tiny=slot_fmts[i]['tiny_total'])
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
            sheaders = ['Supplier', 'Buy From'] + slot_titles
            ws2 = workbook.add_worksheet(self.SUPPLIERS_SHEET_NAME)
            ws2.write(0, 0, 'Combined Plan - Suppliers (USD)',
                      title_fmt)
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

            s_est = [0.0] * len(plans)
            r2 = shrow + 1
            for loc in locs:
                b_est = [0.0] * len(plans)
                for name in sorted(blocks[loc],
                                   key=lambda t: t.lower()):
                    arr = blocks[loc][name]
                    ws2.write(r2, 0, name, text_fmt)
                    ws2.write(r2, 1, loc or '—', text_fmt)
                    _sbump(0, name)
                    _sbump(1, loc or '—')
                    for i in range(len(plans)):
                        scol = 2 + i
                        if (name, loc, i) in present:
                            try:
                                est = float(arr[i] or 0)
                            except (TypeError, ValueError):
                                est = 0.0
                            _write_usd(ws2, r2, scol, est,
                                       slot_fmts[i]['money'],
                                       slot_fmts[i]['small'],
                                       slot_fmts[i]['text'],
                                       fmt_tiny=slot_fmts[i]['tiny'])
                            b_est[i] += est
                            s_est[i] += est
                            _sbump(scol,
                                   '$' + (_usd_csv(est) or ''))
                        else:
                            ws2.write(r2, scol, '',
                                      slot_fmts[i]['text'])
                    r2 += 1
                slab = '%s SUBTOTAL' % (loc or '—')
                ws2.write(r2, 0, slab, total_fmt)
                ws2.write(r2, 1, '', total_fmt)
                for i in range(len(plans)):
                    _write_usd(ws2, r2, 2 + i, b_est[i],
                               slot_fmts[i]['total'],
                               slot_fmts[i]['small_total'],
                               slot_fmts[i]['text'],
                               fmt_tiny=slot_fmts[i]['tiny_total'])
                _sbump(0, slab)
                r2 += 1
            # Grand TOTAL, kept out of the filter.
            ws2.write(r2, 0, 'TOTAL', total_fmt)
            ws2.write(r2, 1, '', total_fmt)
            for i in range(len(plans)):
                _write_usd(ws2, r2, 2 + i, s_est[i],
                           slot_fmts[i]['total'],
                           slot_fmts[i]['small_total'],
                           slot_fmts[i]['text'],
                           fmt_tiny=slot_fmts[i]['tiny_total'])
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
        filename = '%s%s_%s.xlsx' % (
            prefix, self._cost_suffix(data),
            datetime.now().strftime('%Y%m%d_%H%M'))
        return request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument'
                 '.spreadsheetml.sheet'),
                ('Content-Disposition',
                 'attachment; filename=%s' % filename),
            ])
