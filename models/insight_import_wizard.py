# -*- coding: utf-8 -*-
import base64
import csv
import io
import json
import os
import re
import zipfile

import pytz

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

        # Best-effort detection of which TJ ids carry a bare `milestone`
        # attribute in the source .tjp, so the resulting Odoo task can be
        # linked to a project.milestone on import instead of silently
        # losing that information (see _find_milestone_task_ids).
        milestone_tj_ids = self._find_milestone_task_ids(all_content)

        # Parse tasks and resource IDs from TJ3 output (first schedule CSV)
        first_csv = next(iter(csv_files.values()))
        tasks, resource_ids = self._parse_csv_preview(first_csv, milestone_tj_ids)

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
    def _find_milestone_task_ids(tjp_text):
        """Best-effort detection of which TJ ids carry a bare `milestone`
        attribute, by scanning from each `task <id> "<name>" {` opening
        line up to the next `task` keyword found forward (its own nested
        subtask, or the next sibling once its block closes) — TJ3 authors
        write attributes right after the opening brace, before any nested
        subtasks, same convention our own exporter follows. Not a real
        parser (no brace-matching), so it's a heuristic, not a guarantee."""
        milestone_ids = set()
        opens = list(re.finditer(r'\btask\s+(\S+)\s+"[^"]*"\s*\{', tjp_text))
        for i, match in enumerate(opens):
            tj_id = match.group(1)
            start = match.end()
            end = opens[i + 1].start() if i + 1 < len(opens) else len(tjp_text)
            block = tjp_text[start:end]
            if re.search(r'^\s*milestone\b', block, re.MULTILINE):
                milestone_ids.add(tj_id)
        return milestone_ids

    @staticmethod
    def _parse_csv_preview(csv_content, milestone_tj_ids=None):
        milestone_tj_ids = milestone_tj_ids or set()
        # TJ3 uses semicolons as CSV delimiter
        first_line = csv_content.split('\n')[0] if csv_content else ''
        delimiter = ';' if ';' in first_line else ','
        reader = csv.DictReader(io.StringIO(csv_content), delimiter=delimiter)
        tasks = []
        resource_ids = set()
        for row in reader:
            norm = {k.strip().lower(): (v or '').strip() for k, v in row.items() if k is not None}
            res_str = norm.get('resources', '')
            # TJ3 formats resources as "Full Name (resource_id)" — extract the ID in parens
            task_res = re.findall(r'\((\w+)\)', res_str)
            if not task_res and res_str:
                # Fallback: plain comma/space-separated IDs (no parens)
                task_res = [r.strip() for r in re.split(r'[,;]+', res_str) if r.strip()]
            resource_ids.update(task_res)
            # 'id' is the dotted TJ3 path (e.g. "root.sub.leaf"); its last
            # segment is the local id used in the source `task <id> "..."`.
            leaf_tj_id = norm.get('id', '').split('.')[-1]
            tasks.append({
                'bsi': norm.get('bsi', ''),
                'name': norm.get('name', ''),
                'effort': norm.get('effort', ''),
                'resources': task_res,
                'complete': norm.get('complete', '0'),
                'is_milestone': leaf_tj_id in milestone_tj_ids,
            })
        return tasks, resource_ids

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
        tasks = json.loads(self.parsed_tasks_json or '[]')
        csv_files = json.loads(self.csv_files_json or '{}')
        project = self.project_id

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

        # Create task hierarchy ordered by BSI
        bsi_task_id = {}
        sorted_tasks = sorted(tasks, key=lambda t: self._bsi_sort_key(t['bsi']))
        for task_data in sorted_tasks:
            bsi = task_data['bsi']
            parent_bsi = '.'.join(bsi.split('.')[:-1]) if '.' in bsi else None

            user_ids = [
                user_map[res_id].id
                for res_id in task_data.get('resources', [])
                if user_map.get(res_id)
            ]
            stage = self._resolve_task_stage(
                task_data, stage_refine, stage_backlog, stage_done
            )
            task = self.env['project.task'].create({
                'name': task_data['name'] or f'Tarea {bsi}',
                'project_id': project.id,
                'parent_id': bsi_task_id.get(parent_bsi) if parent_bsi else False,
                'allocated_hours': self._effort_to_hours(task_data.get('effort', '')),
                'user_ids': [(6, 0, user_ids)],
                'stage_id': stage.id,
            })
            bsi_task_id[bsi] = task.id
            if task_data.get('is_milestone'):
                if not project.allow_milestones:
                    project.allow_milestones = True
                milestone = self.env['project.milestone'].create({
                    'name': task_data['name'] or f'Hito {bsi}',
                    'project_id': project.id,
                })
                task.milestone_id = milestone.id

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
        ('map', 'Mapear a usuario'),
        ('skip', 'Ignorar'),
    ], string='Acción', required=True, default='map')
    user_id = fields.Many2one('res.users', string='Usuario Odoo')
