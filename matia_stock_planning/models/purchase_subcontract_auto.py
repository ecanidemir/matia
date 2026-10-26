# -*- coding: utf-8 -*-
"""Auto-register PO vendors on subcontract BOMs before confirm.

Odoo picks the subcontract BOM matching the vendor at confirm time.
Without a match the order falls back to a plain receipt and component
resupply moves are never created (seen on PO/26-00146: 67 subcontract
BOMs listed only partners 1088/1240, vendor 1299 missing).
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class PurchaseOrderSubcontractAuto(models.Model):
    """Register vendors on subcontract BOMs prior to procurement.

    Runs inside ``button_confirm`` before ``super()`` because BOM
    selection happens during confirm; a post-confirm automation would
    only help the *next* order.
    """

    _inherit = 'purchase.order'

    def button_confirm(self):
        """Confirm after ensuring subcontract BOMs accept the vendor.

        Best-effort by design: auto-register failures must never break
        the purchase flow (the order then behaves as before).
        @return: super result.
        """
        try:
            self._msp_ensure_subcontract_vendors()
        except Exception:
            _logger.warning(
                'Subcontract auto-register failed.', exc_info=True)
        return super(
            PurchaseOrderSubcontractAuto, self).button_confirm()

    def _msp_ensure_subcontract_vendors(self):
        """Add each order's vendor to its subcontract BOMs.

        Only touches ``mrp.bom`` records with ``type=subcontract``
        whose product (template or variant) matches an order line.
        Lines without a BOM, non-subcontract BOMs and vendors already
        listed are skipped.
        @return: None.
        """
        for order in self:
            try:
                vendor = order.partner_id
                if not vendor:
                    continue
                tmpl_ids = list({
                    line.product_id.product_tmpl_id.id
                    for line in order.order_line
                    if line.product_id and line.product_id.product_tmpl_id
                })
                if not tmpl_ids:
                    continue
                env_sudo = order.with_context(
                    allowed_company_ids=(
                        order.company_id.ids or [1]),
                    active_test=False).sudo().env
                boms = env_sudo['mrp.bom'].search([
                    ('product_tmpl_id', 'in', tmpl_ids),
                    ('type', '=', 'subcontract'),
                ])
                for bom in boms:
                    try:
                        if bom.product_id:
                            line_pids = set(
                                line.product_id.id
                                for line in order.order_line
                                if line.product_id)
                            if bom.product_id.id not in line_pids:
                                continue
                        if vendor.id in bom.subcontractor_ids.ids:
                            continue
                        bom.write({
                            'subcontractor_ids': [(4, vendor.id)],
                        })
                        _logger.info(
                            'PO %s: vendor %s added to subcontract BOM %s.',
                            order.name, vendor.id, bom.id)
                    except Exception:
                        _logger.warning(
                            'PO %s: could not update BOM %s.',
                            order.name, bom.id, exc_info=True)
            except Exception:
                _logger.warning(
                    'Subcontract auto-register failed for an order.',
                    exc_info=True)
