# -*- coding: utf-8 -*-
"""Printable TR/US stock-count sheets (Count List buttons).

Two read-only routes per company behind the backend login
(auth='user', same exposure as the existing export routes):

- GET /matia_stock_planning/count_sheet/<tr|us>:
  printable HTML page with 4 scope tabs (tekrmd / other / ncr /
  spare) plus Print + Excel buttons (Excel follows the active tab).
- GET /matia_stock_planning/count_sheet/<tr|us>/xlsx[/<scope>]:
  .xlsx download of one scope list (default tekrmd; UTF-8 BOM CSV
  fallback without xlsxwriter).

Data comes from matia.stock.planning.get_count_sheet; this module only
owns the HTTP responses and filenames.
"""
import io
from datetime import datetime

from odoo import http
from odoo.http import request

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class MatiaCountSheetController(http.Controller):

    @http.route('/matia_stock_planning/count_sheet/<string:company>',
                type='http', auth='user', methods=['GET'])
    def count_sheet_page(self, company, **kwargs):
        """Render the printable count sheet page.

        @param company: 'tr' or 'us' (anything else -> 404).
        """
        if (company or '').strip().lower() not in ('tr', 'us'):
            return request.not_found()
        sheet = request.env['matia.stock.planning'].get_count_sheet(
            company)
        return request.render(
            'matia_stock_planning.count_sheet_page', {'sheet': sheet})

    @http.route(['/matia_stock_planning/count_sheet/<string:company>/xlsx',
                 '/matia_stock_planning/count_sheet/<string:company>/xlsx/<string:scope>'],
                type='http', auth='user', methods=['GET'])
    def count_sheet_xlsx(self, company, scope='tekrmd', **kwargs):
        """Download one scope list as .xlsx (or CSV fallback).

        @param company: 'tr' or 'us' (anything else -> 404).
        @param scope: 'tekrmd', 'other', 'ncr' or 'spare' (else 404).
        """
        if (company or '').strip().lower() not in ('tr', 'us'):
            return request.not_found()
        scope = (scope or '').strip().lower()
        if scope not in ('tekrmd', 'other', 'ncr', 'spare'):
            return request.not_found()
        sheet = request.env['matia.stock.planning'].get_count_sheet(
            company)
        target = None
        for lst in sheet.get('lists', []) or []:
            if lst.get('key') == scope:
                target = lst
                break
        if target is None:
            return request.not_found()
        show_type = bool(target.get('show_type'))
        headers = target.get('headers', [])
        rows = target.get('rows', []) or []
        title = '%s - %s' % (sheet.get('title', ''),
                             target.get('title', ''))
        stamp = datetime.now().strftime('%Y%m%d_%H%M')
        file_base = '%s_%s' % (sheet.get('file_base') or 'Count_List',
                               scope)

        def _cells(row, loc_join=' / '):
            """Row cells in header order (No excluded)."""
            cells = [row.get('code') or '', row.get('name') or '']
            if show_type:
                cells.append(row.get('type_label') or '')
            cells.extend([loc_join.join(row.get('locs') or []),
                          row.get('qty_text') or '',
                          row.get('lots') or ''])
            return cells

        if not xlsxwriter:
            lines = ['\ufeff' + '%s - %s' % (title, sheet.get(
                'generated', ''))]
            lines.append(';'.join(['No'] + list(headers)))
            for row in rows:
                lines.append(';'.join(
                    [str(row.get('no', ''))] + _cells(row)))
            content = '\r\n'.join(lines).encode('utf-8')
            return request.make_response(
                content,
                headers=[
                    ('Content-Type', 'text/csv; charset=utf-8'),
                    ('Content-Disposition',
                     'attachment; filename=%s_%s.csv' % (
                         file_base, stamp)),
                ]
            )

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = workbook.add_worksheet('Count List')
        title_fmt = workbook.add_format({
            'bold': True, 'font_size': 14, 'font_color': '#1e293b'})
        info_fmt = workbook.add_format({
            'font_size': 9, 'italic': True, 'font_color': '#64748b'})
        header_fmt = workbook.add_format({
            'bold': True, 'font_color': '#ffffff', 'bg_color': '#1e293b',
            'border': 1, 'border_color': '#334155',
            'align': 'center', 'valign': 'vcenter', 'text_wrap': True})
        text_fmt = workbook.add_format({
            'border': 1, 'border_color': '#e2e8f0', 'valign': 'vcenter',
            'text_wrap': True})
        num_fmt = workbook.add_format({
            'border': 1, 'border_color': '#e2e8f0', 'valign': 'vcenter',
            'align': 'right'})
        row_idx = 0
        ws.write(row_idx, 0, title, title_fmt)
        row_idx += 1
        ws.write(row_idx, 0, '%s | %s: %s' % (
            sheet.get('generated', ''), 'Rows', len(rows)), info_fmt)
        row_idx += 2
        ws.set_row(row_idx, 28)
        for col_idx, head in enumerate(['No'] + list(headers)):
            ws.write(row_idx, col_idx, head, header_fmt)
        row_idx += 1
        for row in rows:
            ws.set_row(row_idx, 20)
            cells = [row.get('no', '')] + _cells(row, '\n')
            for col_idx, val in enumerate(cells):
                fmt = num_fmt if col_idx in (0, len(cells) - 2) else text_fmt
                ws.write(row_idx, col_idx, val, fmt)
            row_idx += 1
        widths = [6, 18, 45]
        if show_type:
            widths.append(12)
        widths.extend([40, 14, 20])
        for col_idx, width in enumerate(widths):
            ws.set_column(col_idx, col_idx, width)
        workbook.close()
        output.seek(0)
        return request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type',
                 'application/vnd.openxmlformats-officedocument'
                 '.spreadsheetml.sheet'),
                ('Content-Disposition',
                 'attachment; filename=%s_%s.xlsx' % (
                     file_base, stamp)),
            ]
        )
