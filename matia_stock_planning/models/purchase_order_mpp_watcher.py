# -*- coding: utf-8 -*-
"""Purchase watcher: flag released plans when a linked RFQ/PO is gone.

Never blocks: cancel/unlink always succeed; released plans linked by
PO origin (= plan name) only get needs_revision + a chatter note so
the tracking screen surfaces the gap.
"""
import logging

from odoo import models, _

_logger = logging.getLogger(__name__)


class PurchaseOrderMppWatcher(models.Model):
    """Watch plan-linked RFQs/POs for cancel/unlink after release."""

    _inherit = 'purchase.order'

    def _mpp_flag_released_plans(self, what, names=None, origins=None):
        """Set needs_revision + chatter note on released plans.

        Best-effort by design: watcher failures must never break the
        underlying cancel/unlink.
        @param what: 'cancelled' or 'deleted' (for the message).
        @param names: PO names for the message (default: self names).
        @param origins: PO origins to match plans (default: self
            origins; unlink passes these explicitly because the
            records are already gone).
        @return: None.
        """
        try:
            if origins is None:
                try:
                    origins = list({
                        o for o in self.mapped('origin') if o})
                except Exception:
                    origins = []
            if names is None:
                try:
                    names = self.mapped('name')
                except Exception:
                    names = []
            plans = self.env['matia.procurement.plan'].browse()
            if origins:
                try:
                    # Both locked states are watched: released plans are
                    # live, closed plans stay locked but can still be
                    # re-opened for revision, so a cancelled/deleted PO
                    # must surface on their tracking screens too.
                    plans = self.env['matia.procurement.plan'].search([
                        ('name', 'in', origins),
                        ('release_state', 'in', ['released', 'closed']),
                    ])
                except Exception:
                    _logger.warning(
                        'MPP watcher plan lookup failed.', exc_info=True)
        except Exception:
            _logger.warning(
                'MPP watcher flag failed.', exc_info=True)
            return
        for plan in plans:
            try:
                plan.write({'needs_revision': True})
                if what == 'deleted':
                    plan.message_post(body=_(
                        '%s was deleted after release rev %s. Check '
                        'the tracking screen and revise the plan if '
                        'needed.') % (', '.join(names),
                                       plan.released_rev))
                else:
                    plan.message_post(body=_(
                        '%s was cancelled after release rev %s. Check '
                        'the tracking screen and revise the plan if '
                        'needed.') % (', '.join(names),
                                       plan.released_rev))
            except Exception:
                _logger.warning(
                    'MPP watcher could not flag plan %s.',
                    plan.name, exc_info=True)

    def button_cancel(self):
        """Cancel, then flag released plans (non-blocking).

        @return: super result.
        """
        res = super(PurchaseOrderMppWatcher, self).button_cancel()
        self._mpp_flag_released_plans('cancelled')
        return res

    def unlink(self):
        """Delete, then flag released plans (non-blocking).

        Origins are captured before super(): afterwards the records
        are gone.
        @return: super result.
        """
        names = self.mapped('name')
        origins = list({o for o in self.mapped('origin') if o})
        res = super(PurchaseOrderMppWatcher, self).unlink()
        if origins and names:
            self._mpp_flag_released_plans(
                'deleted', names=names, origins=origins)
        return res
