# -*- coding: utf-8 -*-
from odoo import models, fields


class ResUsers(models.Model):
    _inherit = 'res.users'

    matia_capacity_targets = fields.Char(
        string='Capacity Plan Target Columns',
        default='[]',
        help='Capacity dashboard dynamic target-device columns as a JSON '
             'list (e.g. [50, 100]). Per-user UI preference, managed by '
             'matia.stock.planning get/set_my_capacity_targets; never '
             'shown in any view.')
