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

class MatiaStockPlanningController(http.Controller):

    @http.route('/matia_stock_planning/export_xlsx', type='http', auth='user', methods=['POST'], csrf=False)
    def export_xlsx(self, **kwargs):
        """
        Ekranda o an görünen sütun ve verileri birebir temsil eden şık bir Excel dosyası oluşturur.
        """
        data_json = kwargs.get('data')
        if not data_json:
            return request.not_found()

        data = json.loads(data_json)
        headers = data.get('headers', [])
        groups = data.get('groups', [])
        filter_info = data.get('filter_info', '')

        if not xlsxwriter:
            # Fallback to UTF-8 BOM CSV if xlsxwriter is missing
            csv_lines = ['\ufeff' + f"Matia TekRMD Cihaz Stok ve Kapasite Planı - {filter_info}"]
            csv_lines.append(';'.join(headers))
            for grp in groups:
                csv_lines.append(f"--- {grp.get('title', '')} ---")
                for itm in grp.get('items', []):
                    vals = [str(c.get('val', '')) for c in itm.get('cells', [])]
                    csv_lines.append(';'.join(vals))
            content = '\r\n'.join(csv_lines).encode('utf-8')
            filename = f"TekRMD_Stok_Kapasite_Plani_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
            return request.make_response(
                content,
                headers=[
                    ('Content-Type', 'text/csv; charset=utf-8'),
                    ('Content-Disposition', f'attachment; filename={filename}'),
                ]
            )

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('TekRMD Kapasite Plani')
        worksheet.hide_gridlines(False)

        # Stiller
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

        # Başlık ve Tarih
        row = 0
        worksheet.write(row, 0, 'Matia TekRMD Cihaz Stok ve Kapasite Planı', title_format)
        row += 1
        now_str = datetime.now().strftime('%d.%m.%Y %H:%M')
        worksheet.write(row, 0, f"Rapor Tarihi: {now_str} | Filtre: {filter_info}", info_format)
        row += 2

        # Sütun Başlıkları
        worksheet.set_row(row, 28)
        col_widths = [15] * len(headers)
        for col_idx, h in enumerate(headers):
            worksheet.write(row, col_idx, h, header_format)
            if len(h) + 4 > col_widths[col_idx]:
                col_widths[col_idx] = len(h) + 4
        row += 1

        # Satırlar ve Gruplar
        for grp in groups:
            grp_key = grp.get('key', '')
            grp_title = grp.get('title', 'Grup')
            items = grp.get('items', [])

            # Grup stilini seç
            if grp_key == 'outdoor':
                g_fmt = group_outdoor_format
            elif grp_key == 'seat':
                g_fmt = group_seat_format
            else:
                g_fmt = group_base_format

            # Grup başlık satırı
            worksheet.set_row(row, 24)
            worksheet.merge_range(row, 0, row, len(headers) - 1, f"  {grp_title} ({len(items)} Parça)", g_fmt)
            row += 1

            for itm in items:
                worksheet.set_row(row, 20)
                cells = itm.get('cells', [])
                for col_idx, cell in enumerate(cells):
                    val = cell.get('val', '')
                    c_type = cell.get('type', 'text')

                    if c_type == 'ok':
                        worksheet.write(row, col_idx, val, cell_ok_format)
                    elif c_type == 'need':
                        worksheet.write(row, col_idx, val, cell_need_format)
                    elif c_type == 'number':
                        worksheet.write(row, col_idx, val, cell_num_format)
                    else:
                        worksheet.write(row, col_idx, val, cell_text_format)

                    # Otomatik genişlik
                    val_str = str(val)
                    if len(val_str) + 3 > col_widths[col_idx]:
                        col_widths[col_idx] = min(len(val_str) + 3, 50)
                row += 1

        # Sütun genişliklerini ayarla
        for col_idx, w in enumerate(col_widths):
            worksheet.set_column(col_idx, col_idx, w)

        workbook.close()
        output.seek(0)

        filename = f"TekRMD_Stok_Kapasite_Plani_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        return request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename={filename}'),
            ]
        )
