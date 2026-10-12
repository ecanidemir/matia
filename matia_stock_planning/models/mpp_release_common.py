# -*- coding: utf-8 -*-
"""Pure (stdlib-only) helpers for the single-button Release flow.

This module MUST NOT import odoo: it is unit-tested locally via
scratch/test_mpp_release_common.py through direct importlib loading.
All functions operate on plain dicts/strings so the wizard, the
tracking screen and the release snapshot share one mapping contract.
"""
from datetime import datetime


def line_tracking_status(route_type, po_state, mo_state):
    """Tracking status of one plan line from linked document states.

    Pure function over strings: the tracking wizard feeds
    line.purchase_order_id.state / line.mo_id.state (or None when
    unlinked) and renders the returned code + attention flag.

    @param route_type: 'make', 'buy' or 'subcontract' (subcontract
        lines are RFQ-covered like buy lines).
    @param po_state: purchase.order state or None.
    @param mo_state: mrp.production state or None.
    @return: (status_code, needs_attention_bool).
    """
    if route_type == 'make':
        if not mo_state:
            return ('no_mo', True)
        if mo_state == 'draft':
            return ('mo_draft', False)
        if mo_state in ('confirmed', 'progress', 'to_close'):
            return ('mo_open', False)
        if mo_state == 'done':
            return ('mo_done', False)
        if mo_state == 'cancel':
            return ('mo_cancelled', True)
        return ('mo_open', False)
    if route_type in ('buy', 'subcontract'):
        if not po_state:
            return ('no_rfq', True)
        if po_state == 'draft':
            return ('rfq_draft', False)
        if po_state in ('sent', 'to approve'):
            return ('rfq_sent', False)
        if po_state in ('purchase', 'done'):
            return ('po_confirmed', False)
        if po_state == 'cancel':
            return ('po_cancelled', True)
        return ('rfq_draft', False)
    return ('unknown', True)


def build_snapshot_payload(rev, user, rfq, mo):
    """Build the JSON-serializable release snapshot payload.

    @param rev: release revision number.
    @param user: login name performing the release.
    @param rfq: {'created': [...], 'skipped': [...] (...) any JSON-able}.
    @param mo: {'created': [...], 'relinked': [...], 'skipped': [...]}.
    @return: dict ready for json.dumps into release_snapshot.
    """
    return {
        'rev': int(rev or 1),
        'date': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        'user': user or '',
        'rfq': rfq or {},
        'mo': mo or {},
    }
