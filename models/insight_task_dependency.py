# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class InsightTaskDependency(models.Model):
    _name = 'insight.task.dependency'
    _description = 'Tipo de dependencia TJ3 por arista (override de tj_dependency_type)'
    _rec_name = 'depends_on_id'

    task_id = fields.Many2one(
        'project.task', string='Tarea', required=True, ondelete='cascade', index=True,
    )
    depends_on_id = fields.Many2one(
        'project.task', string='Bloqueante', required=True, ondelete='cascade',
        help='Debe ser una de las tareas ya listadas en depend_on_ids de la '
             'tarea — este registro no crea la dependencia en sí (eso lo '
             'sigue manejando el campo nativo de Odoo), solo le pone un '
             'tipo TJ3 distinto del default de la tarea (tj_dependency_type) '
             'a esa arista puntual.',
    )
    dependency_type = fields.Selection(
        [('FS', 'Finish→Start'), ('SS', 'Start→Start'), ('FF', 'Finish→Finish')],
        string='Tipo de dependencia TJ', required=True, default='FS',
    )

    _sql_constraints = [
        ('task_depends_on_uniq', 'unique(task_id, depends_on_id)',
         'Ya hay un tipo de dependencia definido para esta arista.'),
    ]

    @api.constrains('task_id', 'depends_on_id')
    def _check_depends_on_is_a_real_dependency(self):
        for rec in self:
            if rec.depends_on_id not in rec.task_id.depend_on_ids:
                raise ValidationError(_(
                    '"%(dep)s" no es un bloqueante de "%(task)s" — agregalo '
                    'primero en el campo de dependencias de la tarea antes '
                    'de definirle un tipo TJ3 puntual.'
                ) % {'dep': rec.depends_on_id.name, 'task': rec.task_id.name})
