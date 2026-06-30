# -*- coding: utf-8 -*-
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    tj_microservice_url = fields.Char(
        config_parameter='insight_project.tj_microservice_url',
        string='URL del microservicio TaskJuggler',
    )
    tj_microservice_timeout = fields.Integer(
        config_parameter='insight_project.tj_microservice_timeout',
        string='Timeout (segundos)',
    )
