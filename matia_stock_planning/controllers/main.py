# -*- coding: utf-8 -*-
import io
import json
from datetime import datetime
from odoo import http
from odoo.http import request

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None

from .capacity_sheet import (
    CAPACITY_TITLE,
    capacity_csv_lines,
    write_capacity_sheet,
)

class MatiaStockPlanningController(http.Controller):

    @http.route('/matia_stock_planning/export_xlsx', type='http', auth='user', methods=['POST'], csrf=False)
    def export_xlsx(self, **kwargs):
        """
        Generates an Excel sheet exactly matching the visible screen columns and rows.

        The table layout lives in controllers/capacity_sheet.py (shared
        with the combined popup export); this route only parses the
        screen payload and owns the filename.
        """
        data_json = kwargs.get('data')
        if not data_json:
            return request.not_found()

        try:
            data = json.loads(data_json)
        except (TypeError, ValueError):
            return request.not_found()
        headers = data.get('headers', [])
        groups = data.get('groups', [])
        filter_info = data.get('filter_info', '')

        if not xlsxwriter:
            # Fallback to UTF-8 BOM CSV if xlsxwriter is missing
            csv_lines = capacity_csv_lines(
                headers, groups, filter_info, title=CAPACITY_TITLE)
            content = '\r\n'.join(csv_lines).encode('utf-8')
            filename = f"TekRMD_Stock_Capacity_Plan_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
            return request.make_response(
                content,
                headers=[
                    ('Content-Type', 'text/csv; charset=utf-8'),
                    ('Content-Disposition', f'attachment; filename={filename}'),
                ]
            )

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('TekRMD Capacity Plan')
        write_capacity_sheet(
            workbook, worksheet, headers, groups, filter_info,
            title=CAPACITY_TITLE)

        workbook.close()
        output.seek(0)

        filename = f"TekRMD_Stock_Capacity_Plan_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        return request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename={filename}'),
            ]
        )
