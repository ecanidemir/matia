# -*- coding: utf-8 -*-
"""Printable TR/US stock-count sheets (Count List buttons).

Two read-only routes per company behind the backend login
(auth='user', same exposure as the existing export routes):

- GET /matia_stock_planning/count_sheet/<tr|us>:
  printable HTML page with Print + Excel buttons.
- GET /matia_stock_planning/count_sheet/<tr|us>/xlsx:
  .xlsx download (UTF-8 BOM CSV fallback without xlsxwriter).

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

    @http.route('/matia_stock_planning/count_sheet/<string:company>/xlsx',
                type='http', auth='user', methods=['GET'])
    def count_sheet_xlsx(self, company, **kwargs):
        """Download the same rows as .xlsx (or CSV fallback).

        @param company: 'tr' or 'us' (anything else -> 404).
        """
        if (company or '').strip().lower() not in ('tr', 'us'):
            return request.not_found()
        sheet = request.env['matia.stock.planning'].get_count_sheet(
            company)
        headers = sheet.get('headers', [])
        rows = sheet.get('rows', []) or []
        title = sheet.get('title', '')
        stamp = datetime.now().strftime('%Y%m%d_%H%M')
        file_base = sheet.get('file_base') or 'Count_List'

        if not xlsxwriter:
            lines = ['\ufeff' + '%s - %s' % (title, sheet.get(
                'generated', ''))]
            lines.append(';'.join(['No'] + list(headers)))
            for row in rows:
                lines.append(';'.join([
                    str(row.get('no', '')),
                    row.get('code') or '',
                    row.get('name') or '',
                    row.get('type_label') or '',
                    ' / '.join(row.get('locs') or []),
                    row.get('qty_text') or '',
                ]))
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
            ws.write(row_idx, 0, row.get('no', ''), num_fmt)
            ws.write(row_idx, 1, row.get('code') or '', text_fmt)
            ws.write(row_idx, 2, row.get('name') or '', text_fmt)
            ws.write(row_idx, 3, row.get('type_label') or '', text_fmt)
            ws.write(row_idx, 4,
                     '\n'.join(row.get('locs') or []), text_fmt)
            ws.write(row_idx, 5, row.get('qty_text') or '', num_fmt)
            row_idx += 1
        ws.set_column(0, 0, 6)
        ws.set_column(1, 1, 18)
        ws.set_column(2, 2, 45)
        ws.set_column(3, 3, 12)
        ws.set_column(4, 4, 40)
        ws.set_column(5, 5, 14)
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
