# -*- coding: utf-8 -*-
"""Manual price/location overrides per product (global, all plans).

Tab 3 "Prices" of the Production Plan dashboard manages these records:
the user fixes products whose last purchase price is missing or wrong by
entering a manual USD price (corrected_price_usd) and/or a purchase
location (TR/US). One row per product at most; valid in every plan until
changed or cleared.

The corrected price is a USD unit price per plan-line UoM (no UoM
conversion is applied to it). The location routes the draft RFQ to the
matching company (TR -> company 1, US -> company 2).
"""

from odoo import fields, models


class MatiaProcurementPriceOverride(models.Model):
    """Manual USD price + purchase location for one product.

    @param product_id: product this override belongs to (unique).
    @param corrected_price_usd: manual USD unit price, 0.0 = none set.
    @param location: 'tr' / 'us' purchase location, False = not chosen.
    """

    _name = 'matia.procurement.price.override'
    _description = 'Matia Manual Price Override (global per product)'

    product_id = fields.Many2one(
        'product.product', required=True, ondelete='cascade',
        help='Product this manual price/location belongs to.')
    corrected_price_usd = fields.Float(
        digits=(16, 4), default=0.0,
        help='Manual USD unit price per plan-line UoM. Overrides the '
             'last-buy USD price in rolled costs, supplier totals and '
             'draft RFQs when greater than zero.')
    location = fields.Selection(
        [('tr', 'TR'), ('us', 'US')],
        help='Purchase location: routes the draft RFQ to the TR or US '
             'company. Empty keeps the last-buy company rule.')

    _sql_constraints = [
        ('product_uniq', 'unique(product_id)',
         'Only one price override per product is allowed.'),
    ]
