# -*- coding: utf-8 -*-
import base64
import io
import json
import os
import re
import zipfile

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from . import tjp_parser


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

    tjp_file = fields.Binary(string='Archivo TJP / ZIP')
    tjp_filename = fields.Char()

    # Parsed data stored as JSON text
    parsed_tasks_json = fields.Text()
    csv_files_json = fields.Text()
    parsed_now = fields.Date()
    parsed_end = fields.Date()

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

    def _check_draft_state(self):
        """Importar (y reimportar) reemplaza todas las tareas/milestones
        existentes del proyecto — solo tiene sentido, y solo debería ser
        seguro, mientras el proyecto está en 'draft' (project_improve): ahí
        todavía se está presupuestando. En 'evaluación'/'progreso'/
        'finalizado' se bloquea para no arriesgar borrar trabajo real.

        'draft' por sí solo NO garantiza que no haya horas imputadas —
        nada impide cargar timesheets en un proyecto que sigue en
        borrador — así que se valida aparte (ver
        _check_no_timesheets_logged)."""
        self.ensure_one()
        if self.project_id.state != 'draft':
            raise UserError(_(
                'Solo se puede importar (o reimportar) un .tjp cuando el '
                'proyecto está en estado "Borrador". "%(project)s" está en '
                '"%(state)s".'
            ) % {
                'project': self.project_id.name,
                'state': dict(self.project_id._fields['state'].selection)[self.project_id.state],
            })

    def _check_no_timesheets_logged(self):
        """Reimportar borra todas las tareas existentes del proyecto
        (ver action_import) — si alguna tiene horas imputadas
        (account.analytic.line), Odoo va a rechazar ese unlink con su
        propio guard nativo (hr_timesheet._unlink_except_contains_entries),
        mid-operación y con un mensaje que no dice nada de reimportar.
        Se valida acá antes, con un mensaje específico a este flujo."""
        self.ensure_one()
        project = self.project_id
        tasks_with_hours = self.env['account.analytic.line'].sudo().search([
            ('task_id.project_id', '=', project.id),
        ]).task_id
        if tasks_with_hours:
            raise UserError(_(
                'No se puede reimportar "%(project)s": las siguientes tareas '
                'tienen horas imputadas y Odoo no permite borrarlas sin '
                'borrar antes esos registros: %(tasks)s.'
            ) % {
                'project': project.name,
                'tasks': ', '.join(tasks_with_hours.mapped('name')),
            })

    # -------------------------------------------------------------------------
    # Step 1: Upload & Analyze
    # -------------------------------------------------------------------------

    def action_analyze(self):
        self.ensure_one()
        if not self.tjp_file:
            raise UserError(_('Seleccione un archivo TJP antes de continuar.'))
        self._check_draft_state()
        self._check_no_timesheets_logged()

        ICP = self.env['ir.config_parameter'].sudo()
        url = ICP.get_param('insight_project.tj_microservice_url')
        if not url:
            raise UserError(_('Configure la URL del microservicio TJ3 en Ajustes → TaskJuggler.'))
        timeout = int(ICP.get_param('insight_project.tj_microservice_timeout') or 120)

        raw_bytes = base64.b64decode(self.tjp_file)
        filename = (self.tjp_filename or '').lower()
        if filename.endswith('.zip'):
            tjp_content, include_files = self._extract_zip_files(raw_bytes)
        else:
            tjp_content = raw_bytes.decode('utf-8', errors='replace')
            include_files = {}

        # If the .tjp references include files but none were provided, ask for a ZIP
        needed_includes = re.findall(r'\binclude\s+"([^"]+)"', tjp_content)
        if needed_includes and not include_files:
            raise UserError(
                _('El archivo TJP referencia archivos de inclusión:\n%s\n\n'
                  'Cree un ZIP con el .tjp y todos sus archivos .tji y súbalo como ZIP.')
                % '\n'.join(needed_includes)
            )

        # Capture the source project's base date and horizon so they carry
        # over to Odoo instead of silently reverting to defaults on import.
        now_match = re.search(r'^\s*now\s+(\d{4}-\d{2}-\d{2})', tjp_content, re.MULTILINE)
        parsed_now = now_match.group(1) if now_match else False
        end_match = re.search(
            r'^project\s+\S+\s+"[^"]*"\s+\d{4}-\d{2}-\d{2}\s*-\s*(\d{4}-\d{2}-\d{2})',
            tjp_content, re.MULTILINE,
        )
        parsed_end = end_match.group(1) if end_match else False

        # Normalize timezone IDs against pytz canonical list (handles spaces vs underscores)
        _tz_lookup = {t.replace('_', ' ').lower(): t for t in pytz.all_timezones}
        tjp_content = re.sub(
            r'(timezone\s+")([^"]+)(")',
            lambda m: m.group(1) + _tz_lookup.get(m.group(2).replace('_', ' ').lower(), m.group(2)) + m.group(3),
            tjp_content,
        )

        # Always inject our own taskreports (schedule_<scenario>.csv) so we
        # get consistently-named output regardless of reports in the source.
        # Search scenarios in all content (tjp + tji).
        all_content = tjp_content + '\n' + '\n'.join(include_files.values())
        sc_ids = re.findall(r'\bscenario\s+(\w+)\b', all_content)
        if not sc_ids:
            sc_ids = ['plan']
        for sc_id in sc_ids:
            tjp_content += (
                f'\ntaskreport "schedule_{sc_id}" {{\n'
                f'  formats csv\n'
                f'  columns id, bsi, name, start, end, effort, duration, resources, criticalness, complete\n'
                f'  scenarios {sc_id}\n}}\n'
            )

        response_data = self.project_id._call_tj_microservice(
            url.rstrip('/'), tjp_content, timeout, include_files=include_files
        )
        all_csvs = response_data.get('csv_files', {})
        if not all_csvs:
            stderr = response_data.get('stderr', '')
            raise UserError(
                _('El microservicio no retornó ningún CSV.\n\nVerifique el archivo TJP.\n%s') % stderr
            )

        # Only keep our schedule_*.csv files as the source of truth
        csv_files = {k: v for k, v in all_csvs.items() if k.lower().startswith('schedule_')}
        if not csv_files:
            csv_files = all_csvs  # fallback: use all if naming didn't match

        # Parsear el .tjp fuente con el parser real (tjp_parser) — a
        # diferencia del CSV que devuelve TJ3 (que no tiene columna de
        # dependencias ni de notas), acá se recupera la jerarquía real,
        # `depends`/`precedes`, `allocate` (pool de recursos) y `note` de
        # cada tarea. El CSV se sigue usando más abajo, pero solo para
        # completar fechas/criticidad vía _import_scenario_csv — ya no
        # para crear las tareas (ver action_import).
        roots = tjp_parser.parse_tasks(all_content)
        tasks = self._serialize_tree(roots)

        resource_ids = set()
        for node in tasks:
            resource_ids.update(node['resource_ids'])

        # Enrich resource IDs with display names from source files (best-effort)
        resource_names = {
            m.group(1): m.group(2)
            for m in re.finditer(r'\bresource\s+(\w+)\s+"([^"]+)"', all_content)
        }

        # Rebuild resource mapping lines — auto-match by display name to res.users
        self.resource_map_ids.unlink()
        map_vals = []
        for res_id in sorted(resource_ids):
            display_name = resource_names.get(res_id, res_id)
            user = self.env['res.users'].search([('name', 'ilike', display_name)], limit=1)
            map_vals.append({
                'wizard_id': self.id,
                'tj_resource_id': res_id,
                'tj_resource_name': display_name,
                'user_id': user.id if user else False,
                'action': 'map',
            })
        if map_vals:
            self.env['insight.import.resource.map'].create(map_vals)

        self.write({
            'parsed_tasks_json': json.dumps(tasks),
            'csv_files_json': json.dumps(csv_files),
            'parsed_now': parsed_now,
            'parsed_end': parsed_end,
            'state': 'mapping',
        })
        return self._reopen()

    @staticmethod
    def _serialize_tree(roots):
        """Aplana el árbol de TaskNode de tjp_parser a una lista de dicts
        JSON-serializable, en pre-orden (padre siempre antes que sus
        hijos) — así action_import puede resolver parent_id en una sola
        pasada. Los `depends`/`precedes` ya se resuelven acá (contra el
        árbol completo, con acceso a los nodos reales) a su full_id
        destino — action_import solo necesita buscar ese full_id en el
        mapa de registros ya creados, no reimplementar la resolución de
        '!'."""
        flat = []
        for root in roots:
            for node in root.walk():
                resource_ids = []
                primary_ids = []
                for alloc in node.allocations:
                    resource_ids.append(alloc.primary)
                    resource_ids.extend(alloc.alternatives)
                    primary_ids.append(alloc.primary)
                flat.append({
                    'full_id': node.full_id,
                    'parent_full_id': node.parent.full_id if node.parent else None,
                    'name': node.name,
                    'effort': node.effort,
                    'complete': node.complete,
                    'is_milestone': node.is_milestone,
                    'note': node.note,
                    'primary_ids': primary_ids,
                    'resource_ids': resource_ids,
                    'depends': [
                        {'target': tjp_parser.resolve_dep_ref(node, d.ref), 'modifier': d.modifier}
                        for d in node.raw_depends
                    ],
                    'precedes': [
                        {'target': tjp_parser.resolve_dep_ref(node, d.ref), 'modifier': d.modifier}
                        for d in node.raw_precedes
                    ],
                })
        return flat

    @staticmethod
    def _extract_zip_files(zip_bytes):
        """Extract main .tjp and include files from a ZIP archive.

        Normalises Windows-style backslash separators and only collects
        include files from the same directory as the main .tjp.
        """
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            # Build a map: normalised_path → original_zip_entry_name
            entry_map = {}
            for orig in zf.namelist():
                norm = orig.replace('\\', '/')
                if not norm.endswith('/'):
                    entry_map[norm] = orig

            tjp_names = [n for n in entry_map if n.lower().endswith('.tjp')]
            if not tjp_names:
                raise UserError(_('No se encontró ningún archivo .tjp en el ZIP.'))

            # Prefer a .tjp at root level; otherwise take the first found
            root_tjps = [n for n in tjp_names if '/' not in n]
            main_norm = root_tjps[0] if root_tjps else tjp_names[0]
            main_content = zf.read(entry_map[main_norm]).decode('utf-8', errors='replace')

            # Only collect files from the same directory as the main .tjp
            main_dir = main_norm.rsplit('/', 1)[0] + '/' if '/' in main_norm else ''

            include_files = {}
            for norm_name, orig_name in entry_map.items():
                if norm_name == main_norm:
                    continue
                if main_dir and not norm_name.startswith(main_dir):
                    continue
                basename = norm_name.rsplit('/', 1)[-1]
                if not basename:
                    continue
                try:
                    include_files[basename] = zf.read(orig_name).decode('utf-8', errors='replace')
                except Exception:
                    pass
            return main_content, include_files

    def action_back(self):
        self.state = 'upload'
        return self._reopen()

    # -------------------------------------------------------------------------
    # Step 2: Import
    # -------------------------------------------------------------------------

    def action_import(self):
        self.ensure_one()
        self._check_draft_state()
        self._check_no_timesheets_logged()
        tasks = json.loads(self.parsed_tasks_json or '[]')
        csv_files = json.loads(self.csv_files_json or '{}')
        project = self.project_id

        # Reimportar reemplaza TODO lo que ya existía en el proyecto — no
        # mergea contra un import anterior, para no terminar con tareas
        # duplicadas si el .tjp cambió de estructura entre una corrida y
        # la siguiente. Solo se permite en 'draft' (ver _check_draft_state)
        # precisamente para que esto nunca borre trabajo real: en draft no
        # debería haber timesheets ni schedules comprometidos todavía.
        # insight.task.schedule/insight.task.dependency tienen
        # ondelete='cascade' contra project.task, así que se limpian solos;
        # insight.scenario (a nivel proyecto, no de tarea) no se toca —
        # queda vacío hasta que el import de CSV más abajo lo repuebla.
        self.env['project.task'].with_context(active_test=False).search([
            ('project_id', '=', project.id),
        ]).unlink()
        self.env['project.milestone'].with_context(active_test=False).search([
            ('project_id', '=', project.id),
        ]).unlink()

        # Build user map: tj_resource_id → res.users
        user_map = {}
        for rmap in self.resource_map_ids:
            if rmap.action == 'map' and rmap.user_id:
                user_map[rmap.tj_resource_id] = rmap.user_id

        # Resolve task stages and link them to this project.
        # sudo() required: stages without project_ids are restricted by record rules.
        # task_type_planned xmlid kept stable; its stage was renamed to "Backlog".
        stage_refine = self.env.ref('insight_project.task_type_refine').sudo()
        stage_backlog = self.env.ref('insight_project.task_type_planned').sudo()
        stage_done = self.env.ref('insight_project.task_type_done').sudo()
        # All stages defined for this task type must be available on the
        # imported project's kanban, not just the ones auto-assigned below.
        stage_progress = self.env.ref('insight_project.task_type_progress').sudo()
        stage_review = self.env.ref('insight_project.task_type_review').sudo()
        stage_cancelled = self.env.ref('insight_project.task_type_cancelled').sudo()
        all_stages = (
            stage_refine, stage_backlog, stage_progress,
            stage_review, stage_done, stage_cancelled,
        )
        for stage in all_stages:
            if project.id not in stage.project_ids.ids:
                stage.project_ids = [(4, project.id)]

        # Pass 1: crear tareas/milestones. `tasks` viene en pre-orden
        # (_serialize_tree recorre el árbol padre-antes-que-hijo), así que
        # parent_full_id siempre está ya resuelto en record_by_full_id
        # para cuando hace falta. resource_pool_ids se llena con el pool
        # de candidatos de `allocate` (no con quién terminó realmente
        # asignado — eso lo corrige _sync_gantt_dates más abajo a partir
        # del escenario baseline, igual que en un reschedule normal).
        record_by_full_id = {}  # full_id -> ('task'|'milestone', odoo_id)
        for node in tasks:
            if node.get('is_milestone'):
                if not project.allow_milestones:
                    project.allow_milestones = True
                milestone = self.env['project.milestone'].create({
                    'name': node['name'] or node['full_id'],
                    'project_id': project.id,
                })
                record_by_full_id[node['full_id']] = ('milestone', milestone.id)
                continue

            pool_ids = [
                user_map[tj_id].id for tj_id in node.get('resource_ids', [])
                if user_map.get(tj_id)
            ]
            # user_ids arranca solo con el recurso PRIMARIO de cada
            # `allocate` (no todo el pool con alternativas, que sí va a
            # resource_pool_ids) — un default razonable de "a quién se le
            # asigna" antes de correr ningún schedule. Si más adelante se
            # ejecuta un reschedule, _sync_gantt_dates corrige esto solo a
            # partir de a quién asignó realmente el escenario baseline.
            assigned_ids = [
                user_map[tj_id].id for tj_id in node.get('primary_ids', [])
                if user_map.get(tj_id)
            ]
            stage = self._resolve_task_stage(
                {
                    'complete': node.get('complete') or '0',
                    'effort': node.get('effort') or '',
                    'resources': assigned_ids,
                },
                stage_refine, stage_backlog, stage_done,
            )
            parent_ref = record_by_full_id.get(node.get('parent_full_id'))
            parent_task_id = parent_ref[1] if parent_ref and parent_ref[0] == 'task' else False
            vals = {
                'name': node['name'] or node['full_id'],
                'project_id': project.id,
                'parent_id': parent_task_id,
                'allocated_hours': self._effort_to_hours(node.get('effort') or ''),
                'resource_pool_ids': [(6, 0, pool_ids)],
                'user_ids': [(6, 0, assigned_ids)],
                'description': node.get('note') or False,
                'stage_id': stage.id,
            }
            if stage == stage_done:
                # project.task.state (nativo, distinto de stage_id) no se
                # deriva de la etapa — _compute_state solo alterna entre
                # 'en progreso'/'esperando' según dependencias abiertas, y
                # respeta un valor ya cerrado ('done'/'cancelado') sin
                # pisarlo. Sin esto, una tarea importada 100% completa
                # quedaba con state='en progreso' (o 'esperando' si algo
                # dependía de ella), aunque su stage_id ya mostrara
                # "Completada" — y de paso arrastraba a sus dependientes a
                # verse "esperando" una tarea que en realidad ya terminó.
                vals['state'] = '1_done'
            task = self.env['project.task'].create(vals)
            record_by_full_id[node['full_id']] = ('task', task.id)

        # Pass 2: resolver depends/precedes (tareas reales) y task_ids
        # (milestones) contra record_by_full_id — necesita que TODAS las
        # tareas ya existan, porque una dependencia puede apuntar hacia
        # adelante en el árbol. Referencias a tareas fuera de este import
        # (ej. otro "eje" en un archivo separado) se ignoran en silencio,
        # no hay nada contra qué linkear.
        for node in tasks:
            ref = record_by_full_id.get(node['full_id'])
            if not ref:
                continue
            kind, odoo_id = ref
            if kind == 'milestone':
                dep_task_ids = [
                    target[1] for dep in node.get('depends', [])
                    if (target := record_by_full_id.get(dep['target'])) and target[0] == 'task'
                ]
                if dep_task_ids:
                    self.env['project.milestone'].browse(odoo_id).task_ids = [(6, 0, dep_task_ids)]
                continue

            depend_on_ids = []
            overrides = []  # (depends_on_id, dependency_type)
            for dep in node.get('depends', []):
                target = record_by_full_id.get(dep['target'])
                if not target or target[0] != 'task':
                    continue
                depend_on_ids.append(target[1])
                if dep.get('modifier') == 'onstart':
                    overrides.append((target[1], 'SS'))
            for dep in node.get('precedes', []):
                target = record_by_full_id.get(dep['target'])
                if not target or target[0] != 'task':
                    continue
                depend_on_ids.append(target[1])
                overrides.append((target[1], 'FF'))
            if not depend_on_ids:
                continue
            self.env['project.task'].browse(odoo_id).depend_on_ids = [(6, 0, depend_on_ids)]
            for depends_on_id, dep_type in overrides:
                self.env['insight.task.dependency'].create({
                    'task_id': odoo_id, 'depends_on_id': depends_on_id,
                    'dependency_type': dep_type,
                })

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

        project._sync_gantt_dates()

        vals = {
            'is_tj_enabled': True,
            'schedule_dirty': False,
            'last_scheduled': fields.Datetime.now(),
        }
        if self.parsed_now:
            vals['date_start'] = self.parsed_now
        if self.parsed_end:
            vals['date'] = self.parsed_end
            # project.project.write() descarta un `date` sin `date_start`
            # (par tratado como rango) si el proyecto todavía no tiene uno.
            if 'date_start' not in vals and not project.date_start:
                vals['date_start'] = self.parsed_now or fields.Date.today()
        project.write(vals)

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
    def _resolve_task_stage(task_data, stage_refine, stage_backlog, stage_done):
        # 100% complete → done
        raw = task_data.get('complete', '0').replace('%', '').strip()
        try:
            if float(raw) >= 100:
                return stage_done
        except ValueError:
            pass
        # No effort AND no resources → needs refinement
        effort = task_data.get('effort', '').strip()
        zero_effort = not effort or re.match(r'^0+(\.0+)?[dhw]?$', effort)
        if zero_effort and not task_data.get('resources'):
            return stage_refine
        return stage_backlog

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
        ('map', 'Mapear a usuario'),
        ('skip', 'Ignorar'),
    ], string='Acción', required=True, default='map')
    user_id = fields.Many2one('res.users', string='Usuario Odoo')
