# -*- coding: utf-8 -*-
from odoo import models, fields


class InsightScenarioProject(models.Model):
    """Vínculo entre un escenario (compartible) y uno de los proyectos que lo
    usa. is_baseline vive acá, no en insight.scenario: un mismo escenario
    puede ser el baseline del Proyecto A y no serlo del Proyecto B. Las
    acciones que antes vivían en insight.scenario y necesitaban "el" proyecto
    del escenario (generar reportes, export TJP) también viven acá — ver
    action_generate_reports."""
    _name = 'insight.scenario.project'
    _description = 'Vínculo entre un escenario y uno de sus proyectos'
    _order = 'project_id, is_baseline desc'

    scenario_id = fields.Many2one('insight.scenario', required=True, ondelete='cascade')
    project_id = fields.Many2one('project.project', required=True, ondelete='cascade')
    is_baseline = fields.Boolean()

    total_cost = fields.Float(related='scenario_id.total_cost', readonly=True)
    computed_end_date = fields.Datetime(related='scenario_id.computed_end_date', readonly=True)
    peak_resources = fields.Integer(related='scenario_id.peak_resources', readonly=True)
    selection_score = fields.Float(related='scenario_id.selection_score', readonly=True)
    extra_cost = fields.Float(related='scenario_id.extra_cost', readonly=True)
    grand_total_cost = fields.Float(related='scenario_id.grand_total_cost', readonly=True)

    _sql_constraints = [
        ('scenario_project_uniq', 'unique(scenario_id, project_id)',
         'Este escenario ya está vinculado a este proyecto.'),
    ]

    def action_view_cost_reports(self):
        return self.scenario_id.action_view_cost_reports()

    def action_generate_reports(self):
        """El botón real vive acá (por vínculo escenario-proyecto): a
        diferencia de insight.scenario (que puede estar vinculado a más de un
        proyecto), acá project_id/scenario_id no son ambiguos. project.project
        solo expone un wrapper de conveniencia que resuelve el baseline (ver
        project.project.action_generate_reports). Corre cada reporte
        aplicable: costo y Gantt siempre (el Gantt no es por escenario,
        agrega todos los del proyecto — ver
        project.project._compute_and_save_gantt_report); desviación
        baseline vs. real solo si el proyecto está en ejecución (necesita
        avance real, no solo proyección — ver
        project.project._compute_and_save_deviation_report, que también
        valida esto por su cuenta)."""
        self.ensure_one()
        result = self.project_id._compute_and_save_cost_reports(self.scenario_id)
        self.project_id._compute_and_save_gantt_report()
        if self.project_id.state == 'progress':
            self.project_id._compute_and_save_deviation_report(self.scenario_id)
        return result
