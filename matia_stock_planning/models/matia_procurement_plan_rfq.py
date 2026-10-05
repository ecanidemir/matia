# -*- coding: utf-8 -*-
"""Kademe 2: create draft RFQs from a supplier-reviewed preview plan.

This file ONLY extends the Kademe 1 preview models (``_inherit``); the
preview logic in ``matia_procurement_plan.py`` and the Capacity Plan
page (``stock_planning.*``) are untouched.

Rules:
- One draft RFQ per supplier. If a supplier has lines priced in mixed
  currencies, one RFQ per (supplier, currency) is created so the
  original price snapshot (price + currency) is preserved on the PO.
- ``buy`` and ``subcontract`` lines with ``order_qty > 0`` and an
  assigned seller are eligible (subcontract is ordered from the
  subcontractor; confirming the PO runs Odoo's standard subcontract
  chain). ``make`` lines stay in production scope (draft MOs).
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
        """Bucket RFQ-eligible lines by (seller, currency, company).

        The company comes from each line's last purchase (TR or USA):
        the draft PO is created in that company so the receipt lands in
        the right warehouse (WHTR vs WHUS).
        @param plan: matia.procurement.plan record (sudo env).
        @return: (groups, skipped) where groups is a list of dicts
            {seller_id, seller_name, currency_id, currency_name,
            company_id, company, lines, subtotal} and skipped counts
            excluded lines by reason.
        """
        groups = {}
        skipped = {
            'make': 0, 'subcontract': 0, 'unknown': 0, 'zero_qty': 0,
            'no_supplier': 0,
        }
        for line in plan.line_ids:
            route = line.route_type or 'unknown'
            if route not in ('buy', 'subcontract'):
                skipped[route if route in skipped else 'unknown'] += 1
                continue
            if not (line.order_qty or 0.0) > 0:
                skipped['zero_qty'] += 1
                continue
            if not line.seller_id:
                skipped['no_supplier'] += 1
                continue
            cur_id = line.last_currency_id.id if line.last_currency_id else 0
            comp_id = line.last_company_id.id if line.last_company_id \
                else plan.company_id.id
            key = (line.seller_id.id, cur_id, comp_id)
            bucket = groups.setdefault(key, {
                'seller_id': line.seller_id.id,
                'seller_name': line.seller_id.display_name,
                'currency_id': cur_id,
                'currency_name': line.last_currency_id.name
                if line.last_currency_id else '',
                'company_id': comp_id,
                'company': self._mpp_company_code(
                    plan.env, comp_id),
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
                'company_id': grp['company_id'],
                'company': grp['company'],
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
        # Incoming picking type per company (TR Receipts / US Receive),
        # so each PO's receipt lands in the right warehouse.
        pickings = {}

        def _incoming(cid):
            if cid not in pickings:
                pick = env_sudo['stock.picking.type'].search([
                    ('code', '=', 'incoming'),
                    ('company_id', '=', cid),
                ], limit=1)
                if not pick:
                    raise UserError(_(
                        'No incoming picking type found for company %s.')
                        % cid)
                pickings[cid] = pick
            return pickings[cid]

        created = []
        try:
            for grp in groups:
                gcomp = env_sudo['res.company'].browse(
                    grp['company_id'])
                picking = _incoming(grp['company_id'])
                po = env_sudo['purchase.order'].create({
                    'partner_id': grp['seller_id'],
                    'company_id': grp['company_id'],
                    'currency_id': grp['currency_id']
                    or gcomp.currency_id.id,
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

    def action_create_supplier_rfq(self, plan_id, seller_id,
                                   company_id=None, confirm=False):
        """Create draft RFQ(s) for ONE supplier in ONE company.

        The tab-3 button (TR RFQ / US RFQ) passes the row's company: one
        PO per (seller, currency) inside that company. Idempotent per
        seller+company: existing draft POs of this plan for that pair
        require confirm=True.
        @param plan_id Plan ID.
        @param seller_id res.partner ID.
        @param company_id res.company ID (row's source company).
        @param confirm True when the user confirmed repeat creation.
        @return Dict with created POs or {'needs_confirm': True}, plus
            a fresh supplier summary for tab 3.
        """
        self.ensure_one()
        env_sudo, plan = self._rfq_plan(plan_id)
        try:
            seller_id = int(seller_id)
        except (TypeError, ValueError):
            raise UserError(_('Invalid supplier.'))
        try:
            company_id = int(company_id) if company_id else False
        except (TypeError, ValueError):
            company_id = False
        groups, skipped = self._rfq_groups(plan)
        groups = [g for g in groups if g['seller_id'] == seller_id
                  and (not company_id or g['company_id'] == company_id)]
        if not groups:
            raise UserError(_(
                'No RFQ-eligible lines for this supplier: need buy or '
                'subcontract lines with quantity.'))
        company_id = groups[0]['company_id']
        groups = [g for g in groups
                  if g['company_id'] == company_id]
        existing = [po for po in plan.purchase_order_ids
                    if po.partner_id.id == seller_id
                    and po.company_id.id == company_id
                    and po.state == 'draft']
        if existing and not confirm:
            return {
                'needs_confirm': True,
                'seller_id': seller_id,
                'seller_name': groups[0]['seller_name'],
                'company_id': company_id,
                'company': groups[0]['company'],
                'existing': [{
                    'id': po.id, 'name': po.name,
                } for po in existing],
                'message': _(
                    'This supplier already has %d draft RFQ(s) from '
                    'this plan in %s. Creating again will add new '
                    'RFQs; existing records are kept.') % (
                        len(existing), groups[0]['company']),
            }
        company = env_sudo['res.company'].browse(company_id)
        picking = env_sudo['stock.picking.type'].search([
            ('code', '=', 'incoming'),
            ('company_id', '=', company.id),
        ], limit=1)
        if not picking:
            raise UserError(_(
                'No incoming picking type found for %s.') % company.name)
        created = []
        try:
            for grp in groups:
                po = env_sudo['purchase.order'].create({
                    'partner_id': grp['seller_id'],
                    'company_id': company.id,
                    'currency_id': grp['currency_id']
                    or company.currency_id.id,
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
                    'company': grp['company'],
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
            'supplier_summary': self.get_supplier_summary(plan.id),
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
