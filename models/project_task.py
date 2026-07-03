# -*- coding: utf-8 -*-
from odoo import _, models, fields, api


class ProjectTask(models.Model):
    _inherit = 'project.task'

    is_milestone = fields.Boolean(string='Hito')
    tj_dependency_type = fields.Selection(
        [('FS', 'Finish→Start'), ('SS', 'Start→Start'), ('FF', 'Finish→Finish')],
        string='Tipo de dependencia TJ',
        default='FS',
    )
    start_scheduled = fields.Datetime(
        string='Inicio planificado', compute='_compute_scheduled', store=True,
    )
    end_scheduled = fields.Datetime(
        string='Fin planificado', compute='_compute_scheduled', store=True,
    )
    is_critical_path = fields.Boolean(
        string='Camino crítico', compute='_compute_scheduled', store=True,
    )
    bsi = fields.Char(
        string='BSI', compute='_compute_scheduled', store=True,
    )
    blocked = fields.Boolean(
        string='Bloqueada', tracking=True,
        help='Impedimento temporal que impide continuar el trabajo. No '
             'reemplaza stage_id ni state: puede coexistir con cualquier '
             'etapa/estado activo. El motivo se registra como comentario '
             'en el chatter o en el parte de horas, no en este campo.',
    )

    @api.depends('project_id.scenario_ids', 'project_id.scenario_ids.schedule_ids')
    def _compute_scheduled(self):
        for task in self:
            baseline = task.project_id.scenario_ids.filtered('is_baseline')[:1]
            if not baseline:
                task.start_scheduled = False
                task.end_scheduled = False
                task.is_critical_path = False
                task.bsi = False
                continue
            schedule = self.env['insight.task.schedule'].search([
                ('task_id', '=', task.id),
                ('scenario_id', '=', baseline.id),
            ], limit=1)
            task.start_scheduled = schedule.start_scheduled
            task.end_scheduled = schedule.end_scheduled
            task.is_critical_path = schedule.is_critical_path
            task.bsi = schedule.bsi

    @api.model
    def _cron_flag_changes_requested(self):
        """Pasa a 'Cambios solicitados' las tareas cuyo plan quedó invalidado
        por la realidad: se venció la fecha de fin planificada (end_scheduled,
        calculada por el motor CPM), o -si son camino crítico- se agotaron
        las horas asignadas. En una tarea sin holgura, agotar el presupuesto
        de horas también corre el cronograma aguas abajo; si no es crítica,
        el exceso de horas queda solo como alerta visual en el chip del
        systray, sin forzar un replanificado."""
        open_states = ('01_in_progress', '03_approved', '04_waiting_normal')
        overdue = self.search([
            ('state', 'in', open_states),
            ('end_scheduled', '!=', False),
            ('end_scheduled', '<', fields.Datetime.now()),
        ])
        over_budget = self.search([
            ('state', 'in', open_states),
            ('is_critical_path', '=', True),
            ('allocated_hours', '>', 0),
            ('remaining_hours', '<=', 0),
        ])
        (overdue | over_budget).write({'state': '02_changes_requested'})

    # ── Decoración TJ3 sobre el contrato work.item.mixin ────────────────────
    # La implementación genérica (candidatos, cierre → parte de horas,
    # cronómetro) vive en work_item_task; acá solo se agrega ⚡ camino
    # crítico / ❗ revisión pendiente, y el efecto de `blocked` al cerrar.

    def _work_item_label(self):
        label = super()._work_item_label()
        if self.is_critical_path:
            label['icon'] = '⚡'
            label['css_class'] = 'text-danger fw-bold'
        elif self.state == '02_changes_requested':
            label['icon'] = '❗'
            label['css_class'] = 'text-warning fw-bold'
        return label

    @api.model
    def _work_item_candidates(self):
        candidates = super()._work_item_candidates()
        if not candidates:
            return candidates
        tasks_by_id = {t.id: t for t in self.browse([c['res_id'] for c in candidates])}
        for candidate in candidates:
            task = tasks_by_id.get(candidate['res_id'])
            if not task:
                continue
            if task.is_critical_path:
                candidate['icon'] = '⚡'
                candidate['css_class'] = 'text-danger fw-bold'
            elif task.state == '02_changes_requested':
                candidate['icon'] = '❗'
                candidate['css_class'] = 'text-warning fw-bold'
        return candidates

    def _work_item_close(self, start_datetime, intent_note, outcome_note, outcome_blocked):
        super()._work_item_close(start_datetime, intent_note, outcome_note, outcome_blocked)
        if outcome_blocked:
            self.blocked = True
