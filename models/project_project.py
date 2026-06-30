# -*- coding: utf-8 -*-
from odoo import models, fields


class ProjectProject(models.Model):
    _inherit = 'project.project'

    tj_now = fields.Date(string='Fecha base del plan')
    tj_timezone = fields.Char(
        string='Zona horaria TJ',
        default='America/Argentina/Buenos_Aires',
    )
    is_tj_enabled = fields.Boolean(string='Habilitar integración TaskJuggler')
    scenario_ids = fields.One2many('insight.scenario', 'project_id', string='Escenarios')
    resource_ids = fields.One2many('insight.resource', 'project_id', string='Recursos')
    schedule_dirty = fields.Boolean(string='Schedule desactualizado')
    last_scheduled = fields.Datetime(string='Último schedule', readonly=True)

    def action_export_tjp(self):
        self.ensure_one()
        # TODO: return binary file download action
        tjp_content = self._generate_tjp()
        return {
            'type': 'ir.actions.act_window_close',
        }

    def action_run_schedule(self):
        self.ensure_one()
        # TODO: call TJ3 microservice via HTTP and import CSV results
        pass

    def _generate_tjp(self):
        self.ensure_one()
        lines = []
        lines += self._tjp_project_header()
        for res in self.resource_ids:
            lines += self._tjp_resource_block(res)
        for scenario in self.scenario_ids:
            lines += self._tjp_scenario_supplement(scenario)
        for task in self.task_ids.filtered(lambda t: not t.parent_id):
            lines += self._tjp_task_block(task, depth=0)
        lines += self._tjp_reports()
        return '\n'.join(lines)

    def _tjp_project_header(self):
        return []

    def _tjp_resource_block(self, res):
        return []

    def _tjp_scenario_supplement(self, scenario):
        return []

    def _tjp_task_block(self, task, depth=0):
        return []

    def _tjp_reports(self):
        return []

    def _import_schedule_csv(self, csv_content):
        pass
