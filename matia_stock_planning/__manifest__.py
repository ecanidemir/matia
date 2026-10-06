# -*- coding: utf-8 -*-
{
    'name': 'Matia TekRMD Stock & Capacity Planning',
    'version': '15.0.2.3.0',
    'category': 'Inventory/Inventory',
    'summary': 'Device Production Capacity & Stock Analysis based on TekRMD BOMs',
    'description': """
Matia TekRMD Stock & Capacity Planning
======================================
This module analyzes parts from TekRMD Common Parts (Base), Outdoor Parts, and Seat Parts BOMs
across TR and USA warehouse locations to calculate:
- Maximum producible device count,
- Missing part quantities needed for 20 devices,
- Up to 3 customizable dynamic device target columns,
- TR (WHTR/Stock/*) and USA (WHUS/Stock/*) location filtering (excluding NCR),
- NCR storage stock quantities for informational purposes,
- BOM usage quantity toggle (hide/show),
- Direct Excel (.xlsx) export matching screen layout and visibility.
    """,
    'author': 'Matia Robotics',
    'website': 'https://matiamobility.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'stock',
        'mrp',
        'purchase',
        'web',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/matia_procurement_plan_sequence.xml',
        'views/stock_planning_views.xml',
        'views/stock_planning_menus.xml',
        'views/procurement_plan_views.xml',
        'views/procurement_plan_rfq_views.xml',
        'views/procurement_plan_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'matia_stock_planning/static/src/scss/stock_planning.scss',
            'matia_stock_planning/static/src/js/stock_planning.js',
            'matia_stock_planning/static/src/scss/procurement_plan.scss',
            'matia_stock_planning/static/src/js/procurement_plan.js',
        ],
        'web.assets_qweb': [
            'matia_stock_planning/static/src/xml/stock_planning.xml',
            'matia_stock_planning/static/src/xml/procurement_plan.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
