# -*- coding: utf-8 -*-
"""Shared Device Capacity sheet writer (Capacity + combined exports).

The Capacity page export (controllers/main.py) and the combined popup
export (controllers/procurement_export.py) write the SAME capacity
table through these two helpers, so the screen-mirror file and the
appended 'Device Capacity' sheet can never drift apart.

Pure stdlib + xlsxwriter only (no odoo import): unit-testable with a
fake workbook. Callers own the worksheet name, the title string and
the HTTP response; only the table layout lives here.

Cell shape (mirrors stock_planning.js _buildExportCells):
    headers: list of column titles.
    groups: [{key, title, items: [{cells: [{val, type}], is_sub, level}]}]
    type is one of 'ok' | 'need' | 'number' | 'text'.
"""
from datetime import datetime


CAPACITY_TITLE = 'Matia TekRMD Device Stock & Capacity Plan'


def capacity_csv_lines(headers, groups, filter_info='',
                       title=CAPACITY_TITLE):
    """CSV fallback lines for one capacity table (mirrors the xlsx).

    @param headers: column titles.
    @param groups: writer-shape groups (see module docstring).
    @param filter_info: location/capacity note for the title line.
    @param title: report title line prefix.
    @return: list of text lines (first carries the UTF-8 BOM).
    """
    lines = ['\ufeff' + '%s - %s' % (title, filter_info or '')]
    lines.append(';'.join(headers or []))
    for grp in groups or []:
        lines.append('--- %s ---' % grp.get('title', ''))
        for itm in grp.get('items', []):
            vals = [str(c.get('val', '')) for c in itm.get('cells', [])]
            lines.append(';'.join(vals))
    return lines


