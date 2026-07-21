# -*- coding: utf-8 -*-
"""Regression tests for hr.employee.tj_daily_rate (models/hr_employee.py):
derivado de hr.contract.wage (salario bruto mensual) / 30 en vez de campo
manual — ver BACKLOG.md ítem 4 (resuelto) y CHANGELOG.md."""
from odoo.tests.common import TransactionCase


class TestTjDailyRateFromContract(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({'name': 'Empleado Test'})

    def _open_contract(self, wage):
        return self.env['hr.contract'].create({
            'name': 'Contrato Test', 'employee_id': self.employee.id,
            'wage': wage, 'state': 'open',
        })

    def test_no_contract_yields_zero(self):
        self.assertFalse(self.employee.contract_id)
        self.assertEqual(self.employee.tj_daily_rate, 0.0)

    def test_derives_from_open_contract_wage_divided_by_30(self):
        self._open_contract(3000.0)
        self.assertEqual(self.employee.contract_id.wage, 3000.0)
        self.assertEqual(self.employee.tj_daily_rate, 100.0)

    def test_recomputes_when_wage_changes(self):
        contract = self._open_contract(3000.0)
        self.assertEqual(self.employee.tj_daily_rate, 100.0)
        contract.wage = 6000.0
        self.assertEqual(self.employee.tj_daily_rate, 200.0)

    def test_closing_contract_without_replacement_keeps_last_computed_value(self):
        """contract_id (hr_contract core) no se limpia solo al cerrar un
        contrato sin uno nuevo que lo reemplace — tj_daily_rate sigue el
        mismo criterio que el resto de hr_contract, no inventa lógica
        propia de "contrato vencido"."""
        contract = self._open_contract(3000.0)
        contract.state = 'close'
        self.assertEqual(self.employee.tj_daily_rate, 100.0)


class TestTjpResourceBlockUsesComputedRate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({
            'name': 'Rate Resource Block Project', 'is_tj_enabled': True,
            'date_start': '2026-06-29',
        })
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Rate Test User', 'login': 'rate_test@insight.test',
            'email': 'rate_test@insight.test',
            'groups_id': [(4, cls.env.ref('base.group_user').id)],
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Rate Test User', 'user_id': cls.user.id,
        })

    def test_rate_line_reflects_computed_daily_rate(self):
        self.env['hr.contract'].create({
            'name': 'Contrato', 'employee_id': self.employee.id,
            'wage': 9000.0, 'state': 'open',
        })
        text = '\n'.join(self.project._tjp_resource_block(self.user))
        self.assertIn('  rate 300.00', text)

    def test_no_contract_omits_rate_line(self):
        text = '\n'.join(self.project._tjp_resource_block(self.user))
        self.assertNotIn('rate', text)
