# -*- coding: utf-8 -*-
"""Regression tests for portfolio scheduling (project.project.state
draft/evaluation/progress from project_improve, _tj_portfolio_recordset,
multi-project _generate_tjp/_tj_project_users, and the write-back asymmetry
in _import_all_schedules — see BACKLOG.md item 3 / memoria
project_portfolio_scheduling_states)."""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestPortfolioRecordset(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.active = cls.env['project.project'].create({
            'name': 'Active Project', 'is_tj_enabled': True, 'state': 'evaluation',
        })
        cls.progress1 = cls.env['project.project'].create({
            'name': 'Progress 1', 'is_tj_enabled': True, 'state': 'progress',
        })
        cls.progress2 = cls.env['project.project'].create({
            'name': 'Progress 2', 'is_tj_enabled': True, 'state': 'progress',
        })
        cls.draft = cls.env['project.project'].create({
            'name': 'Draft Project', 'is_tj_enabled': True, 'state': 'draft',
        })

    def test_combines_all_progress_projects_with_self(self):
        combined = self.active._tj_portfolio_recordset()
        self.assertEqual(combined, self.active | self.progress1 | self.progress2)
        self.assertNotIn(self.draft, combined)

    def test_progress_project_includes_itself_and_peers(self):
        combined = self.progress1._tj_portfolio_recordset()
        self.assertIn(self.progress1, combined)
        self.assertIn(self.progress2, combined)

    def test_draft_project_is_isolated_from_progress_peers(self):
        """Bug real (2026-07-27): un proyecto 'draft' se planifica aislado,
        para presupuestar sin competir por recursos con nadie (ver help de
        project.project.state y el diseño original en la memoria
        project_portfolio_scheduling_states). Antes de este fix,
        _tj_portfolio_recordset combinaba igual con todos los 'en progreso'
        sin importar el estado propio, contradiciendo ambos."""
        combined = self.draft._tj_portfolio_recordset()
        self.assertEqual(combined, self.draft)


class TestMultiProjectGeneration(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Shared Resource', 'login': 'shared_resource@insight.test',
            'email': 'shared_resource@insight.test',
            'groups_id': [(4, cls.env.ref('base.group_user').id)],
        })
        cls.project_a = cls.env['project.project'].create({
            'name': 'Project A', 'is_tj_enabled': True, 'state': 'evaluation',
        })
        cls.project_b = cls.env['project.project'].create({
            'name': 'Project B', 'is_tj_enabled': True, 'state': 'progress',
        })
        cls.task_a = cls.env['project.task'].create({
            'name': 'Task A', 'project_id': cls.project_a.id,
            'allocated_hours': 8.0, 'user_ids': [(6, 0, [cls.user.id])],
        })
        cls.task_b = cls.env['project.task'].create({
            'name': 'Task B', 'project_id': cls.project_b.id,
            'allocated_hours': 8.0, 'user_ids': [(6, 0, [cls.user.id])],
        })
        _scenario_a = cls.env['insight.scenario'].create({'name': 'Default'})
        cls.scenario_a = cls.env['insight.scenario.project'].create({
            'scenario_id': _scenario_a.id, 'project_id': cls.project_a.id, 'is_baseline': True,
        })
        _scenario_b = cls.env['insight.scenario'].create({'name': 'Default'})
        cls.scenario_b = cls.env['insight.scenario.project'].create({
            'scenario_id': _scenario_b.id, 'project_id': cls.project_b.id, 'is_baseline': True,
        })

    def test_tjp_scenario_id_is_qualified_by_project(self):
        """Dos escenarios con el mismo nombre en proyectos distintos no
        deben colisionar al combinarse en una sola corrida."""
        id_a = self.project_a._tjp_scenario_id(self.scenario_a)
        id_b = self.project_a._tjp_scenario_id(self.scenario_b)
        self.assertNotEqual(id_a, id_b)

    def test_combined_tjp_declares_shared_resource_once(self):
        combined = self.project_a | self.project_b
        tjp = combined._generate_tjp(active_project=self.project_a)
        res_id = combined._tjp_resource_id(self.user.partner_id.id)
        self.assertEqual(
            tjp.count(f'resource {res_id}'), 1,
            'Un recurso compartido por dos proyectos combinados debe declararse una sola vez',
        )

    def test_combined_tjp_includes_both_task_trees(self):
        combined = self.project_a | self.project_b
        tjp = combined._generate_tjp(active_project=self.project_a)
        self.assertIn(f'task {combined._tjp_task_id(self.task_a)}', tjp)
        self.assertIn(f'task {combined._tjp_task_id(self.task_b)}', tjp)

    def test_draft_project_generate_tjp_excludes_peer_tasks(self):
        """Complemento end-to-end de test_combined_tjp_includes_both_task_trees:
        con project_a en 'draft' (en vez de 'evaluation'), _tj_portfolio_recordset
        ya no debe traer a project_b (aunque esté 'en progreso') al .tjp
        generado — bug real corregido (2026-07-27)."""
        self.project_a.state = 'draft'
        try:
            combined = self.project_a._tj_portfolio_recordset()
            tjp = combined._generate_tjp(active_project=self.project_a)
            self.assertIn(f'task {combined._tjp_task_id(self.task_a)}', tjp)
            self.assertNotIn(f'task {combined._tjp_task_id(self.task_b)}', tjp)
        finally:
            self.project_a.state = 'evaluation'

    def test_single_project_generation_is_unchanged(self):
        """N=1 no debe ser un caso especial: mismo resultado que antes."""
        tjp = self.project_a._generate_tjp()
        self.assertIn(f'project p{self.project_a.id}', tjp)
        self.assertIn(f'task {self.project_a._tjp_task_id(self.task_a)}', tjp)
        self.assertNotIn(f'task {self.project_a._tjp_task_id(self.task_b)}', tjp)


