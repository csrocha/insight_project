# -*- coding: utf-8 -*-
import requests

from odoo import _, fields, models
from odoo.exceptions import UserError

_DEFAULT_TIMEOUT = 120


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

    def get_values(self):
        res = super().get_values()
        if not res.get('tj_microservice_timeout'):
            res['tj_microservice_timeout'] = _DEFAULT_TIMEOUT
        return res

    def action_test_tj_connection(self):
        url = (
            self.env['ir.config_parameter']
            .sudo()
            .get_param('insight_project.tj_microservice_url')
        )
        if not url:
            raise UserError(
                _('Configure la URL del microservicio antes de probar la conexión.')
            )
        health_url = url.rstrip('/') + '/health'
        try:
            response = requests.get(health_url, timeout=10)
            response.raise_for_status()
            msg = _('Microservicio TJ3 disponible en %s') % url
            msg_type = 'success'
        except requests.exceptions.ConnectionError:
            msg = _('No se pudo conectar con el microservicio en %s') % url
            msg_type = 'warning'
        except requests.exceptions.Timeout:
            msg = _('Timeout al conectar con el microservicio en %s') % url
            msg_type = 'warning'
        except requests.exceptions.HTTPError as e:
            msg = _('El microservicio respondió con error: %s') % str(e)
            msg_type = 'warning'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Test de conexión TJ3'),
                'message': msg,
                'type': msg_type,
                'sticky': False,
            },
        }
