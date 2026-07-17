# -*- coding: utf-8 -*-
"""Regression tests for _apply_selection_strategy (models/project_project.py):
after importing every scenario's CSV, this decides which scenario becomes
is_baseline according to project.scenario_selection_strategy, and posts the
rationale on the project chatter.
"""
from odoo.tests.common import TransactionCase


class TestScenarioSelectionBase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Selection Project',
            'is_tj_enabled': True,
            'date_start': '2020-01-01',
        })
        cls.user_a = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Resource A', 'login': 'sel_a@insight.test', 'email': 'sel_a@insight.test',
            'groups_id': [(4, cls.env.ref('base.group_user').id)],
        })
        cls.user_b = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Resource B', 'login': 'sel_b@insight.test', 'email': 'sel_b@insight.test',
            'groups_id': [(4, cls.env.ref('base.group_user').id)],
        })

    def _task(self, **vals):
        vals.setdefault('project_id', self.project.id)
        return self.env['project.task'].create(vals)

    def _scenario(self, name, is_baseline=False):
        return self.env['insight.scenario'].create({
            'name': name, 'project_id': self.project.id, 'is_baseline': is_baseline,
        })

    @staticmethod
    def _row(task, start, end, resources='', cost='0'):
        return f'"t{task.id}";"1";"Task";"{start}";"{end}";"5.0d";"5.0d";"{cost}";"{resources}";"0"\n'

    def _csv(self, *rows):
        header = '"Id";"Bsi";"Name";"Start";"End";"Effort";"Duration";"Cost";"Resources";"Criticalness"\n'
        return header + ''.join(rows)


class TestManualStrategyIsNoop(TestScenarioSelectionBase):

    def test_manual_strategy_never_changes_is_baseline(self):
        cheap = self._scenario('Barato', is_baseline=True)
        expensive = self._scenario('Caro')
        task = self._task(name='T1')
        self.project._import_scenario_csv(
            self._csv(self._row(task, '2024-01-01', '2024-01-05', cost='100')), cheap,
        )
        self.project._import_scenario_csv(
            self._csv(self._row(task, '2024-01-01', '2024-01-05', cost='500')), expensive,
        )
        self.project.scenario_selection_strategy = 'manual'
        self.project._apply_selection_strategy()

        self.assertTrue(cheap.is_baseline)
        self.assertFalse(expensive.is_baseline)
        # Los agregados se calculan igual, aunque la estrategia sea manual —
        # sirven para mostrar en la UI sin depender de que corra la selección.
        self.assertEqual(cheap.total_cost, 100.0)
        self.assertEqual(expensive.total_cost, 500.0)


class TestMinCostStrategy(TestScenarioSelectionBase):

    def test_picks_the_cheaper_scenario_and_flips_baseline(self):
        cheap = self._scenario('Barato')
        expensive = self._scenario('Caro', is_baseline=True)
        task = self._task(name='T1')
        self.project._import_scenario_csv(
            self._csv(self._row(task, '2024-01-01', '2024-01-05', cost='100')), cheap,
        )
        self.project._import_scenario_csv(
            self._csv(self._row(task, '2024-01-01', '2024-01-05', cost='500')), expensive,
        )
        self.project.write({
            'scenario_selection_strategy': 'automatic',
            'scenario_weight_cost': 1.0, 'scenario_weight_duration': 0.0,
            'scenario_weight_resources': 0.0,
        })
        self.project._apply_selection_strategy()

        self.assertTrue(cheap.is_baseline)
        self.assertFalse(expensive.is_baseline)

        messages = self.env['mail.message'].search([
            ('model', '=', 'project.project'), ('res_id', '=', self.project.id),
        ])
        self.assertTrue(
            messages.filtered(lambda m: 'Barato' in (m.body or '') and 'costo' in (m.body or '')),
            'The chatter should explain which scenario won and why',
        )


class TestMinDurationStrategy(TestScenarioSelectionBase):

    def test_picks_the_scenario_that_finishes_earliest(self):
        fast = self._scenario('Rápido')
        slow = self._scenario('Lento', is_baseline=True)
        task = self._task(name='T1')
        self.project._import_scenario_csv(
            self._csv(self._row(task, '2024-01-01', '2024-01-05')), fast,
        )
        self.project._import_scenario_csv(
            self._csv(self._row(task, '2024-01-01', '2024-02-05')), slow,
        )
        self.project.write({
            'scenario_selection_strategy': 'automatic',
            'scenario_weight_cost': 0.0, 'scenario_weight_duration': 1.0,
            'scenario_weight_resources': 0.0,
        })
        self.project._apply_selection_strategy()

        self.assertTrue(fast.is_baseline)
        self.assertFalse(slow.is_baseline)


