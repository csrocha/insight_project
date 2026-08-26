# -*- coding: utf-8 -*-
"""Tests para BACKLOG.md ítem 8: clonar proyecto + calibración histórica de
allocated_hours vía la mediana de horas reales de la cadena de clones (ver
project.task.copy()/_get_calibration_chain y
project.project.action_clone()/_seed_baseline_scenario)."""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestActionCloneGuard(TransactionCase):

    def test_action_clone_requires_done_state(self):
        project = self.env['project.project'].create({'name': 'Guard Project'})
        for state in ('draft', 'evaluation', 'progress'):
            project.state = state
            with self.assertRaises(UserError):
                project.action_clone()


class TestActionCloneCalibration(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.analytic_plan = cls.env['account.analytic.plan'].create({
            'name': 'Clone Test Plan',
        })
        cls.analytic_account = cls.env['account.analytic.account'].create({
            'name': 'Clone Test Analytic', 'plan_id': cls.analytic_plan.id,
        })
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Clone Resource',
            'login': 'clone_resource@insight.test',
            'email': 'clone_resource@insight.test',
            'groups_id': [(4, cls.env.ref('base.group_user').id)],
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Clone Resource', 'user_id': cls.user.id,
        })

    def _project(self, **vals):
        vals.setdefault('name', 'Clone Project')
        vals.setdefault('analytic_account_id', self.analytic_account.id)
        return self.env['project.project'].create(vals)

    def _log_time(self, task, hours, date='2026-07-01'):
        return self.env['account.analytic.line'].create({
            'name': '/', 'account_id': self.analytic_account.id,
            'task_id': task.id, 'employee_id': self.employee.id,
            'date': date, 'unit_amount': hours,
        })

    def test_action_clone_creates_draft_project_calibrated(self):
        project = self._project()
        project.state = 'done'
        task = self.env['project.task'].create({
            'name': 'Fase 1', 'project_id': project.id, 'allocated_hours': 100.0,
            'user_ids': [(6, 0, [self.user.id])],
        })
        self._log_time(task, 120.0)

        result = project.action_clone()
        new_project = self.env['project.project'].browse(result['res_id'])
        self.assertEqual(new_project.state, 'draft')
        self.assertEqual(new_project.template_project_id, project)

        new_task = self.env['project.task'].search([('project_id', '=', new_project.id)])
        self.assertEqual(len(new_task), 1)
        self.assertEqual(new_task.source_task_id, task)
        self.assertEqual(new_task.allocated_hours, 120.0)

    def test_action_clone_chain_median_two_generations(self):
        project = self._project(name='Template Project')
        project.state = 'done'
        task = self.env['project.task'].create({
            'name': 'Fase 1', 'project_id': project.id, 'allocated_hours': 100.0,
            'user_ids': [(6, 0, [self.user.id])],
        })
        self._log_time(task, 90.0)

        clone1 = self.env['project.project'].browse(project.action_clone()['res_id'])
        task_clone1 = self.env['project.task'].search([('project_id', '=', clone1.id)])
        self.assertEqual(task_clone1.allocated_hours, 90.0, 'mediana de una sola muestra')

        clone1.state = 'done'
        self._log_time(task_clone1, 110.0, date='2026-08-01')

        clone2 = self.env['project.project'].browse(clone1.action_clone()['res_id'])
        task_clone2 = self.env['project.task'].search([('project_id', '=', clone2.id)])
        self.assertEqual(task_clone2.source_task_id, task_clone1)
        self.assertEqual(task_clone2.allocated_hours, 100.0, 'mediana de [90, 110]')

    def test_action_clone_falls_back_without_timesheets(self):
        project = self._project()
        project.state = 'done'
        task = self.env['project.task'].create({
            'name': 'Fase 1', 'project_id': project.id, 'allocated_hours': 50.0,
            'user_ids': [(6, 0, [self.user.id])],
        })

        new_project = self.env['project.project'].browse(project.action_clone()['res_id'])
        new_task = self.env['project.task'].search([('project_id', '=', new_project.id)])
        self.assertEqual(new_task.allocated_hours, 50.0)

    def test_action_clone_resets_scenarios_seeds_baseline_efficiency(self):
        project = self._project()
        old_scenario = self.env['insight.scenario'].create({
            'name': 'Old',
            'project_link_ids': [(0, 0, {'project_id': project.id, 'is_baseline': True})],
        })
        task = self.env['project.task'].create({
            'name': 'Fase 1', 'project_id': project.id, 'allocated_hours': 40.0,
            'user_ids': [(6, 0, [self.user.id])],
        })
        self.env['insight.task.schedule'].create({
            'task_id': task.id, 'scenario_id': old_scenario.id, 'cost': 1000.0,
        })
        self._log_time(task, 40.0)
        project.state = 'done'

        new_project = self.env['project.project'].browse(project.action_clone()['res_id'])
        self.assertEqual(len(new_project.scenario_link_ids), 1)
        baseline_link = new_project.scenario_link_ids
        baseline = baseline_link.scenario_id
        self.assertEqual(baseline.name, 'Baseline')
        self.assertTrue(baseline_link.is_baseline)
        self.assertEqual(len(baseline.efficiency_ids), 1)
        self.assertEqual(baseline.efficiency_ids.user_id, self.user)
        self.assertEqual(baseline.efficiency_ids.efficiency, 1.0)

    def test_action_clone_remaps_dependencies(self):
        project = self._project()
        project.allow_task_dependencies = True
        task_a = self.env['project.task'].create({
            'name': 'Bloqueante', 'project_id': project.id, 'allocated_hours': 10.0,
        })
        task_b = self.env['project.task'].create({
            'name': 'Bloqueada', 'project_id': project.id, 'allocated_hours': 10.0,
            'depend_on_ids': [(6, 0, [task_a.id])],
        })
        project.state = 'done'

        new_project = self.env['project.project'].browse(project.action_clone()['res_id'])
        new_task_a = self.env['project.task'].search([
            ('project_id', '=', new_project.id), ('source_task_id', '=', task_a.id),
        ])
        new_task_b = self.env['project.task'].search([
            ('project_id', '=', new_project.id), ('source_task_id', '=', task_b.id),
        ])
        self.assertEqual(new_task_b.depend_on_ids, new_task_a)
