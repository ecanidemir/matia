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

    # NOTE: _name is required explicitly with list-form _inherit. Without
    # it Odoo builds a shadow new model named after this class, copying
    # all stored fields incl. purchase_order_ids (same M2M table) -> the
    # registry dies with "Many2many fields ... use the same table and
    # columns" and every request 500s. Explicit _name forces extension.
    _name = 'matia.procurement.plan'
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

    # ---- Dashboard (JS) RPCs: JSON-serializable dicts, explicit plan_id
    # (@api.model like action_create_mos, so the JS client calls them
    # with [plan_id, ...] without recordset-dispatch ambiguity). ----

    @api.model
    def _cleanup_release_transient_selection_rows(self):
        """One-shot upgrade helper: drop selection rows of deleted models.

        Removes ``ir.model.fields.selection`` rows left behind by the
        deleted release wizard/tracking transient models
        (v15.0.2.10.x removed them when Release moved to the dashboard).
        Plain ORM unlink cannot be used here:
        ``ir.model.fields.selection._process_ondelete`` resolves
        ``self.env[selection.field_id.model]`` which raises ``KeyError``
        because those models no longer exist in the registry (this broke
        the upgrade at ``ir.model.data._process_end``). Raw SQL bypasses
        the ORM unlink path entirely. Safe no-op on fresh installs.
        Called once from ``procurement_plan_release_cleanup.xml``.
        @return: number of deleted rows.
        """
        stale_models = (
            'matia.procurement.plan.release.wizard',
            'matia.procurement.plan.release.wizard.line',
            'matia.procurement.plan.tracking',
            'matia.procurement.plan.tracking.line',
        )
        self.env.cr.execute(
            """
            DELETE FROM ir_model_fields_selection AS sel
            USING ir_model_fields AS fld
            WHERE sel.field_id = fld.id
              AND fld.model IN %s
            """,
            (stale_models,),
        )
        return self.env.cr.rowcount

    @api.model
    def _release_preview_data(self, plan):
        """Shared preview computation (wizard default_get + JS RPC).

        RFQ-side selection is intentionally plan-wide (see wizard
        default_get docstring); the include flag applies to MO lines.
        @param plan: matia.procurement.plan record (sudo env).
        @return: (lines, summary_text, counts) where lines is a list of
            plain dicts (plan_line_id, product_name, qty, route, kind,
            detail, include).
        """
        env_sudo = _mpp_env_sudo(self)
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
                    lines.append({
                        'plan_line_id': line.id,
                        'product_name':
                            line.product_id.display_name or '',
                        'qty': rem,
                        'route': route,
                        'kind': 'rfq',
                        'detail': line.seller_id.display_name or _(
                            'No supplier'),
                        'include': True,
                    })
            elif route == 'make' and (line.order_qty or 0.0) > 0 \
                    and not line.mo_id:
                lines.append({
                    'plan_line_id': line.id,
                    'product_name':
                        line.product_id.display_name or '',
                    'qty': float(line.order_qty),
                    'route': route,
                    'kind': 'mo',
                    'detail': line.product_id.default_code or '',
                    'include': True,
                })
        summary = _(
            '%d RFQ group(s), %d open line(s) shown, %d skipped '
            '(covered/no supplier/zero qty/make-with-MO). '
            '%d draft RFQ(s), %d MO(s) already linked to the plan.')
        summary = summary % (
            len(groups), len(lines), sum(skipped.values()),
            len(plan.purchase_order_ids), len(plan.mo_ids))
        counts = {
            'groups': len(groups),
            'skipped': sum(skipped.values()),
            'draft_rfqs': len(plan.purchase_order_ids),
            'mos': len(plan.mo_ids),
        }
        return lines, summary, counts

    @api.model
    def get_release_preview(self, plan_id):
        """Release preview for the dashboard (tab 3).

        @param plan_id: plan id.
        @return: dict with release_state/released_rev/needs_revision,
            summary text, counts and open lines.
        """
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            raise UserError(_('Plan not found.'))
        mpp = env_sudo['matia.procurement.plan']
        lines, summary, counts = self._release_preview_data(plan)
        # Dashboard contract (see _releasePreviewHtml in
        # procurement_plan.js): grouped RFQ rows with an estimated USD
        # total + a create/update action, and checkbox MO rows.
        # _rfq_groups subtotals are in group currency, so convert to
        # USD for the estimate (best effort: raw subtotal on failure).
        usd = env_sudo['res.currency'].search(
            [('name', '=', 'USD')], limit=1)
        groups, _skipped = mpp._rfq_groups(plan)
        groups_out = []
        for grp in groups:
            updatable = mpp._rfq_find_updatable(
                plan, grp['seller_id'], grp['company_id'],
                grp['currency_id'])
            total = grp['subtotal']
            cur = env_sudo['res.currency'].browse(
                grp['currency_id'])
            if usd and cur.exists() and cur.id != usd.id:
                try:
                    total = cur._convert(
                        total, usd,
                        env_sudo['res.company'].browse(
                            grp['company_id']),
                        fields.Date.today())
                except Exception:
                    total = grp['subtotal']
            groups_out.append({
                'name': '%s (%s / %s)' % (
                    grp['seller_name'], grp['currency_name'],
                    grp['company']),
                'line_count': len(grp['lines']),
                'total_usd': round(total or 0.0, 2),
                'action': 'update' if updatable else 'create',
            })
        mo_eligible = [{
            'line_id': line['plan_line_id'],
            'product': line['product_name'],
            'qty': line['qty'],
        } for line in lines if line.get('kind') == 'mo']
        return {
            'plan_id': plan.id,
            'release_state': plan.release_state,
            'released_rev': plan.released_rev or 0,
            'needs_revision': bool(plan.needs_revision),
            'summary': summary,
            'group_count': counts['groups'],
            'skipped_count': counts['skipped'],
            'draft_rfq_count': counts['draft_rfqs'],
            'mo_count': counts['mos'],
            'groups': groups_out,
            'mo_eligible': mo_eligible,
            'lines': lines,
        }

    @api.model
    def action_release_confirm(self, plan_id, mode='update',
                               include_mo_line_ids=None):
        """Confirm a release from the dashboard (no wizard record).

        @param plan_id: plan id.
        @param mode: 'update' (reuse matching draft RFQs) or 'create'.
        @param include_mo_line_ids: plan line ids to manufacture
            (MO-side include flags from the preview; RFQ side is always
            plan-wide). Intersected with eligible make lines server-side.
        @return: dict with rev + created/updated/relinked name lists.
        """
        if not _mpp_can_create_docs(self):
            raise AccessError(_(
                'Only administrators can release a plan.'))
        mpp = self.env['matia.procurement.plan']
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists() or not plan.line_ids:
            raise UserError(_('Plan has no lines to release.'))
        if plan.release_state in ('released', 'closed'):
            raise UserError(_(
                'Plan is already released. Open it for revision first '
                'to release again.'))
        groups, skipped = mpp._rfq_groups(plan)
        if groups:
            rfq_res = mpp.action_create_draft_rfqs(
                plan.id, confirm=True, mode=mode or 'update')
        else:
            rfq_res = {'created': [], 'updated': [],
                       'skipped': skipped}
        wanted = set(int(x) for x in (include_mo_line_ids or []))
        mo_line_ids = plan.line_ids.filtered(
            lambda l: l.id in wanted and l.route_type == 'make'
            and (l.order_qty or 0.0) > 0 and not l.mo_id).ids
        if mo_line_ids:
            mo_res = mpp.action_create_mos(plan.id, line_ids=mo_line_ids)
        else:
            mo_res = {'created': [], 'relinked': [], 'skipped': []}

        def _names(items):
            out = []
            for item in (items or []):
                if isinstance(item, dict):
                    out.append(item.get('name') or
                               '#%s' % item.get('id'))
                else:
                    out.append(str(item))
            return out

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
        return {
            'rev': rev,
            'rfq_created': _names(rfq_summary['created']),
            'rfq_updated': _names(rfq_summary['updated']),
            'mo_created': _names(mo_summary['created']),
            'mo_relinked': _names(mo_summary['relinked']),
        }

    @api.model
    def get_release_tracking(self, plan_id, attention_only=False):
        """Live per-line tracking data for the dashboard (tab 3).

        @param plan_id: plan id.
        @param attention_only: only return attention lines.
        @return: dict with release_state/released_rev/needs_revision,
            parsed snapshot header and tracking lines.
        """
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            raise UserError(_('Plan not found.'))
        lines = self._release_tracking_lines_vals(plan)
        if attention_only:
            lines = [l for l in lines if l.get('attention')]
        snapshot = {}
        if plan.release_snapshot:
            try:
                snapshot = json.loads(plan.release_snapshot)
            except ValueError:
                snapshot = {}
        return {
            'plan_id': plan.id,
            'release_state': plan.release_state,
            'released_rev': plan.released_rev or 0,
            'needs_revision': bool(plan.needs_revision),
            'snapshot': snapshot,
            'attention_count': sum(1 for l in lines
                                   if l.get('attention')),
            'line_count': len(lines),
            'lines': lines,
        }

    @api.model
    def action_release_confirm_docs(self, plan_id):
        """Confirm all draft plan RFQs (dashboard tracking button).

        Per-PO errors are collected, never abort the batch; the summary
        is posted to the plan chatter.
        @param plan_id: plan id.
        @return: dict with confirmed/failed name lists.
        """
        if not _mpp_can_create_docs(self):
            raise AccessError(_(
                'Only administrators can confirm RFQs.'))
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            raise UserError(_('Plan not found.'))
        ok, failed = [], []
        for po in plan.purchase_order_ids.filtered(
                lambda p: p.state == 'draft'):
            try:
                env_sudo['purchase.order'].browse(po.id).button_confirm()
                ok.append(po.name)
            except Exception as exc:
                _logger.warning(
                    'MPP dashboard confirm failed for %s: %s',
                    po.name, exc)
                failed.append('%s (%s)' % (po.name, exc))
        self.env['matia.procurement.plan'].browse(plan.id).message_post(
            body=_(
                'Dashboard confirm by %s: %d RFQ(s) confirmed%s%s.')
            % (self.env.user.display_name, len(ok),
               '; failed: ' + ', '.join(failed) if failed else '',
               ': ' + ', '.join(ok) if ok else ''))
        return {'confirmed': ok, 'failed': failed}

    @api.model
    def action_release_unrelease(self, plan_id):
        """Dashboard wrapper for action_unrelease (unlock for revision).

        @param plan_id: plan id.
        @return: True.
        """
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            raise UserError(_('Plan not found.'))
        plan.action_unrelease()
        return True

    @api.model
    def action_release_close(self, plan_id):
        """Dashboard wrapper for action_close_release.

        @param plan_id: plan id.
        @return: True.
        """
        env_sudo = _mpp_env_sudo(self)
        plan = env_sudo['matia.procurement.plan'].browse(int(plan_id))
        if not plan.exists():
            raise UserError(_('Plan not found.'))
        plan.action_close_release()
        return True

    @api.model
    def _release_tracking_lines_vals(self, plan):
        """Plain-dict tracking lines for the dashboard (tab 3).

        @param plan: matia.procurement.plan record (sudo env).
        @return: list of dicts (plan_line_id, code, product_name, qty,
            route, rfq_name, rfq_state, mo_name, mo_state, status,
            attention, selected).
        """
        vals = []
        for line in plan.line_ids:
            po = line.purchase_order_id
            mo = line.mo_id
            if not (line.order_qty or 0.0) > 0:
                # Zero-need line: nothing to order, never attention.
                # (Otherwise fully-covered plans show a wall of red
                # rows for lines that need nothing.)
                code, attn = 'no_need', False
            else:
                code, attn = line_tracking_status(
                    line.route_type or 'unknown',
                    po.state if po else None,
                    mo.state if mo else None)
            vals.append({
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
            })
        return vals
