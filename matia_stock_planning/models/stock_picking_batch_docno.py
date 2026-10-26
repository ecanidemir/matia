# -*- coding: utf-8 -*-
"""Copy batch Doc No to transfers before batch validation.

RES batches (Resupply Subcontractor) require ``document_number`` on every
open transfer at validate time. Users enter the number once on the batch
(Studio field ``x_docno``); this override propagates it automatically so
the extra "Belge No Kopyala" click is no longer needed.
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockPickingBatchDocno(models.Model):
    """Propagate batch Doc No to open transfers on validate.

    Runs inside ``action_done`` before ``super()`` because picking-level
    document validation happens during validate; copying afterwards would
    only help the *next* batch.
    """

    _inherit = 'stock.picking.batch'

    def action_done(self):
        """Copy Doc No to open transfers, then validate as usual.

        Empty Doc No is skipped silently (core validation still warns).
        ``done``/``cancel`` transfers are untouched (history preserved).
        Best-effort by design: copy failures must never break validation
        (the batch then behaves as before).
        @return: super result.
        """
        try:
            self._msp_copy_docno_to_pickings()
        except Exception:
            _logger.exception('Batch Doc No copy failed.')
        return super(StockPickingBatchDocno, self).action_done()

    def _msp_copy_docno_to_pickings(self):
        """Write each batch's Doc No onto its open transfers.

        Guards: ``x_docno`` is a Studio field and ``document_number``
        comes from ``l10n_tr_account_document_stock``; either may be
        absent (e.g. Studio field deleted) and then nothing happens.
        Filled numbers are overwritten (user decision 2026-10-26).
        @return: None.
        """
        has_docno = 'x_docno' in self._fields
        if not has_docno:
            return
        for batch in self:
            docno = (batch['x_docno'] or '').strip()
            if not docno:
                continue
            pickings = batch.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel'))
            if not pickings or 'document_number' not in pickings._fields:
                continue
            pickings.write({'document_number': docno})
