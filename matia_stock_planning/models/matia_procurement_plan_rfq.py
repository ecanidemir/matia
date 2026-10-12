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
from odoo.exceptions import AccessError, UserError
from xml.sax.saxutils import escape as _xml_escape
import json
import logging

from .matia_procurement_plan import (
    _MPP_OVERRIDE_COMPANY,
    _mpp_can_create_docs,
    _mpp_env_sudo,
    _mpp_line_uom_factor,
    _mpp_price_overrides,
)

_logger = logging.getLogger(__name__)


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

    @api.model
    def _rfq_line_eff(self, env_sudo, usd, plan, line, overrides):
        """Effective RFQ price/company for one plan line.

        A manual USD override wins: corrected price (per line UoM,
        factor 1.0) in USD, routed to the override purchase location.
        Otherwise the last-buy snapshot with the last-buy company.
        @param env_sudo: sudo environment.
        @param usd: res.currency USD record (or False).
        @param plan: matia.procurement.plan record.
        @param line: matia.procurement.plan.line record.
        @param overrides: _mpp_price_overrides() map.
        @return: {price, currency_id, currency_name, company_id}.
        """
        _ov = (overrides or {}).get(line.product_id.id, {})
        _corr = float(_ov.get('price') or 0.0)
        if _corr > 0:
            _loc = _ov.get('location')
            return {
                'price': _corr,
                'currency_id': usd.id if usd else 0,
                'currency_name': 'USD',
                'company_id': _MPP_OVERRIDE_COMPANY.get(_loc) or (
                    line.last_company_id.id if line.last_company_id
                    else plan.company_id.id),
            }
        # RFQ PO lines use the plan line UoM, so the PO-UoM snapshot
        # must be converted first (e.g. per-m price -> per-mm price).
        return {
            'price': (line.last_price or 0.0)
            * _mpp_line_uom_factor(line),
            'currency_id': line.last_currency_id.id
            if line.last_currency_id else 0,
            'currency_name': line.last_currency_id.name
            if line.last_currency_id else '',
            'company_id': line.last_company_id.id
            if line.last_company_id else plan.company_id.id,
        }

    def _rfq_groups(self, plan):
        """Bucket RFQ-eligible lines by (seller, currency, company).

        The company comes from each line's last purchase (TR or USA),
        or from the manual purchase location when set: the draft PO
        is created in that company so the receipt lands in the right
        warehouse (WHTR vs WHUS).
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
        env_sudo = plan.env
        usd = env_sudo['res.currency'].search(
            [('name', '=', 'USD')], limit=1)
        overrides = _mpp_price_overrides(env_sudo)
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
            eff = self._rfq_line_eff(
                env_sudo, usd, plan, line, overrides)
            cur_id = eff['currency_id']
            comp_id = eff['company_id']
            key = (line.seller_id.id, cur_id, comp_id)
            bucket = groups.setdefault(key, {
                'seller_id': line.seller_id.id,
                'seller_name': line.seller_id.display_name,
                'currency_id': cur_id,
                'currency_name': eff['currency_name'],
                'company_id': comp_id,
                'company': self._mpp_company_code(
                    plan.env, comp_id),
                'lines': [],
                'subtotal': 0.0,
            })
            bucket['lines'].append(line)
            bucket['subtotal'] += (
                (line.order_qty or 0.0) * eff['price'])
        return list(groups.values()), skipped

    def _rfq_plan(self, plan_id):
        """Load the plan in sudo env and validate its state.

        @param plan_id: database id of the plan (int or int-like).
        @return: (env_sudo, plan) tuple.
        """
        try:
            plan_id = int(plan_id)
        except (TypeError, ValueError):
            raise UserError(_('Invalid plan reference.'))
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(plan_id)
        if not plan.exists():
            raise UserError(_('Plan not found.'))
        if plan.state not in ('supplier_review', 'calculated',
                              'rfq_created'):
            raise UserError(_(
                'Run supplier preview before creating draft RFQs.'))
        return env_sudo, plan

    def _rfq_find_bom(self, env_sudo, product, company_id):
        """Find the best BOM for a product and company.

        Prefers the company's own BOM over a global one, and a
        normal/subcontract BOM over a phantom kit.

        @param env_sudo: sudo environment.
        @param product: product.product record.
        @param company_id: res.company id (or False).
        @return: mrp.bom record or False when none exists.
        """
        boms = env_sudo['mrp.bom'].search([
            ('product_tmpl_id', '=',
             product.product_tmpl_id.id),
            '|', ('product_id', '=', product.id),
            ('product_id', '=', False),
        ])
        if not boms:
            return False

        def _rank(bom):
            if company_id and bom.company_id.id == company_id:
                comp = 0
            elif not bom.company_id:
                comp = 1
            else:
                comp = 2
            kind = 0 if bom.type in (
                'normal', 'subcontract') else 1
            return (comp, kind, bom.id)

        return sorted(boms, key=_rank)[0]

    def _rfq_fmt_qty(self, qty):
        """Format a quantity compactly (integer when whole).

        @param qty: float quantity.
        @return: str without trailing decimal noise.
        """
        qty = float(qty or 0.0)
        if abs(qty - round(qty)) < 1e-9:
            return str(int(round(qty)))
        return ('%.2f' % qty).rstrip('0').rstrip('.')

    def _rfq_std_line_name(self, po, product):
        """Standard purchase line description (no module prefix).

        Mirrors the stock purchase onchange: variant display name
        plus the product's Purchase Description, in the vendor's
        language (partner context included, like the UI). The
        module never invents its own '[plan] ...' prefix.
        @param po: purchase.order record (vendor lang source).
        @param product: product.product record.
        @return: description string.
        """
        ctx = {'partner_id': po.partner_id.id}
        if po.partner_id.lang:
            ctx['lang'] = po.partner_id.lang
        prod = product.with_context(**ctx)
        name = prod.display_name or ''
        if prod.description_purchase:
            name += '\n' + prod.description_purchase
        return name

    def _rfq_usage_map(self, plan):
        """Invert the plan explosion edges (child -> parents).

        edge_json stores {parent: {child: qty}} with qty per
        parent unit in the CHILD's UoM. Inverting gives, for
        every child, its direct parents plus per-unit usage.
        @param plan: matia.procurement.plan record.
        @return: ({child_id: [(parent_id, qty_per_unit)]},
            {product_id: plan line}).
        """
        try:
            edges = json.loads(plan.edge_json or '{}')
        except ValueError:
            edges = {}
        parents = {}
        for _p, _ch in (edges or {}).items():
            try:
                _pi = int(_p)
            except (TypeError, ValueError):
                continue
            for _c, _q in (_ch or {}).items():
                try:
                    parents.setdefault(int(_c), []).append(
                        (_pi, float(_q or 0.0)))
                except (TypeError, ValueError):
                    continue
        lines = {}
        for _line in plan.line_ids:
            lines.setdefault(_line.product_id.id, _line)
        return parents, lines

    def _rfq_usage_lines(self, parents, lines_by_pid, child_id,
                         child_uom):
        """Net-based where-used breakdown for one child product.

        Walks the inverted edges upward; the first ancestor
        holding a plan line consumes (edge qty x line order_qty,
        i.e. the parent's NET need). Lineless ancestors
        (phantom kits) are passed through with an accumulated
        factor. Zero-net parents are skipped, so the parts sum
        to the parent-driven demand, not to the ordered qty
        (the child's own stock covers the rest).
        @param parents: inverted edge map from _rfq_usage_map.
        @param lines_by_pid: {product_id: plan line}.
        @param child_id: product.product id of the RFQ line.
        @param child_uom: UoM name of the RFQ line.
        @return: list of display strings, biggest first (max 10,
            plus an overflow note when more parents exist).
        """
        found = []
        seen = set()
        queue = [(child_id, 1.0)]
        guard = 0
        while queue and guard < 500:
            guard += 1
            _pid, _factor = queue.pop(0)
            for _pp, _q in parents.get(_pid, []):
                _nf = _factor * float(_q or 0.0)
                if _nf <= 0 or _pp in seen:
                    continue
                seen.add(_pp)
                _pl = lines_by_pid.get(_pp)
                if _pl is None:
                    queue.append((_pp, _nf))
                    continue
                _n = float(_pl.order_qty or 0.0)
                if _n <= 0:
                    continue
                _contrib = _nf * _n
                _puom = (_pl.uom_id.name
                         if _pl.uom_id else '')
                found.append((_contrib,
                    '[%s] %s: %s %s x %s %s = %s %s' % (
                        _pl.product_id.default_code or '',
                        _pl.product_id.display_name or '',
                        self._rfq_fmt_qty(_nf), child_uom,
                        self._rfq_fmt_qty(_n), _puom,
                        self._rfq_fmt_qty(_contrib),
                        child_uom)))
        found.sort(key=lambda t: -t[0])
        res = [t[1] for t in found[:10]]
        if len(found) > 10:
            res.append(_('... and %d more parents') % (
                len(found) - 10))
        return res

    def _rfq_bom_chatter(self, env_sudo, plan, po, lines):
        """Post a BOM-detail note on a freshly created RFQ.

        Each ordered line is listed with its ordered quantity; when
        the line product has a BOM, its components are exploded one
        level and scaled by the ordered quantity, e.g.
        '[M3TLMN01] Wheel Tool 2 Milling - 26 Units' with component
        '[M3TLTN02] Wheel Tool 2 Lathe - 26 Units (1 per)'.
        Lines without a BOM render as themselves only. Raw-material
        lines additionally list their NET-based usage (which parent
        products consume how much per piece, e.g. a 3500 mm bar
        shows '[M3PRT01] Bracket: 200 mm x 10 Units = 2000 mm').
        Posted as an internal note so the vendor is not emailed.

        @param env_sudo: sudo environment.
        @param plan: matia.procurement.plan record.
        @param po: purchase.order record to post on.
        @param lines: plan line recordset ordered on this RFQ.
        @return: None.
        """
        items = []
        usage_parents, lines_by_pid = self._rfq_usage_map(plan)
        for line in lines:
            prod = line.product_id
            src_uom = (line.uom_id or prod.uom_id
                       or prod.uom_po_id)
            src_uom_name = src_uom.name if src_uom else ''
            head = '[%s] %s - %s %s' % (
                prod.default_code or '',
                prod.display_name or '',
                self._rfq_fmt_qty(line.order_qty),
                src_uom_name)
            bom = self._rfq_find_bom(
                env_sudo, prod, po.company_id.id)
            subs = []
            if bom:
                try:
                    need = src_uom._compute_quantity(
                        line.order_qty or 0.0, bom.product_uom_id)
                except Exception:
                    need = line.order_qty or 0.0
                factor = (need / bom.product_qty) if bom.product_qty \
                    else 0.0
                for bl in bom.bom_line_ids:
                    cprod = bl.product_id
                    cqty = (bl.product_qty or 0.0) * factor
                    subs.append('[%s] %s - %s %s (%s per %s %s)' % (
                        cprod.default_code or '',
                        cprod.display_name or '',
                        self._rfq_fmt_qty(cqty),
                        bl.product_uom_id.name,
                        self._rfq_fmt_qty(bl.product_qty),
                        self._rfq_fmt_qty(bom.product_qty),
                        bom.product_uom_id.name))
            for _use in self._rfq_usage_lines(
                    usage_parents, lines_by_pid, prod.id,
                    src_uom_name):
                subs.append(_('uses: %s') % _use)
            if subs:
                items.append(
                    '<li>%s<ul><li>%s</li></ul></li>' % (
                        _xml_escape(head),
                        '</li><li>'.join(
                            _xml_escape(c) for c in subs)))
            else:
                items.append('<li>%s</li>' % _xml_escape(head))
        if not items:
            return
        body = '<p>%s</p><ul>%s</ul>' % (
            _xml_escape(_('BOM detail from %s:') % plan.name),
            ''.join(items))
        po.message_post(
            body=body, message_type='comment',
            subtype_xmlid='mail.mt_note')

    @api.model
    def get_rfq_preview(self, plan_id):
        """Preview the draft RFQs that would be created (no writes).

        @param plan_id: database id of the plan.
        @return: dict with supplier groups, line counts, subtotals,
            skipped counters and already linked RFQs.
        """
        # No ensure_one: called model-style (empty recordset) from JS.
        env_sudo, plan = self._rfq_plan(plan_id)
        groups, skipped = self._rfq_groups(plan)
        usd = env_sudo['res.currency'].search(
            [('name', '=', 'USD')], limit=1)
        overrides = _mpp_price_overrides(env_sudo)
        preview_groups = []
        for grp in groups:
            _plines = []
            for line in grp['lines']:
                _eff = self._rfq_line_eff(
                    env_sudo, usd, plan, line, overrides)
                _plines.append({
                    'product_id': line.product_id.id,
                    'code': line.product_id.default_code or '',
                    'name': line.product_id.display_name,
                    'order_qty': line.order_qty,
                    'last_price': _eff['price'],
                    'last_currency': _eff['currency_name'],
                })
            preview_groups.append({
                'seller_id': grp['seller_id'],
                'seller_name': grp['seller_name'],
                'currency_id': grp['currency_id'],
                'currency_name': grp['currency_name'],
                'company_id': grp['company_id'],
                'company': grp['company'],
                'line_count': len(grp['lines']),
                'subtotal': grp['subtotal'],
                'lines': _plines,
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

    @api.model
    def action_create_draft_rfqs(self, plan_id, confirm=False):
        """Create one draft RFQ per (supplier, currency) group.

        @param plan_id: database id of the plan.
        @param confirm: True when the user confirmed repeat creation.
        @return: dict with created RFQs (id, name, partner, lines,
            amount) or {'needs_confirm': True} when RFQs already exist.
        """
        # No ensure_one: called model-style (empty recordset) from JS.
        if not _mpp_can_create_docs(self):
            raise AccessError(_(
                'Only administrators can create draft RFQs.'))
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

        usd = env_sudo['res.currency'].search(
            [('name', '=', 'USD')], limit=1)
        overrides = _mpp_price_overrides(env_sudo)
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
                    _conv = self._rfq_line_eff(
                        env_sudo, usd, plan, line,
                        overrides)['price']
                    po_line = env_sudo['purchase.order.line'].create({
                        'order_id': po.id,
                        'product_id': line.product_id.id,
                        'product_qty': line.order_qty,
                        'product_uom': uom,
                        'price_unit': _conv,
                        'name': self._rfq_std_line_name(
                            po, line.product_id),
                        'date_planned': fields.Date.today(),
                    })
                    line.write({
                        'purchase_order_id': po.id,
                        'purchase_line_id': po_line.id,
                    })
                    amount += ((line.order_qty or 0.0) * _conv)
                try:
                    self._rfq_bom_chatter(
                        env_sudo, plan, po, grp['lines'])
                except Exception:
                    _logger.warning(
                        'MPP BOM chatter failed for PO %s.', po.id)
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
            _logger.exception('MPP draft RFQ creation failed.')
            raise UserError(_(
                'Draft RFQ creation failed. The technical detail was '
                'written to the server log.'))
        return {
            'needs_confirm': False,
            'created': created,
            'skipped': skipped,
            'summary': self._plan_summary(env_sudo, plan),
        }

    @api.model
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
        # No ensure_one: called model-style (empty recordset) from JS.
        if not _mpp_can_create_docs(self):
            raise AccessError(_(
                'Only administrators can create draft RFQs.'))
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
        usd = env_sudo['res.currency'].search(
            [('name', '=', 'USD')], limit=1)
        overrides = _mpp_price_overrides(env_sudo)
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
                    _conv2 = self._rfq_line_eff(
                        env_sudo, usd, plan, line,
                        overrides)['price']
                    po_line = env_sudo['purchase.order.line'].create({
                        'order_id': po.id,
                        'product_id': line.product_id.id,
                        'product_qty': line.order_qty,
                        'product_uom': uom,
                        'price_unit': _conv2,
                        'name': self._rfq_std_line_name(
                            po, line.product_id),
                        'date_planned': fields.Date.today(),
                    })
                    line.write({
                        'purchase_order_id': po.id,
                        'purchase_line_id': po_line.id,
                    })
                    amount += ((line.order_qty or 0.0)
                               * _conv2)
                try:
                    self._rfq_bom_chatter(
                        env_sudo, plan, po, grp['lines'])
                except Exception:
                    _logger.warning(
                        'MPP BOM chatter failed for PO %s.', po.id)
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
            _logger.exception('MPP draft RFQ creation failed.')
            raise UserError(_(
                'Draft RFQ creation failed. The technical detail was '
                'written to the server log.'))
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
