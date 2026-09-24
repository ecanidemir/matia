# -*- coding: utf-8 -*-
{
    'name': 'Matia TekRMD Stok & Kapasite Planlama',
    'version': '15.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'TekRMD Reçeteleri ve Stok Miktarları ile Cihaz Kapasite Analizi',
    'description': """
Matia TekRMD Stok & Kapasite Planlama
====================================
Bu modül TekRMD Common Parts (Base), Outdoor Parts ve Seat Parts reçetelerindeki
parçaların TR ve USA lokasyonlarındaki stok miktarlarını analiz ederek:
- Üretilebilecek maksimum cihaz sayısını,
- 20 cihaz için gerekli eksik ürün adetlerini,
- Kullanıcı tanımlı 3 adede kadar dinamik hedef cihaz ihtiyacını,
- TR (WHTR/Stock/*) ve USA (WHUS/Stock/*) konum filtrelemesini (NCR hariç),
- NCR alanındaki stok miktarını bilgilendirme olarak,
- Kullanım miktarı gizleme/gösterme seçeneğini,
- Ekranda görülen yapıyı koruyarak Excel (.xlsx) indirme özelliğini sunar.
    """,
    'author': 'Matia Robotics',
    'website': 'https://matiamobility.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'stock',
        'mrp',
        'web',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/stock_planning_views.xml',
        'views/stock_planning_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'matia_stock_planning/static/src/scss/stock_planning.scss',
            'matia_stock_planning/static/src/js/stock_planning.js',
        ],
        'web.assets_qweb': [
            'matia_stock_planning/static/src/xml/stock_planning.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