def write_capacity_sheet(workbook, ws, headers, groups, filter_info='',
                         title=CAPACITY_TITLE, now=None):
    """Write one full capacity table (title + grid + group blocks).

    Byte-for-byte the former controllers/main.py export body: group
    colors, OK/need/number/text cell types, per-level sub-BOM shades
    (level 1-8; level 0 = main rows).

    @param workbook: xlsxwriter Workbook.
    @param ws: target worksheet (caller names it).
    @param headers: column titles.
    @param groups: writer-shape groups (see module docstring).
    @param filter_info: location/capacity note under the title.
    @param title: report title (first row).
    @param now: datetime override (tests); defaults to now.
    @return: None.
    """
    ws.hide_gridlines(False)

    # Styles
    title_format = workbook.add_format({
        'bold': True,
        'font_size': 14,
        'font_color': '#1e293b',
        'align': 'left',
        'valign': 'vcenter',
    })
    info_format = workbook.add_format({
        'font_size': 9,
        'italic': True,
        'font_color': '#64748b',
        'align': 'left',
        'valign': 'vcenter',
    })
    header_format = workbook.add_format({
        'bold': True,
        'font_color': '#ffffff',
        'bg_color': '#1e293b',
        'border': 1,
        'border_color': '#334155',
        'align': 'center',
        'valign': 'vcenter',
        'text_wrap': True,
    })
    group_base_format = workbook.add_format({
        'bold': True,
        'font_color': '#1e40af',
        'bg_color': '#dbeafe',
        'border': 1,
        'border_color': '#bfdbfe',
        'valign': 'vcenter',
    })
    group_outdoor_format = workbook.add_format({
        'bold': True,
        'font_color': '#065f46',
        'bg_color': '#d1fae5',
        'border': 1,
        'border_color': '#a7f3d0',
        'valign': 'vcenter',
    })
    group_seat_format = workbook.add_format({
        'bold': True,
        'font_color': '#854d0e',
        'bg_color': '#fef3c7',
        'border': 1,
        'border_color': '#fde68a',
        'valign': 'vcenter',
    })
    group_screws_format = workbook.add_format({
        'bold': True,
        'font_color': '#334155',
        'bg_color': '#f1f5f9',
        'border': 1,
        'border_color': '#cbd5e1',
        'valign': 'vcenter',
    })
    cell_text_format = workbook.add_format({
        'border': 1,
        'border_color': '#e2e8f0',
        'align': 'left',
        'valign': 'vcenter',
    })
    cell_num_format = workbook.add_format({
        'border': 1,
        'border_color': '#e2e8f0',
        'align': 'center',
        'valign': 'vcenter',
    })
    cell_ok_format = workbook.add_format({
        'bold': True,
        'font_color': '#15803d',
        'bg_color': '#dcfce7',
        'border': 1,
        'border_color': '#86efac',
        'align': 'center',
        'valign': 'vcenter',
    })
    cell_need_format = workbook.add_format({
        'bold': True,
        'font_color': '#b91c1c',
        'bg_color': '#fee2e2',
        'border': 1,
        'border_color': '#fca5a5',
        'align': 'center',
        'valign': 'vcenter',
    })
    # Per-level sub-BOM formats (match page colors L1-L8).
    # Level 0 = main rows.
    sub_level_bg = {
        1: '#f0f9ff',
        2: '#faf5ff',
        3: '#ecfdf5',
        4: '#fff7ed',
        5: '#fdf2f8',
        6: '#fefce8',
        7: '#ecfeff',
        8: '#f1f5f9',
    }
    sub_text_by_level = {}
    sub_num_by_level = {}
    for lvl in range(1, 9):
        sub_text_by_level[lvl] = workbook.add_format({
            'border': 1,
            'border_color': '#e2e8f0',
            'bg_color': sub_level_bg[lvl],
            'align': 'left',
            'valign': 'vcenter',
            'font_size': 9,
        })
        sub_num_by_level[lvl] = workbook.add_format({
            'border': 1,
            'border_color': '#e2e8f0',
            'bg_color': sub_level_bg[lvl],
            'align': 'center',
            'valign': 'vcenter',
            'font_size': 9,
        })

    # Header Title and Date
    now = now or datetime.now()
    row = 0
    ws.write(row, 0, title, title_format)
    row += 1
    now_str = now.strftime('%Y-%m-%d %H:%M')
    ws.write(row, 0, 'Report Date: %s | Filter: %s' % (
        now_str, filter_info or ''), info_format)
    row += 2

    # Column Headers
    ws.set_row(row, 28)
    col_widths = [15] * len(headers)
    for col_idx, h in enumerate(headers):
        ws.write(row, col_idx, h, header_format)
        if len(h) + 4 > col_widths[col_idx]:
            col_widths[col_idx] = len(h) + 4
    row += 1

    # Groups and Items
    for grp in groups:
        grp_key = grp.get('key', '')
        grp_title = grp.get('title', 'Group')
        items = grp.get('items', [])

        if grp_key == 'outdoor':
            g_fmt = group_outdoor_format
        elif grp_key == 'seat':
            g_fmt = group_seat_format
        elif grp_key == 'screws':
            g_fmt = group_screws_format
        else:
            g_fmt = group_base_format

        ws.set_row(row, 24)
        ws.merge_range(row, 0, row, len(headers) - 1,
                       '  %s (%s Parts)' % (grp_title, len(items)),
                       g_fmt)
        row += 1

        for itm in items:
            ws.set_row(row, 20)
            cells = itm.get('cells', [])
            try:
                lvl = int(itm.get('level') or 0)
            except (TypeError, ValueError):
                lvl = 0
            if lvl < 1 or lvl > 8:
                lvl = 8 if itm.get('is_sub') else 0

            for col_idx, cell in enumerate(cells):
                val = cell.get('val', '')
                c_type = cell.get('type', 'text')

                if c_type == 'ok':
                    ws.write(row, col_idx, 'OK', cell_ok_format)
                elif c_type == 'need':
                    need_val = 0
                    try:
                        need_val = int(val) if val not in [
                            False, None, ''] else 0
                    except (TypeError, ValueError):
                        need_val = 0
                    ws.write(row, col_idx, need_val, cell_need_format)
                elif c_type == 'number':
                    num_val = 0
                    try:
                        if val not in [False, None, '']:
                            num_val = float(val)
                            if num_val.is_integer():
                                num_val = int(num_val)
                        else:
                            num_val = 0
                    except (TypeError, ValueError):
                        num_val = 0
                    fmt = sub_num_by_level[lvl] if lvl else cell_num_format
                    ws.write(row, col_idx, num_val, fmt)
                else:
                    text_val = '' if val in [False, None] else str(val)
                    fmt = sub_text_by_level[lvl] if lvl else cell_text_format
                    ws.write(row, col_idx, text_val, fmt)

                val_str = str(val if val not in [False, None] else (
                    0 if c_type == 'number' else ''))
                if len(val_str) + 3 > col_widths[col_idx]:
                    col_widths[col_idx] = min(len(val_str) + 3, 50)
            row += 1

    for col_idx, w in enumerate(col_widths):
        ws.set_column(col_idx, col_idx, w)