class TestMinResourcesStrategy(TestScenarioSelectionBase):
    """peak_resources = máxima cantidad de recursos distintos con una tarea
    activa en simultáneo (sweep-line sobre intervalos [start, end))."""

    def test_sequential_scenario_has_lower_peak_than_parallel_one(self):
        parallel = self._scenario('Paralelo')
        sequential = self._scenario('Secuencial', is_baseline=True)
        t1 = self._task(name='T1')
        t2 = self._task(name='T2')

        self.project._import_scenario_csv(self._csv(
            self._row(t1, '2024-01-01', '2024-01-05', resources=f'Resource A (u{self.user_a.id})'),
            self._row(t2, '2024-01-02', '2024-01-06', resources=f'Resource B (u{self.user_b.id})'),
        ), parallel)
        self.project._import_scenario_csv(self._csv(
            self._row(t1, '2024-01-01', '2024-01-05', resources=f'Resource A (u{self.user_a.id})'),
            self._row(t2, '2024-01-05', '2024-01-10', resources=f'Resource B (u{self.user_b.id})'),
        ), sequential)

        self.assertEqual(self.project._peak_concurrent_resources(
            parallel, self.project._tjp_leaf_task_ids()), 2)
        self.assertEqual(self.project._peak_concurrent_resources(
            sequential, self.project._tjp_leaf_task_ids()), 1,
            'A task ending exactly when another starts must not count as concurrent',
        )

        self.project.write({
            'scenario_selection_strategy': 'automatic',
            'scenario_weight_cost': 0.0, 'scenario_weight_duration': 0.0,
            'scenario_weight_resources': 1.0,
        })
        self.project._apply_selection_strategy()
        self.assertTrue(sequential.is_baseline)
        self.assertFalse(parallel.is_baseline)


class TestWeightedScoreStrategy(TestScenarioSelectionBase):

    def test_weights_tilt_the_winner_towards_the_favored_axis(self):
        cheap_slow = self._scenario('Barato y lento')
        expensive_fast = self._scenario('Caro y rápido')
        task = self._task(name='T1')
        self.project._import_scenario_csv(self._csv(
            self._row(task, '2024-01-01', '2024-03-01', cost='100'),
        ), cheap_slow)
        self.project._import_scenario_csv(self._csv(
            self._row(task, '2024-01-01', '2024-01-05', cost='900'),
        ), expensive_fast)

        self.project.write({
            'scenario_selection_strategy': 'automatic',
            'scenario_weight_cost': 1.0,
            'scenario_weight_duration': 0.0,
            'scenario_weight_resources': 0.0,
        })
        self.project._apply_selection_strategy()
        self.assertTrue(cheap_slow.is_baseline, 'With only cost weighted, the cheaper scenario should win')
        self.assertEqual(cheap_slow.selection_score, 0.0)
        self.assertEqual(expensive_fast.selection_score, 1.0)

        self.project.write({
            'scenario_selection_strategy': 'automatic',
            'scenario_weight_cost': 0.0,
            'scenario_weight_duration': 1.0,
            'scenario_weight_resources': 0.0,
        })
        self.project._apply_selection_strategy()
        self.assertTrue(expensive_fast.is_baseline, 'With only duration weighted, the faster scenario should win')


class TestDeadlineGate(TestScenarioSelectionBase):

    def test_scenario_that_misses_the_agreed_date_is_discarded(self):
        self.project.date = '2024-01-31'
        cheap_but_late = self._scenario('Barato pero tarde')
        pricier_on_time = self._scenario('A tiempo', is_baseline=True)
        task = self._task(name='T1')
        self.project._import_scenario_csv(self._csv(
            self._row(task, '2024-01-01', '2024-02-15', cost='100'),
        ), cheap_but_late)
        self.project._import_scenario_csv(self._csv(
            self._row(task, '2024-01-01', '2024-01-20', cost='300'),
        ), pricier_on_time)

        self.project.write({
            'scenario_selection_strategy': 'automatic',
            'scenario_weight_cost': 1.0, 'scenario_weight_duration': 0.0,
            'scenario_weight_resources': 0.0,
        })
        self.project._apply_selection_strategy()

        self.assertTrue(
            pricier_on_time.is_baseline,
            'The cheaper scenario must be discarded for missing the agreed deadline',
        )

    def test_falls_back_to_all_scenarios_when_none_meets_the_deadline(self):
        self.project.date = '2024-01-01'
        cheap = self._scenario('Barato')
        expensive = self._scenario('Caro', is_baseline=True)
        task = self._task(name='T1')
        self.project._import_scenario_csv(self._csv(
            self._row(task, '2024-01-01', '2024-02-15', cost='100'),
        ), cheap)
        self.project._import_scenario_csv(self._csv(
            self._row(task, '2024-01-01', '2024-03-15', cost='500'),
        ), expensive)

        self.project.write({
            'scenario_selection_strategy': 'automatic',
            'scenario_weight_cost': 1.0, 'scenario_weight_duration': 0.0,
            'scenario_weight_resources': 0.0,
        })
        self.project._apply_selection_strategy()

        self.assertTrue(cheap.is_baseline, 'Falls back to comparing every scenario when none meets the deadline')
        messages = self.env['mail.message'].search([
            ('model', '=', 'project.project'), ('res_id', '=', self.project.id),
        ])
        self.assertTrue(
            messages.filtered(lambda m: 'Ningún escenario cumple' in (m.body or '')),
            'The chatter must explain that the deadline filter was ignored',
        )


class TestTieBreak(TestScenarioSelectionBase):

    def test_keeps_current_baseline_among_tied_winners(self):
        current = self._scenario('Actual', is_baseline=True)
        alternative = self._scenario('Alternativa')
        task = self._task(name='T1')
        self.project._import_scenario_csv(self._csv(
            self._row(task, '2024-01-01', '2024-01-10', cost='100'),
        ), current)
        self.project._import_scenario_csv(self._csv(
            self._row(task, '2024-01-01', '2024-01-10', cost='100'),
        ), alternative)

        self.project.write({
            'scenario_selection_strategy': 'automatic',
            'scenario_weight_cost': 1.0, 'scenario_weight_duration': 0.0,
            'scenario_weight_resources': 0.0,
        })
        self.project._apply_selection_strategy()

        self.assertTrue(current.is_baseline, 'A tie should not switch away from the current baseline')