class TestImportAllSchedulesPortfolio(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project_a = cls.env['project.project'].create({
            'name': 'Active Eval Project', 'is_tj_enabled': True, 'state': 'evaluation',
        })
        cls.project_b = cls.env['project.project'].create({
            'name': 'Progress Peer Project', 'is_tj_enabled': True, 'state': 'progress',
        })
        _scenario_a = cls.env['insight.scenario'].create({'name': 'Plan'})
        cls.scenario_a = cls.env['insight.scenario.project'].create({
            'scenario_id': _scenario_a.id, 'project_id': cls.project_a.id, 'is_baseline': True,
        })
        _scenario_b = cls.env['insight.scenario'].create({'name': 'Plan'})
        cls.scenario_b = cls.env['insight.scenario.project'].create({
            'scenario_id': _scenario_b.id, 'project_id': cls.project_b.id, 'is_baseline': True,
        })
        cls.task_a = cls.env['project.task'].create({'name': 'Task A', 'project_id': cls.project_a.id})
        cls.task_b = cls.env['project.task'].create({'name': 'Task B', 'project_id': cls.project_b.id})

    @staticmethod
    def _csv_multi(tasks_and_ends):
        header = '"Id";"Bsi";"Name";"Start";"End";"Effort";"Duration";"Resources";"Criticalness"\n'
        rows = ''.join(
            f'"t{task.id}";"1";"Task";"2024-01-01";"{end}";"5.0d";"5.0d";"";"0"\n'
            for task, end in tasks_and_ends
        )
        return header + rows

    def test_evaluation_mode_persists_only_active_project(self):
        combined = self.project_a | self.project_b
        csv_files = {
            f'schedule_{self.project_a._tjp_scenario_id(self.scenario_a)}.csv':
                self._csv_multi([(self.task_a, '2024-01-10'), (self.task_b, '2024-01-15')]),
        }
        imported = combined._import_all_schedules(csv_files, active_project=self.project_a)
        self.assertEqual(imported, 1)
        self.assertTrue(self.env['insight.task.schedule'].search([
            ('task_id', '=', self.task_a.id), ('scenario_id', '=', self.scenario_a.scenario_id.id),
        ]))
        self.assertFalse(
            self.env['insight.task.schedule'].search([('task_id', '=', self.task_b.id)]),
            'Un proyecto en progreso no debe persistir schedule nuevo mientras el '
            'proyecto activo solo está en evaluación',
        )

    def test_progress_mode_persists_all_included_projects(self):
        self.project_a.state = 'progress'
        combined = self.project_a | self.project_b
        csv_files = {
            f'schedule_{self.project_a._tjp_scenario_id(self.scenario_a)}.csv':
                self._csv_multi([(self.task_a, '2024-01-10'), (self.task_b, '2024-01-15')]),
        }
        combined._import_all_schedules(csv_files, active_project=self.project_a)
        self.assertTrue(self.env['insight.task.schedule'].search([
            ('task_id', '=', self.task_a.id), ('scenario_id', '=', self.scenario_a.scenario_id.id),
        ]))
        self.assertTrue(self.env['insight.task.schedule'].search([
            ('task_id', '=', self.task_b.id), ('scenario_id', '=', self.scenario_b.scenario_id.id),
        ]), 'En modo progreso, los proyectos pares incluidos en la corrida sí se persisten')

    def test_evaluation_mode_reports_date_slip_for_peer_project(self):
        # Simula que Project B ya tenía un schedule comprometido (ej. de una
        # corrida 'progress' anterior) con Task B terminando el 2024-01-05.
        self.project_b._import_scenario_csv(
            self._csv_multi([(self.task_b, '2024-01-05')]), self.scenario_b,
        )

        combined = self.project_a | self.project_b
        csv_files = {
            f'schedule_{self.project_a._tjp_scenario_id(self.scenario_a)}.csv':
                self._csv_multi([(self.task_a, '2024-01-10'), (self.task_b, '2024-01-15')]),
        }
        combined._import_all_schedules(csv_files, active_project=self.project_a)

        asset = self.env['knowledge.asset'].search([
            ('res_model', '=', 'project.project'), ('res_id', '=', self.project_a.id),
            ('category', '=', 'insight_project.evaluation_impact_report'),
        ])
        self.assertTrue(asset, 'Debe publicarse un reporte de impacto cuando un proyecto par se ve afectado')
        payload = asset.latest_version().payload
        projects_payload = payload['projects']
        self.assertEqual(len(projects_payload), 1)
        self.assertEqual(projects_payload[0]['project_id'], self.project_b.id)
        self.assertEqual(projects_payload[0]['max_slip_days'], 10)
        # Project B no debe haber sido tocado: sigue con su schedule viejo.
        schedule_b = self.env['insight.task.schedule'].search([
            ('task_id', '=', self.task_b.id), ('scenario_id', '=', self.scenario_b.scenario_id.id),
        ])
        self.assertEqual(str(schedule_b.end_scheduled.date()), '2024-01-05')

    def test_no_impact_report_when_nothing_changes_for_peers(self):
        combined = self.project_a | self.project_b
        csv_files = {
            f'schedule_{self.project_a._tjp_scenario_id(self.scenario_a)}.csv':
                self._csv_multi([(self.task_a, '2024-01-10')]),
        }
        combined._import_all_schedules(csv_files, active_project=self.project_a)
        count = self.env['knowledge.asset'].search_count([
            ('res_model', '=', 'project.project'), ('res_id', '=', self.project_a.id),
            ('category', '=', 'insight_project.evaluation_impact_report'),
        ])
        self.assertEqual(count, 0)


class TestArchivedAncestorPreflight(TransactionCase):
    """Bug real (2026-07-28, ver memoria
    project_insight_project_tjp_cross_project_depends_bug): Odoo permite
    archivar una tarea sin archivar sus subtareas, dejando una rama activa
    invisible para el schedule TJ3 sin ningún aviso. Decisión del usuario
    (confirmada 2026-07-29, tras una corrección de rumbo intermedia que
    intentó angostar el guard a solo-si-hay-una-dependencia-real y resultó
    equivocada): bloquear la corrida completa ante CUALQUIER tarea archivada
    con descendencia activa, sin importar si algo depende de esa rama o no
    — dejar una actividad por grupo con el subárbol activo completo
    involucrado. Los tests con una arista `depends`/milestone real cruzando
    el archivado (test_dependency_edge_.../test_milestone_edge_...) no son
    un caso aparte con lógica propia — son el mismo chequeo amplio
    (`_tj_archived_ancestor_groups`, que no le presta atención a si algo
    depende de la rama activa o no), documentados por separado porque así
    es como el bug real llegó a producción."""

    def _project_with_scenario(self, name):
        project = self.env['project.project'].create({
            'name': name, 'is_tj_enabled': True,
        })
        scenario = self.env['insight.scenario'].create({'name': 'Plan'})
        self.env['insight.scenario.project'].create({
            'scenario_id': scenario.id, 'project_id': project.id, 'is_baseline': True,
        })
        return project

    def test_archived_ancestor_with_active_descendants_blocks_schedule(self):
        """Solo chequea la excepción (tipo + mensaje), no la persistencia de
        la actividad: `assertRaises` en el test runner de Odoo envuelve el
        bloque en un SAVEPOINT que se revierte al capturar la excepción
        esperada (odoo/tests/common.py) — simula lo que pasa en un request
        real cuando termina en UserError, así que revertiría también la
        actividad/mensaje creados en la misma llamada. Por eso
        action_run_schedule hace un commit real (gateado por test_enable,
        nunca ejercido bajo test — ver
        feedback_odoo_test_cursor_rollback_fragility) antes de este raise; la
        persistencia de la actividad se prueba aparte, llamando al helper
        directo (test_flag_helper_creates_activity_with_full_active_subtree),
        sin pasar por ningún raise."""
        project = self._project_with_scenario('Preflight Blocked Project')
        Task = self.env['project.task'].with_context(default_project_id=project.id)
        archived_root = Task.create({
            'name': 'Eje archivado', 'project_id': project.id, 'active': False,
        })
        Task.create({
            'name': 'Nieta activa colgando', 'project_id': project.id,
            'parent_id': archived_root.id,
        })

        with self.assertRaises(UserError) as cm:
            project.action_run_schedule(interactive=False)
        self.assertIn('archivada', str(cm.exception))
        self.assertNotIn('microservicio', str(cm.exception))

    def test_dependency_edge_into_archived_ancestor_is_also_blocked(self):
        """Caso puntual (2026-07-28, real de producción): A (activa) depende
        de B (activa), B es subtarea de C (archivada). No requiere lógica
        propia — es una instancia más de "archivada con descendencia
        activa" (mismo `test_archived_ancestor_with_active_descendants_
        blocks_schedule` de arriba), documentado aparte porque así llegó el
        bug real: vía un `depends` que revienta en TJ3 con "has unknown
        depends", no vía una tarea huérfana sin referencias."""
        project = self._project_with_scenario('Preflight Blocked Dependency Edge')
        Task = self.env['project.task'].with_context(default_project_id=project.id)
        archived_ancestor = Task.create({
            'name': 'Eje archivado', 'project_id': project.id, 'active': False,
        })
        blocker = Task.create({
            'name': 'Bloqueante activa', 'project_id': project.id,
            'parent_id': archived_ancestor.id,
        })
        Task.create({
            'name': 'Dependiente', 'project_id': project.id,
            'depend_on_ids': [(6, 0, [blocker.id])],
        })

        with self.assertRaises(UserError) as cm:
            project.action_run_schedule(interactive=False)
        self.assertIn('archivada', str(cm.exception))
        self.assertNotIn('microservicio', str(cm.exception))

    def test_milestone_edge_into_archived_ancestor_is_also_blocked(self):
        """Mismo caso que el anterior, pero la arista es un
        project.milestone.task_ids en vez de depend_on_ids — tampoco
        necesita lógica propia, ya lo cubre el chequeo amplio de descendencia
        activa bajo un ancestro archivado."""
        project = self._project_with_scenario('Preflight Blocked Milestone Edge')
        Task = self.env['project.task'].with_context(default_project_id=project.id)
        archived_ancestor = Task.create({
            'name': 'Eje archivado', 'project_id': project.id, 'active': False,
        })
        linked_task = Task.create({
            'name': 'Vinculada a milestone', 'project_id': project.id,
            'parent_id': archived_ancestor.id,
        })
        milestone = self.env['project.milestone'].create({
            'name': 'Hito', 'project_id': project.id,
        })
        linked_task.milestone_id = milestone.id

        with self.assertRaises(UserError) as cm:
            project.action_run_schedule(interactive=False)
        self.assertIn('archivada', str(cm.exception))
        self.assertNotIn('microservicio', str(cm.exception))

    def test_flag_helper_creates_activity_with_full_active_subtree(self):
        """El helper en sí (llamado directo, sin pasar por ningún raise) sí
        deja probar la persistencia real de la actividad/mensaje."""
        project = self._project_with_scenario('Flag Helper Project')
        Task = self.env['project.task'].with_context(default_project_id=project.id)
        archived_root = Task.create({
            'name': 'Eje archivado', 'project_id': project.id, 'active': False,
        })
        child = Task.create({
            'name': 'Hija activa', 'project_id': project.id, 'parent_id': archived_root.id,
        })
        grandchild = Task.create({
            'name': 'Nieta activa', 'project_id': project.id, 'parent_id': child.id,
        })

        combined = project._tj_portfolio_recordset()
        groups = combined._tj_archived_ancestor_groups()
        self.assertEqual(len(groups), 1)
        root, active_descendants = groups[0]
        self.assertEqual(root, archived_root)
        self.assertEqual(active_descendants, child | grandchild)

        root._tj_flag_archived_ancestor_inconsistency(active_descendants)

        activity = self.env['mail.activity'].search([
            ('res_model', '=', 'project.task'), ('res_id', '=', archived_root.id),
        ])
        self.assertTrue(activity, 'Debe crear una actividad en la tarea archivada')
        self.assertIn(child.name, activity.note or '')
        self.assertIn(grandchild.name, activity.note or '')

    def test_closed_state_root_with_active_descendants_blocks_schedule(self):
        """Bug real (2026-07-29, datos de producción): una tarea RAÍZ
        marcada "Hecha" (`state='1_done'`) sin archivar (`active=True`)
        esconde su rama del recorrido de raíces de _generate_tjp igual que
        una archivada — project.task_ids trae un dominio nativo
        `[('state','in',OPEN_STATES)]` ajeno a `active`. El guard viejo
        (`not t.active`) no lo detectaba porque la raíz seguía activa."""
        project = self._project_with_scenario('Preflight Blocked Closed Root')
        Task = self.env['project.task'].with_context(default_project_id=project.id)
        closed_root = Task.create({
            'name': 'Eje cerrado', 'project_id': project.id, 'state': '1_done',
        })
        Task.create({
            'name': 'Nieta activa colgando', 'project_id': project.id,
            'parent_id': closed_root.id,
        })

        with self.assertRaises(UserError) as cm:
            project.action_run_schedule(interactive=False)
        self.assertIn('cerrada', str(cm.exception))
        self.assertNotIn('microservicio', str(cm.exception))

    def test_flag_helper_uses_reopen_wording_for_closed_state_root(self):
        """El mensaje/actividad debe distinguir el caso: una raíz cerrada
        pero activa dice "marcada como terminada/cancelada" y "Reabrí" —
        no "archivada"/"Desarchivá", que sería engañoso (`active` sigue en
        `True`, no hay nada que desarchivar)."""
        project = self._project_with_scenario('Flag Helper Closed Root Project')
        Task = self.env['project.task'].with_context(default_project_id=project.id)
        closed_root = Task.create({
            'name': 'Eje cerrado', 'project_id': project.id, 'state': '1_done',
        })
        child = Task.create({
            'name': 'Hija activa', 'project_id': project.id, 'parent_id': closed_root.id,
        })

        combined = project._tj_portfolio_recordset()
        groups = combined._tj_archived_ancestor_groups()
        self.assertEqual(len(groups), 1)
        root, active_descendants = groups[0]
        self.assertEqual(root, closed_root)
        self.assertEqual(active_descendants, child)

        root._tj_flag_archived_ancestor_inconsistency(active_descendants)

        activity = self.env['mail.activity'].search([
            ('res_model', '=', 'project.task'), ('res_id', '=', closed_root.id),
        ])
        self.assertTrue(activity, 'Debe crear una actividad en la tarea cerrada')
        self.assertIn('Reabrí', activity.note or '')
        self.assertNotIn('Desarchivá', activity.note or '')

    def test_dependency_edge_into_closed_state_root_is_also_blocked(self):
        """Forma exacta del bug real de producción: una tarea de OTRO eje
        del mismo proyecto depende de una sub-tarea activa colgando de una
        raíz cerrada — mismo guard amplio, sin lógica propia (ver
        test_dependency_edge_into_archived_ancestor_is_also_blocked, su
        análogo para el caso archivado)."""
        project = self._project_with_scenario('Preflight Blocked Closed Root Edge')
        Task = self.env['project.task'].with_context(default_project_id=project.id)
        closed_root = Task.create({
            'name': 'Eje cerrado', 'project_id': project.id, 'state': '1_done',
        })
        blocker = Task.create({
            'name': 'Bloqueante activa', 'project_id': project.id,
            'parent_id': closed_root.id,
        })
        Task.create({
            'name': 'Dependiente de otro eje', 'project_id': project.id,
            'depend_on_ids': [(6, 0, [blocker.id])],
        })

        with self.assertRaises(UserError) as cm:
            project.action_run_schedule(interactive=False)
        self.assertIn('cerrada', str(cm.exception))
        self.assertNotIn('microservicio', str(cm.exception))

    def test_no_archived_inconsistency_does_not_block_on_preflight(self):
        """Sin ninguna tarea archivada con descendencia activa, el pre-flight
        no debe frenar nada — la corrida sigue hasta el siguiente chequeo
        real (acá, config del microservicio, que no está seteada en test)."""
        project = self._project_with_scenario('Preflight OK Project')
        Task = self.env['project.task'].with_context(default_project_id=project.id)
        Task.create({'name': 'Tarea normal', 'project_id': project.id})

        with self.assertRaises(UserError) as cm:
            project.action_run_schedule(interactive=False)
        self.assertIn('microservicio', str(cm.exception))
