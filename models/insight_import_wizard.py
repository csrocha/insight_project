# -*- coding: utf-8 -*-
import base64
import csv
import io
import json
import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class InsightImportWizard(models.TransientModel):
    _name = 'insight.import.wizard'
    _description = 'Importar proyecto TJP a Odoo'

    project_id = fields.Many2one(
        'project.project', string='Proyecto', required=True,
        default=lambda self: self.env.context.get('active_id'),
    )
    state = fields.Selection([
        ('upload', 'Subir archivo'),
        ('mapping', 'Mapear recursos'),
    ], default='upload', readonly=True)

    tjp_file = fields.Binary(string='Archivo TJP (.tjp)')
    tjp_filename = fields.Char()

    # Parsed data stored as JSON text
    parsed_tasks_json = fields.Text()
    csv_files_json = fields.Text()

    task_count = fields.Integer(compute='_compute_task_count', string='Tareas encontradas')
    scenario_names = fields.Char(compute='_compute_scenario_names', string='Escenarios detectados')

    resource_map_ids = fields.One2many(
        'insight.import.resource.map', 'wizard_id',
        string='Recursos del TJP',
    )

    @api.depends('parsed_tasks_json')
    def _compute_task_count(self):
        for rec in self:
            if rec.parsed_tasks_json:
                try:
                    rec.task_count = len(json.loads(rec.parsed_tasks_json))
                except Exception:
                    rec.task_count = 0
            else:
                rec.task_count = 0

    @api.depends('csv_files_json')
    def _compute_scenario_names(self):
        for rec in self:
            if rec.csv_files_json:
                try:
                    files = json.loads(rec.csv_files_json)
                    names = []
                    for fname in files:
                        base = fname.rsplit('.', 1)[0]
                        sc = base[len('schedule_'):] if base.startswith('schedule_') else base
                        names.append(sc)
                    rec.scenario_names = ', '.join(names)
                except Exception:
                    rec.scenario_names = ''
            else:
                rec.scenario_names = ''

    # -------------------------------------------------------------------------
    # Step 1: Upload & Analyze
    # -------------------------------------------------------------------------

    def action_analyze(self):
        self.ensure_one()
        if not self.tjp_file:
            raise UserError(_('Seleccione un archivo TJP antes de continuar.'))

        ICP = self.env['ir.config_parameter'].sudo()
        url = ICP.get_param('insight_project.tj_microservice_url')
        if not url:
            raise UserError(_('Configure la URL del microservicio TJ3 en Ajustes → TaskJuggler.'))
        timeout = int(ICP.get_param('insight_project.tj_microservice_timeout') or 120)

        tjp_content = base64.b64decode(self.tjp_file).decode('utf-8', errors='replace')

        # Append report blocks if none exist
        if 'taskreport' not in tjp_content.lower():
            sc_ids = re.findall(r'\bscenario\s+(\w+)\b', tjp_content)
            if not sc_ids:
                sc_ids = ['plan']
            for sc_id in sc_ids:
                tjp_content += (
                    f'\ntaskreport "schedule_{sc_id}" {{\n'
                    f'  formats csv\n'
                    f'  columns id, bsi, name, start, end, effort, duration, resources, criticalness\n'
                    f'  scenarios {sc_id}\n}}\n'
                )

        response_data = self.project_id._call_tj_microservice(url.rstrip('/'), tjp_content, timeout)
        csv_files = response_data.get('csv_files', {})
        if not csv_files:
            stderr = response_data.get('stderr', '')
            raise UserError(
                _('El microservicio no retornó ningún CSV.\n\nVerifique el archivo TJP.\n%s') % stderr
            )

        # Extract resource display names from TJP source
        resource_names = {
            m.group(1): m.group(2)
            for m in re.finditer(r'\bresource\s+(\w+)\s+"([^"]+)"', tjp_content)
        }

        # Parse tasks and resource IDs from first CSV
        first_csv = next(iter(csv_files.values()))
        tasks, resource_ids = self._parse_csv_preview(first_csv)

        # Rebuild resource mapping lines
        self.resource_map_ids.unlink()
        map_vals = []
        for res_id in sorted(resource_ids):
            display_name = resource_names.get(res_id, res_id)
            employee = self.env['hr.employee'].search([('name', 'ilike', display_name)], limit=1)
            map_vals.append({
                'wizard_id': self.id,
                'tj_resource_id': res_id,
                'tj_resource_name': display_name,
                'employee_id': employee.id if employee else False,
                'action': 'map' if employee else 'create',
            })
        if map_vals:
            self.env['insight.import.resource.map'].create(map_vals)

        self.write({
            'parsed_tasks_json': json.dumps(tasks),
            'csv_files_json': json.dumps(csv_files),
            'state': 'mapping',
        })
        return self._reopen()

    @staticmethod
    def _parse_csv_preview(csv_content):
        reader = csv.DictReader(io.StringIO(csv_content))
        tasks = []
        resource_ids = set()
        for row in reader:
            norm = {k.strip().lower(): (v or '').strip() for k, v in row.items()}
            res_str = norm.get('resources', '')
            task_res = [r.strip() for r in re.split(r'[,\s]+', res_str) if r.strip()]
            resource_ids.update(task_res)
            tasks.append({
                'bsi': norm.get('bsi', ''),
                'name': norm.get('name', ''),
                'effort': norm.get('effort', ''),
                'resources': task_res,
            })
        return tasks, resource_ids

    def action_back(self):
        self.state = 'upload'
        return self._reopen()

    # -------------------------------------------------------------------------
    # Step 2: Import
    # -------------------------------------------------------------------------

    def action_import(self):
        self.ensure_one()
        tasks = json.loads(self.parsed_tasks_json or '[]')
        csv_files = json.loads(self.csv_files_json or '{}')
        project = self.project_id

        # Build partner map from resource mappings
        partner_map = {}
        for rmap in self.resource_map_ids:
            if rmap.action == 'skip':
                continue
            if rmap.action == 'map' and rmap.employee_id:
                partner = rmap.employee_id.address_home_id or rmap.employee_id.partner_id
                partner_map[rmap.tj_resource_id] = partner
            elif rmap.action == 'create':
                name = rmap.tj_resource_name or rmap.tj_resource_id
                partner = self.env['res.partner'].create({'name': name})
                partner_map[rmap.tj_resource_id] = partner

        # Ensure project has insight.resource entries for each partner
        existing_partner_ids = {r.partner_id.id for r in project.resource_ids}
        for partner in partner_map.values():
            if partner and partner.id not in existing_partner_ids:
                self.env['insight.resource'].create({
                    'project_id': project.id,
                    'partner_id': partner.id,
                })
                existing_partner_ids.add(partner.id)

        # Create task hierarchy ordered by BSI
        bsi_task_id = {}
        sorted_tasks = sorted(tasks, key=lambda t: self._bsi_sort_key(t['bsi']))
        for task_data in sorted_tasks:
            bsi = task_data['bsi']
            parent_bsi = '.'.join(bsi.split('.')[:-1]) if '.' in bsi else None

            user_ids = []
            for res_id in task_data.get('resources', []):
                partner = partner_map.get(res_id)
                if partner:
                    user = self.env['res.users'].search(
                        [('partner_id', '=', partner.id)], limit=1
                    )
                    if user:
                        user_ids.append(user.id)

            task = self.env['project.task'].create({
                'name': task_data['name'] or f'Tarea {bsi}',
                'project_id': project.id,
                'parent_id': bsi_task_id.get(parent_bsi) if parent_bsi else False,
                'planned_hours': self._effort_to_hours(task_data.get('effort', '')),
                'user_ids': [(6, 0, user_ids)],
            })
            bsi_task_id[bsi] = task.id

        # Create scenarios and import schedules
        for filename, csv_content in csv_files.items():
            base = filename.rsplit('.', 1)[0]
            sc_key = base[len('schedule_'):] if base.startswith('schedule_') else base

            scenario = project.scenario_ids.filtered(
                lambda s: s.name.lower() == sc_key.lower()
            )[:1]
            if not scenario:
                scenario = self.env['insight.scenario'].create({
                    'name': sc_key.title(),
                    'project_id': project.id,
                    'is_baseline': not bool(project.scenario_ids),
                })
                project.invalidate_recordset(['scenario_ids'])

            project._import_scenario_csv(csv_content, scenario)

        project.write({
            'is_tj_enabled': True,
            'schedule_dirty': False,
            'last_scheduled': fields.Datetime.now(),
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'project.project',
            'res_id': project.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'insight.import.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @staticmethod
    def _bsi_sort_key(bsi):
        try:
            return [int(p) for p in (bsi or '0').split('.')]
        except ValueError:
            return [0]

    @staticmethod
    def _effort_to_hours(effort_str):
        v = (effort_str or '').strip()
        if not v:
            return 0.0
        try:
            if v.endswith('d'):
                return float(v[:-1]) * 8.0
            if v.endswith('h'):
                return float(v[:-1])
            if v.endswith('w'):
                return float(v[:-1]) * 40.0
            return float(v) * 8.0
        except (ValueError, AttributeError):
            return 0.0


class InsightImportResourceMap(models.TransientModel):
    _name = 'insight.import.resource.map'
    _description = 'Mapeo de recurso TJP a Odoo'

    wizard_id = fields.Many2one('insight.import.wizard', required=True, ondelete='cascade')
    tj_resource_id = fields.Char(string='ID en TJP', readonly=True)
    tj_resource_name = fields.Char(string='Nombre en TJP', readonly=True)
    action = fields.Selection([
        ('map', 'Mapear a empleado'),
        ('create', 'Crear contacto'),
        ('skip', 'Ignorar'),
    ], string='Acción', required=True, default='create')
    employee_id = fields.Many2one('hr.employee', string='Empleado Odoo')
