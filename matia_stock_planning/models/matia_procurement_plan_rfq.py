# -*- coding: utf-8 -*-
"""Kademe 2: create draft RFQs from a supplier-reviewed preview plan.

This file ONLY extends the Kademe 1 preview models (``_inherit``); the
preview logic in ``matia_procurement_plan.py`` and the Capacity Plan
page (``stock_planning.*``) are untouched.

Rules:
- One draft RFQ per supplier. If a supplier has lines priced in mixed
  currencies, one RFQ per (supplier, currency) is created so the
  original price snapshot (price + currency) is preserved on the PO.
- Only ``buy`` lines with ``order_qty > 0`` and an assigned seller are
  eligible. ``make`` / ``subcontract`` lines stay in production scope.
- Price snapshot: ``price_unit`` = line ``last_price`` with the PO
  currency = line ``last_currency_id`` (no conversion on write).
- Repeat protection: creating again while RFQs are linked requires
  explicit ``confirm=True`` from the client.
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .matia_procurement_plan import _mpp_env_sudo


class MatiaProcurementPlanRfq(models.Model):
    """RFQ creation extension for the preview plan."""
    _inherit = 'matia.procurement.plan'

    state = fields.Selection(
        selection_add=[('rfq_created', 'Draft RFQs created')],
        ondelete={'rfq_created': 'set default'},
    )
    purchase_order_ids = fields.Many2many(
        'purchase.order', 'matia_proc_plan_po_rel', 'plan_id', 'po_id',
        string='Draft RFQs', readonly=True,
        help='Draft purchase orders created from this plan. '
             'Existing records are never deleted by this module.')
    rfq_count = fields.Integer(
        compute='_compute_rfq_count', store=True,
        string='RFQ Count')

    @api.depends('purchase_order_ids')
    def _compute_rfq_count(self):
        """Count linked draft RFQs.

        @param self: plan recordset.
        @return: None (sets rfq_count).
        """
        for plan in self:
            plan.rfq_count = len(plan.purchase_order_ids)

    def _rfq_groups(self, plan):
        """Bucket RFQ-eligible lines by (seller, currency).

        @param plan: matia.procurement.plan record (sudo env).
        @return: (groups, skipped) where groups is a list of dicts
            {seller_id, seller_name, currency_id, currency_name, lines,
            subtotal} and skipped counts excluded lines by reason.
        """
        groups = {}
        skipped = {
            'make': 0, 'subcontract': 0, 'unknown': 0, 'zero_qty': 0,
            'no_supplier': 0,
        }
        for line in plan.line_ids:
            route = line.route_type or 'unknown'
            if route != 'buy':
                skipped[route if route in skipped else 'unknown'] += 1
                continue
            if not (line.order_qty or 0.0) > 0:
                skipped['zero_qty'] += 1
                continue
            if not line.seller_id:
                skipped['no_supplier'] += 1
                continue
            cur_id = line.last_currency_id.id if line.last_currency_id else 0
            key = (line.seller_id.id, cur_id)
            bucket = groups.setdefault(key, {
                'seller_id': line.seller_id.id,
                'seller_name': line.seller_id.display_name,
                'currency_id': cur_id,
                'currency_name': line.last_currency_id.name
                if line.last_currency_id else '',
                'lines': [],
                'subtotal': 0.0,
            })
            bucket['lines'].append(line)
            bucket['subtotal'] += (
                (line.order_qty or 0.0) * (line.last_price or 0.0))
        return list(groups.values()), skipped

    def _rfq_plan(self, plan_id):
        """Load the plan in sudo env and validate its state.

        @param plan_id: database id of the plan.
        @return: (env_sudo, plan) tuple.
        """
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(plan_id)
        if not plan.exists():
            raise UserError(_('Plan not found.'))
        if plan.state not in ('supplier_review', 'calculated',
                              'rfq_created'):
            raise UserError(_(
                'Run supplier preview before creating draft RFQs.'))
        return env_sudo, plan

    def get_rfq_preview(self, plan_id):
        """Preview the draft RFQs that would be created (no writes).

        @param plan_id: database id of the plan.
        @return: dict with supplier groups, line counts, subtotals,
            skipped counters and already linked RFQs.
        """
        self.ensure_one()
        env_sudo, plan = self._rfq_plan(plan_id)
        groups, skipped = self._rfq_groups(plan)
        preview_groups = []
        for grp in groups:
            preview_groups.append({
                'seller_id': grp['seller_id'],
                'seller_name': grp['seller_name'],
                'currency_id': grp['currency_id'],
                'currency_name': grp['currency_name'],
                'line_count': len(grp['lines']),
                'subtotal': grp['subtotal'],
                'lines': [{
                    'product_id': line.product_id.id,
                    'code': line.product_id.default_code or '',
                    'name': line.product_id.display_name,
                    'order_qty': line.order_qty,
                    'last_price': line.last_price,
                    'last_currency': grp['currency_name'],
                } for line in grp['lines']],
            })
        return {
            'plan_id': plan.id,
            'plan_name': plan.name,
            'supplier_count': len(preview_groups),
            'line_count': sum(len(g['lines']) for g in groups),
            'groups': preview_groups,
            'skipped': skipped,
            'existing_rfq_count': len(plan.purchase_order_ids),
            'existing_rfqs': [{
                'id': po.id, 'name': po.name,
                'partner': po.partner_id.display_name,
            } for po in plan.purchase_order_ids],
        }

    def action_create_draft_rfqs(self, plan_id, confirm=False):
        """Create one draft RFQ per (supplier, currency) group.

        @param plan_id: database id of the plan.
        @param confirm: True when the user confirmed repeat creation.
        @return: dict with created RFQs (id, name, partner, lines,
            amount) or {'needs_confirm': True} when RFQs already exist.
        """
        self.ensure_one()
        env_sudo, plan = self._rfq_plan(plan_id)
        existing = plan.purchase_order_ids
        if existing and not confirm:
            return {
                'needs_confirm': True,
                'existing_count': len(existing),
                'existing': [{
                    'id': po.id, 'name': po.name,
                    'partner': po.partner_id.display_name,
                } for po in existing],
                'message': _(
                    'This plan already has %d draft RFQ(s). '
                    'Creating again will add new RFQs; existing '
                    'records are kept.') % len(existing),
            }
        groups, skipped = self._rfq_groups(plan)
        if not groups:
            raise UserError(_(
                'No RFQ-eligible lines: need buy lines with quantity '
                'and an assigned supplier.'))
        company = plan.company_id
        picking = env_sudo['stock.picking.type'].search([
            ('code', '=', 'incoming'),
            ('company_id', '=', company.id),
        ], limit=1)
        if not picking:
            raise UserError(_(
                'No incoming picking type found for this company.'))
        fallback_currency = (
            plan.currency_id.id if plan.currency_id
            else company.currency_id.id)
        created = []
        try:
            for grp in groups:
                po = env_sudo['purchase.order'].create({
                    'partner_id': grp['seller_id'],
                    'company_id': company.id,
                    'currency_id': grp['currency_id'] or fallback_currency,
                    'picking_type_id': picking.id,
                    'origin': plan.name,
                    'date_order': fields.Datetime.now(),
                })
                amount = 0.0
                for line in grp['lines']:
                    uom = (line.uom_id.id if line.uom_id
                           else line.product_id.uom_po_id.id
                           if line.product_id.uom_po_id else False)
                    po_line = env_sudo['purchase.order.line'].create({
                        'order_id': po.id,
                        'product_id': line.product_id.id,
                        'product_qty': line.order_qty,
                        'product_uom': uom,
                        'price_unit': line.last_price or 0.0,
                        'name': '[%s] %s' % (
                            plan.name, line.product_id.display_name),
                        'date_planned': fields.Date.today(),
                    })
                    line.write({
                        'purchase_order_id': po.id,
                        'purchase_line_id': po_line.id,
                    })
                    amount += ((line.order_qty or 0.0)
                               * (line.last_price or 0.0))
                created.append({
                    'id': po.id,
                    'name': po.name,
                    'partner': grp['seller_name'],
                    'currency': grp['currency_name'],
                    'line_count': len(grp['lines']),
                    'amount': amount,
                })
            plan.write({
                'purchase_order_ids': [(4, c['id']) for c in created],
                'state': 'rfq_created',
            })
        except Exception as exc:
            raise UserError(_('Draft RFQ creation failed: %s') % exc)
        return {
            'needs_confirm': False,
            'created': created,
            'skipped': skipped,
            'summary': self._plan_summary(env_sudo, plan),
        }

    def _plan_summary(self, env_sudo, plan):
        """Extend the Kademe 1 summary with linked RFQ info.

        @param env_sudo: sudo environment.
        @param plan: matia.procurement.plan record.
        @return: summary dict with rfq info on supplier groups.
        """
        res = super(MatiaProcurementPlanRfq, self)._plan_summary(
            env_sudo, plan)
        po_by_seller = {}
        for po in plan.purchase_order_ids:
            po_by_seller.setdefault(po.partner_id.id, []).append({
                'id': po.id, 'name': po.name,
            })
        for sup in res.get('suppliers', []):
            sup['rfqs'] = po_by_seller.get(sup.get('seller_id'), [])
        res['rfqs'] = [{
            'id': po.id, 'name': po.name,
            'partner': po.partner_id.display_name,
        } for po in plan.purchase_order_ids]
        res['rfq_count'] = len(plan.purchase_order_ids)
        return res


class MatiaProcurementPlanLineRfq(models.Model):
    """RFQ traceability on plan lines."""
    _inherit = 'matia.procurement.plan.line'

    purchase_order_id = fields.Many2one(
        'purchase.order', readonly=True,
        help='Draft RFQ created from this line (if any).')
    purchase_line_id = fields.Many2one(
        'purchase.order.line', readonly=True,
        help='Draft RFQ line created from this line (if any).')
