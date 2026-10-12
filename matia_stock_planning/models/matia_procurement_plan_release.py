# -*- coding: utf-8 -*-
"""Single-button Release flow for matia.procurement.plan (Odoo 15).

Release = one user action that creates/updates draft RFQs (buy +
subcontract lines, coverage-aware) and draft MOs (make lines,
origin+product dedup), stamps a JSON snapshot on the plan, locks the
plan against rebuilds, and opens the tracking screen.

Existing creation methods are reused UNCHANGED
(action_create_draft_rfqs / action_create_mos): the wizard only
pre-checks open groups/lines so a fully-covered plan still releases
with an empty document summary instead of raising.
"""
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from .matia_procurement_plan import _mpp_env_sudo, _mpp_can_create_docs
from .mpp_release_common import (
    build_snapshot_payload,
    line_tracking_status,
)

_logger = logging.getLogger(__name__)


class MatiaProcurementPlanRelease(models.Model):
    """Release state machine + lock + tracking entry points."""

    _inherit = ['matia.procurement.plan', 'mail.thread']

    release_state = fields.Selection([
        ('draft', 'Draft'),
        ('released', 'Released'),
        ('closed', 'Closed'),
    ], default='draft', required=True, tracking=True,
        help='Release lock: a released plan refuses rebuilds '
             '(target_json writes) until it is opened for revision.')
    release_snapshot = fields.Text(
        readonly=True,
        help='JSON snapshot of the last release (rev, user, RFQ/MO '
             'created/relinked/skipped summaries).')
    released_rev = fields.Integer(
        default=0, readonly=True,
        help='Release revision counter, bumped on every release.')
    needs_revision = fields.Boolean(
        default=False,
        help='Set by the purchase watcher when a plan-linked RFQ/PO '
             'is cancelled or deleted after release.')

    def write(self, vals):
        """Block rebuild writes on released plans.

        set_targets_and_rebuild (the single rebuild choke-point) writes
        target_json, so guarding that key locks the whole rebuild path
        including force=True. Unrelease first, then rebuild. The guard
        is deliberately unconditional: bundling target_json with a
        release_state change in one write() never unlocks the rebuild.
        @param vals: write values.
        @return: super result.
        """
        if 'target_json' in vals:
            locked = self.filtered(
                lambda p: p.release_state == 'released')
            if locked:
                raise UserError(_(
                    'Plan %s is released and locked. Open it for '
                    'revision first (Revize icin ac), then rebuild.')
                    % ', '.join(locked.mapped('name')))
        return super(MatiaProcurementPlanRelease, self).write(vals)

    def action_unrelease(self):
        """Open a released/closed plan for revision (unlock).

        @return: True.
        """
        for plan in self:
            if plan.release_state == 'draft':
                continue
            plan.write({'release_state': 'draft'})
            plan.message_post(body=_(
                'Release rev %s opened for revision by %s.')
                % (plan.released_rev, self.env.user.display_name))
        return True

    def action_close_release(self):
        """Mark a released plan closed (archival, stays locked).

        @return: True.
        """
        for plan in self:
            if plan.release_state != 'released':
                raise UserError(_(
                    'Only a released plan can be closed.'))
            plan.write({'release_state': 'closed'})
            plan.message_post(body=_(
                'Release rev %s closed by %s.')
                % (plan.released_rev, self.env.user.display_name))
        return True

    def action_open_release_wizard(self):
        """Open the single-button release wizard for this plan.

        @return: act_window opening matia.procurement.plan.release.wizard.
        """
        self.ensure_one()
        if self.release_state in ('released', 'closed'):
            raise UserError(_(
                'Plan is already released. Open it for revision first '
                'to release again.'))
        if not self.line_ids:
            raise UserError(_(
                'Nothing to release: explode and net the plan first.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Release: %s') % self.name,
            'res_model': 'matia.procurement.plan.release.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_plan_id': self.id,
                'default_mode': 'update',
            },
        }

    def action_open_tracking(self):
        """Open the live tracking screen for this plan.

        @return: act_window opening matia.procurement.plan.tracking.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tracking: %s') % self.name,
            'res_model': 'matia.procurement.plan.tracking',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_plan_id': self.id},
        }


class MatiaProcurementPlanReleaseWizard(models.TransientModel):
    """Single-button release wizard (preview + confirm)."""

    _name = 'matia.procurement.plan.release.wizard'
    _description = 'Matia Plan Single-Button Release Wizard'

    plan_id = fields.Many2one(
        'matia.procurement.plan', required=True, readonly=True)
    mode = fields.Selection([
        ('update', 'Update existing draft RFQs'),
        ('create', 'Always create new RFQs'),
    ], default='update', required=True,
        help='Update reuses the matching draft RFQ per supplier '
             'group and only opens a new RFQ where none qualifies. '
             'MO lines selected below are always deduped by origin.')
    summary = fields.Text(readonly=True)
    line_ids = fields.One2many(
        'matia.procurement.plan.release.wizard.line', 'wizard_id',
        string='Open lines')

    @api.model
    def default_get(self, fields_list):
        """Prefill summary + one wizard line per open plan line.

        RFQ-side selection is intentionally plan-wide: RFQ creation is
        coverage-aware and idempotent (update mode only touches draft
        RFQs), so per-line RFQ exclusion would silently under-order.
        The include flag applies to MO lines.
        @param fields_list: fields to fill.
        @return: defaults dict.
        """
        res = super(MatiaProcurementPlanReleaseWizard,
                    self).default_get(fields_list)
        plan_id = res.get('plan_id')
        if not plan_id:
            return res
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            return res
        mpp = self.env['matia.procurement.plan']
        groups, skipped = mpp._rfq_groups(plan)
        cov = mpp._rfq_coverage_map(env_sudo, plan)
        lines = []
        for line in plan.line_ids:
            route = line.route_type or 'unknown'
            if route in ('buy', 'subcontract'):
                rem = float((cov.get(line.id) or {}).get(
                    'remaining', line.order_qty) or 0.0)
                if rem > 1e-9:
                    lines.append((0, 0, {
                        'plan_line_id': line.id,
                        'product_name':
                            line.product_id.display_name or '',
                        'qty': rem,
                        'route': route,
                        'kind': 'rfq',
                        'detail': line.seller_id.display_name or _(
                            'No supplier'),
                        'include': True,
                    }))
            elif route == 'make' and (line.order_qty or 0.0) > 0 \
                    and not line.mo_id:
                lines.append((0, 0, {
                    'plan_line_id': line.id,
                    'product_name': line.product_id.display_name or '',
                    'qty': float(line.order_qty),
                    'route': route,
                    'kind': 'mo',
                    'detail': line.product_id.default_code or '',
                    'include': True,
                }))
        res['summary'] = _(
            '%d RFQ group(s), %d open line(s) shown, %d skipped '
            '(covered/no supplier/zero qty/make-with-MO). '
            '%d draft RFQ(s), %d MO(s) already linked to the plan.')
        res['summary'] = res['summary'] % (
            len(groups), len(lines), sum(skipped.values()),
            len(plan.purchase_order_ids), len(plan.mo_ids))
        res['line_ids'] = lines
        return res

    def action_confirm_release(self):
        """Create RFQs + MOs, stamp the snapshot, lock, open tracking.

        @return: act_window opening the tracking screen.
        """
        self.ensure_one()
        if not _mpp_can_create_docs(self):
            raise AccessError(_(
                'Only administrators can release a plan.'))
        mpp = self.env['matia.procurement.plan']
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(
            int(self.plan_id.id))
        if not plan.exists() or not plan.line_ids:
            raise UserError(_('Plan has no lines to release.'))
        if plan.release_state in ('released', 'closed'):
            raise UserError(_(
                'Plan is already released. Open it for revision first '
                'to release again.'))
        groups, skipped = mpp._rfq_groups(plan)
        if groups:
            rfq_res = mpp.action_create_draft_rfqs(
                plan.id, confirm=True, mode=self.mode or 'update')
        else:
            rfq_res = {'created': [], 'updated': [],
                       'skipped': skipped}
        mo_line_ids = self.line_ids.filtered(
            lambda w: w.kind == 'mo' and w.include).mapped(
            'plan_line_id.id')
        if mo_line_ids:
            mo_res = mpp.action_create_mos(plan.id, line_ids=mo_line_ids)
        else:
            mo_res = {'created': [], 'relinked': [], 'skipped': []}
        rfq_summary = {
            'created': rfq_res.get('created') or [],
            'updated': rfq_res.get('updated') or [],
            'skipped': rfq_res.get('skipped') or {},
        }
        mo_summary = {
            'created': mo_res.get('created') or [],
            'relinked': mo_res.get('relinked') or [],
            'skipped': mo_res.get('skipped') or [],
        }
        rev = (plan.released_rev or 0) + 1
        snapshot = build_snapshot_payload(
            rev, self.env.user.login, rfq_summary, mo_summary)
        plan.write({
            'release_state': 'released',
            'release_snapshot': json.dumps(snapshot),
            'released_rev': rev,
            'needs_revision': False,
        })
        # Chatter as the acting user (plan is a sudo record, so post
        # through a user-env browse to keep the author correct).
        self.env['matia.procurement.plan'].browse(plan.id).message_post(
            body=_(
                'Released rev %(rev)s by %(user)s: %(rfq)d RFQ(s) '
                'created, %(upd)d updated, %(mo)d MO(s) created, '
                '%(rel)d relinked.')
            % {'rev': rev, 'user': self.env.user.display_name,
               'rfq': len(rfq_summary['created']),
               'upd': len(rfq_summary['updated']),
               'mo': len(mo_summary['created']),
               'rel': len(mo_summary['relinked'])})
        return plan.action_open_tracking()


class MatiaProcurementPlanReleaseWizardLine(models.TransientModel):
    """One open plan line inside the release wizard."""

    _name = 'matia.procurement.plan.release.wizard.line'
    _description = 'Matia Plan Release Wizard Line'

    wizard_id = fields.Many2one(
        'matia.procurement.plan.release.wizard', required=True,
        ondelete='cascade')
    plan_line_id = fields.Many2one(
        'matia.procurement.plan.line', readonly=True)
    product_name = fields.Char(readonly=True)
    qty = fields.Float(readonly=True)
    route = fields.Char(readonly=True)
    kind = fields.Selection(
        [('rfq', 'RFQ'), ('mo', 'MO')], readonly=True)
    detail = fields.Char(readonly=True)
    include = fields.Boolean(
        default=True,
        help='Only MO lines honour this flag: excluded MO lines '
             'are not manufactured by this release.')


class MatiaProcurementPlanTracking(models.TransientModel):
    """Live per-line document tracking screen for a plan."""

    _name = 'matia.procurement.plan.tracking'
    _description = 'Matia Plan Release Tracking'

    plan_id = fields.Many2one(
        'matia.procurement.plan', required=True, readonly=True)
    attention_only = fields.Boolean(
        string='Only lines needing attention')
    line_ids = fields.One2many(
        'matia.procurement.plan.tracking.line', 'wizard_id',
        string='Lines')

    @api.model
    def default_get(self, fields_list):
        """Snapshot all plan lines with live document states.

        @param fields_list: fields to fill.
        @return: defaults dict.
        """
        res = super(MatiaProcurementPlanTracking,
                    self).default_get(fields_list)
        plan_id = res.get('plan_id')
        if not plan_id:
            return res
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            return res
        res['line_ids'] = self._tracking_lines(plan)
        return res

    @api.model
    def _tracking_lines(self, plan):
        """Build O2M commands for every plan line.

        @param plan: matia.procurement.plan record (sudo env).
        @return: list of (0, 0, vals) commands.
        """
        cmds = []
        for line in plan.line_ids:
            po = line.purchase_order_id
            mo = line.mo_id
            code, attn = line_tracking_status(
                line.route_type or 'unknown',
                po.state if po else None,
                mo.state if mo else None)
            cmds.append((0, 0, {
                'plan_line_id': line.id,
                'code': line.product_id.default_code or '',
                'product_name': line.product_id.display_name or '',
                'qty': float(line.order_qty or 0.0),
                'route': line.route_type or '',
                'rfq_name': po.name if po else '',
                'rfq_state': po.state if po else '',
                'mo_name': mo.name if mo else '',
                'mo_state': mo.state if mo else '',
                'status': code,
                'attention': attn,
                'selected': True,
            }))
        return cmds

    @api.onchange('attention_only')
    def _onchange_attention_only(self):
        """Filter the lines tree to attention lines when asked.

        @return: domain dict for line_ids (or empty).
        """
        if self.attention_only:
            return {'domain': {'line_ids': [('attention', '=', True)]}}
        return {'domain': {'line_ids': []}}

    def action_refresh(self):
        """Rebuild the lines snapshot from live document states.

        @return: act_window reopening this tracking screen.
        """
        self.ensure_one()
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(
            int(self.plan_id.id))
        cmds = self._tracking_lines(plan)
        self.line_ids.unlink()
        self.write({'line_ids': cmds})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tracking: %s') % plan.name,
            'res_model': 'matia.procurement.plan.tracking',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_tracking_send(self):
        """Confirm selected draft RFQs (draft -> purchase order).

        Per-PO errors are collected, never abort the batch: the
        summary is posted to the plan chatter.
        @return: refreshed tracking screen.
        """
        self.ensure_one()
        if not _mpp_can_create_docs(self):
            raise AccessError(_(
                'Only administrators can confirm RFQs.'))
        env_sudo = _mpp_env_sudo(self)
        ok, failed = [], []
        for tline in self.line_ids.filtered('selected'):
            line = tline.plan_line_id
            po = line.purchase_order_id
            if not po or po.state != 'draft':
                continue
            try:
                env_sudo['purchase.order'].browse(
                    po.id).button_confirm()
                ok.append(po.name)
            except Exception as exc:
                _logger.warning(
                    'MPP tracking confirm failed for %s: %s',
                    po.name, exc)
                failed.append('%s (%s)' % (po.name, exc))
        plan = env_sudo['matia.procurement.plan'].browse(
            int(self.plan_id.id))
        self.env['matia.procurement.plan'].browse(plan.id).message_post(
            body=_(
                'Tracking confirm by %s: %d RFQ(s) confirmed%s%s.')
            % (self.env.user.display_name, len(ok),
               '; failed: ' + ', '.join(failed) if failed else '',
               ': ' + ', '.join(ok) if ok else ''))
        return self.action_refresh()

    def action_tracking_unrelease(self):
        """Open the plan for revision from the tracking screen.

        @return: refreshed tracking screen.
        """
        self.ensure_one()
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(
            int(self.plan_id.id))
        plan.action_unrelease()
        return self.action_refresh()

    def action_tracking_close(self):
        """Close the release from the tracking screen.

        @return: refreshed tracking screen.
        """
        self.ensure_one()
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(
            int(self.plan_id.id))
        plan.action_close_release()
        return self.action_refresh()


class MatiaProcurementPlanTrackingLine(models.TransientModel):
    """One tracked plan line (live document states snapshot)."""

    _name = 'matia.procurement.plan.tracking.line'
    _description = 'Matia Plan Release Tracking Line'

    wizard_id = fields.Many2one(
        'matia.procurement.plan.tracking', required=True,
        ondelete='cascade')
    plan_line_id = fields.Many2one(
        'matia.procurement.plan.line', readonly=True)
    code = fields.Char(readonly=True)
    product_name = fields.Char(readonly=True)
    qty = fields.Float(readonly=True)
    route = fields.Char(readonly=True)
    rfq_name = fields.Char(readonly=True)
    rfq_state = fields.Char(readonly=True)
    mo_name = fields.Char(readonly=True)
    mo_state = fields.Char(readonly=True)
    status = fields.Selection([
        ('no_rfq', 'No RFQ'),
        ('rfq_draft', 'RFQ draft'),
        ('rfq_sent', 'RFQ sent'),
        ('po_confirmed', 'PO confirmed'),
        ('po_cancelled', 'PO cancelled'),
        ('no_mo', 'No MO'),
        ('mo_draft', 'MO draft'),
        ('mo_open', 'MO open'),
        ('mo_done', 'MO done'),
        ('mo_cancelled', 'MO cancelled'),
        ('unknown', 'Unknown'),
    ], readonly=True)
    attention = fields.Boolean(readonly=True)
    selected = fields.Boolean(default=True)
