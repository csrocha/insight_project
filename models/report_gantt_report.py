# -*- coding: utf-8 -*-
import calendar
import hashlib
import json
from datetime import datetime

from odoo import models


def _esc(s):
    return (str(s)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


def _bsi_key(bsi):
    return [int(p) if p.isdigit() else p for p in (bsi or '0').split('.')]


def _parse_dt(value):
    return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')


def render_gantt_svg(payload):
    """Renderer puro: toma el payload JSON del knowledge.asset de Gantt (ver
    project.project._tj_gantt_schedule_payload) y devuelve el SVG — mismo
    dibujo que antes generaba project_project._render_gantt_svg en vivo,
    ahora leyendo desde el payload ya persistido en vez de volver a
    consultar el ORM. Sin acceso a ORM: testeable con un dict a mano."""
    tasks = payload.get('tasks') or []
    if not tasks:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="90"'
            ' font-family="Arial, sans-serif">'
            '<rect width="640" height="90" fill="#fafafa"/>'
            '<text x="32" y="50" font-size="13" fill="#757575">'
            'No hay datos de schedule. Ejecute "Replanificar" primero.</text>'
            '</svg>'
        )

    scenarios = payload.get('scenarios') or []
    BAR_NORMAL   = ['#43A047', '#1E88E5', '#FB8C00', '#8E24AA', '#00ACC1']
    BAR_CRITICAL = ['#C62828', '#1565C0', '#E65100', '#6A1B9A', '#00695C']
    sc_color = {
        sc['id']: (BAR_NORMAL[i % 5], BAR_CRITICAL[i % 5])
        for i, sc in enumerate(scenarios)
    }
    sc_name = {sc['id']: sc['name'] for sc in scenarios}

    min_dt = min(_parse_dt(t['start']) for t in tasks)
    max_dt = max(_parse_dt(t['end']) for t in tasks)
    span_secs = max((max_dt - min_dt).total_seconds(), 86400.0)

    # Group by BSI in sorted order
    groups = {}
    for t in tasks:
        groups.setdefault(t.get('bsi') or '?', []).append(t)
    ordered_bsis = sorted(groups.keys(), key=_bsi_key)

    # Layout
    LW, RW = 340, 1060
    TW = LW + RW
    RH = 26
    HDR, LEG, AXIS = 56, 24, 24
    TOP = HDR + LEG + AXIS

    n_rows = sum(len(v) for v in groups.values())
    TH = TOP + n_rows * RH + 16

    def xp(dt):
        return LW + (dt - min_dt).total_seconds() / span_secs * RW

    # Id único del <svg> — el <script> del final lo busca por
    # getElementById en vez de document.currentScript: ese último no está
    # confiablemente soportado para <script> embebido dentro de <svg> (es
    # un mecanismo del modelo de scripts de HTML, no del de SVG), y si
    # devuelve null el script entero aborta silenciosamente sin conectar
    # los listeners del toggle. Determinístico (hash del payload) para que
    # los tests puedan reproducirlo sin mockear random/uuid.
    svg_id = 'gantt-' + hashlib.md5(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:10]

    o = []
    o.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" id="{svg_id}" width="{TW}" height="{TH}"'
        f' font-family="Arial, Helvetica, sans-serif" font-size="11">'
    )
    o.append(
        '<style>'
        '.gantt-legend-item{cursor:pointer}'
        '.gantt-legend-item.gantt-inactive{opacity:0.35}'
        '.gantt-hidden{display:none}'
        '</style>'
    )
    o.append(f'<rect width="{TW}" height="{TH}" fill="#ffffff"/>')

    # Title + subtitle
    o.append(
        f'<text x="10" y="22" font-size="15" font-weight="bold" fill="#212121">'
        f'{_esc(payload.get("title") or "Proyecto")}</text>'
    )
    last_scheduled = payload.get('last_scheduled')
    if last_scheduled:
        o.append(
            f'<text x="10" y="40" font-size="10" fill="#9E9E9E">'
            f'Último schedule: {_esc(last_scheduled[:16])} UTC</text>'
        )

    # Scenario legend — cada item es clickeable (ver <script> al final):
    # alterna mostrar/ocultar las barras/flechas de ese escenario sin volver
    # a generar el reporte. Todos arrancan activos.
    xl, yl = 10, HDR + 16
    for sc in scenarios:
        cn, _cc = sc_color[sc['id']]
        o.append(f'<g class="gantt-legend-item" data-scenario="{sc["id"]}">')
        o.append(f'<rect x="{xl}" y="{yl-11}" width="13" height="13" fill="{cn}" rx="2"/>')
        o.append(f'<text x="{xl+17}" y="{yl}" fill="#424242">{_esc(sc["name"])}</text>')
        o.append('</g>')
        xl += 20 + len(sc['name']) * 7
    o.append(
        f'<text x="{xl+6}" y="{yl}" fill="#C62828" font-weight="bold">⚡ camino crítico</text>'
    )

    # Left / right divider
    o.append(
        f'<line x1="{LW}" y1="{HDR}" x2="{LW}" y2="{TH}"'
        f' stroke="#BDBDBD" stroke-width="1"/>'
    )

    # Month grid lines + labels
    ms = datetime(min_dt.year, min_dt.month, 1)
    while ms <= max_dt:
        if ms >= min_dt:
            mx = xp(ms)
            o.append(
                f'<line x1="{mx:.1f}" y1="{TOP}" x2="{mx:.1f}" y2="{TH}"'
                f' stroke="#F0F0F0" stroke-width="1"/>'
            )
            o.append(
                f'<text x="{mx+3:.1f}" y="{HDR+LEG+17}"'
                f' fill="#9E9E9E" font-size="10">'
                f'{calendar.month_abbr[ms.month]} {ms.year}</text>'
            )
        ms = datetime(ms.year + (ms.month == 12), ms.month % 12 + 1, 1)

    # "Today" marker (UTC)
    now_utc = datetime.utcnow()
    if min_dt <= now_utc <= max_dt:
        nx = xp(now_utc)
        o.append(
            f'<line x1="{nx:.1f}" y1="{TOP}" x2="{nx:.1f}" y2="{TH}"'
            f' stroke="#E53935" stroke-width="1.5"'
            f' stroke-dasharray="5,3" opacity="0.7"/>'
        )
        o.append(
            f'<text x="{nx+2:.1f}" y="{HDR+LEG+17}"'
            f' fill="#E53935" font-size="9" font-weight="bold">Hoy</text>'
        )

    # Task rows
    yc = TOP
    positions = {}  # (task_id, scenario_id) -> (x_start, x_end, y_center), para las flechas de dependencia
    for bsi in ordered_bsis:
        rows = groups[bsi]
        first = rows[0]
        indent = bsi.count('.') * 12

        for ridx, t in enumerate(rows):
            bg = '#FAFAFA' if (yc // RH) % 2 == 0 else '#FFFFFF'
            o.append(f'<rect x="0" y="{yc}" width="{TW}" height="{RH}" fill="{bg}"/>')

            if ridx == 0:
                weight = 'bold' if not first.get('parent_id') else 'normal'
                label = _esc((first.get('name') or '')[:44])
                o.append(
                    f'<text x="{8+indent}" y="{yc+17}" fill="#424242">'
                    f'<tspan font-size="10" fill="#9E9E9E">{_esc(bsi)} </tspan>'
                    f'<tspan font-weight="{weight}">{label}</tspan></text>'
                )

            x1 = xp(_parse_dt(t['start']))
            x2 = xp(_parse_dt(t['end']))
            bw = max(x2 - x1, 4.0)
            positions[(t['task_id'], t['scenario_id'])] = (x1, x1 + bw, yc + RH / 2)
            cn, cc = sc_color.get(t['scenario_id'], (BAR_NORMAL[0], BAR_CRITICAL[0]))
            fill = cc if t.get('is_critical_path') else cn
            stroke = ' stroke="#b71c1c" stroke-width="1.5"' if t.get('is_critical_path') else ''
            o.append(f'<g class="gantt-bar-group" data-scenario="{t["scenario_id"]}">')
            o.append(
                f'<rect x="{x1:.1f}" y="{yc+5}" width="{bw:.1f}" height="{RH-10}"'
                f' fill="{fill}" rx="3" opacity="0.88"{stroke}/>'
            )
            complete = t.get('complete') or 0.0
            if complete > 0:
                # Franja de avance real (project.task.progress al momento
                # del export, ver _tjp_task_block) sobre el borde inferior
                # de la barra — no lo calcula TJ3, es solo visual.
                complete_w = bw * min(complete, 100.0) / 100.0
                o.append(
                    f'<rect x="{x1:.1f}" y="{yc+RH-8}" width="{complete_w:.1f}" height="3"'
                    f' fill="#212121" opacity="0.55" rx="1.5"/>'
                )
            if t.get('is_critical_path'):
                o.append(
                    f'<text x="{x1+bw+2:.1f}" y="{yc+15}" font-size="10">⚡</text>'
                )
            if len(scenarios) > 1 and bw > 50:
                o.append(
                    f'<text x="{x1+4:.1f}" y="{yc+15}"'
                    f' fill="white" font-size="9" font-weight="bold">'
                    f'{_esc((sc_name.get(t["scenario_id"]) or "")[:9])}</text>'
                )
            o.append('</g>')

            yc += RH

    # Flechas de dependencia: conector desde el fin de la barra bloqueante
    # hasta el inicio de la barra dependiente, por escenario (una dependencia
    # es estructural del proyecto, no de un escenario puntual — se dibuja en
    # cada escenario donde ambas puntas tengan una barra).
    ARROW = '#757575'
    STUB = 6
    for dep in payload.get('dependencies') or []:
        task_id, depends_on_id = dep.get('task_id'), dep.get('depends_on_id')
        for sc in scenarios:
            src = positions.get((depends_on_id, sc['id']))
            dst = positions.get((task_id, sc['id']))
            if not src or not dst:
                continue
            _src_x1, src_x2, src_y = src
            dst_x1, _dst_x2, dst_y = dst
            mx = src_x2 + STUB

            if mx <= dst_x1 - STUB:
                # Espacio suficiente entre el fin del bloqueante y el
                # inicio de la dependiente: conector simple en escuadra.
                points = [(src_x2, src_y), (mx, src_y), (mx, dst_y), (dst_x1 - 4, dst_y)]
            else:
                # Tareas que arrancan de inmediato (o se solapan): el
                # conector directo entraría por encima/atrás del inicio de
                # la dependiente, así que rodea en forma de "S invertida" —
                # sale a la derecha del bloqueante, corta por el medio entre
                # ambas filas y entra por la izquierda de la dependiente.
                left_x = dst_x1 - STUB
                mid_y = (src_y + dst_y) / 2 if src_y != dst_y else src_y - RH / 2
                points = [
                    (src_x2, src_y), (mx, src_y), (mx, mid_y),
                    (left_x, mid_y), (left_x, dst_y), (dst_x1 - 4, dst_y),
                ]

            path_d = ' '.join(
                f'{"M" if i == 0 else "L"} {x:.1f},{y:.1f}'
                for i, (x, y) in enumerate(points)
            )
            o.append(f'<g class="gantt-dep-group" data-scenario="{sc["id"]}">')
            o.append(
                f'<path d="{path_d}" fill="none" stroke="{ARROW}"'
                f' stroke-width="1" opacity="0.6"/>'
            )
            o.append(
                f'<path d="M {dst_x1-4:.1f},{dst_y-3:.1f} L {dst_x1:.1f},{dst_y:.1f}'
                f' L {dst_x1-4:.1f},{dst_y+3:.1f} Z" fill="{ARROW}" opacity="0.6"/>'
            )
            o.append('</g>')

    # Toggle de leyenda: clickear un escenario en la leyenda muestra/oculta
    # sus barras y flechas de dependencia sin recargar el reporte. Busca su
    # propio <svg> por id (no por document.currentScript.closest: ese
    # mecanismo es del modelo de scripts de HTML y no está garantizado para
    # un <script> embebido dentro de un <svg> — si devuelve null, el script
    # entero aborta sin conectar ningún listener) para no pisar otros Gantt
    # embebidos en la misma página del reporte HTML.
    o.append(
        '<script>(function(){'
        f'var svg=document.getElementById("{svg_id}");'
        'if(!svg)return;'
        'var items=svg.querySelectorAll(".gantt-legend-item");'
        'for(var i=0;i<items.length;i++){'
        '(function(item){'
        'item.addEventListener("click",function(){'
        'var sc=item.getAttribute("data-scenario");'
        'item.classList.toggle("gantt-inactive");'
        'var targets=svg.querySelectorAll('
        '".gantt-bar-group[data-scenario=\\"" + sc + "\\"], '
        '.gantt-dep-group[data-scenario=\\"" + sc + "\\"]");'
        'for(var j=0;j<targets.length;j++){targets[j].classList.toggle("gantt-hidden");}'
        '});'
        '})(items[i]);'
        '}'
        '})();</script>'
    )

    o.append('</svg>')
    return '\n'.join(o)


class ReportInsightProjectGanttReportSvg(models.AbstractModel):
    _name = 'report.insight_project.report_gantt_report_svg'
    _description = 'Reporte Gantt SVG (desde knowledge.asset)'

    def _get_report_values(self, docids, data=None):
        docs = self.env['knowledge.asset'].browse(docids)
        return {
            'docs': docs,
            'reports': [self._build_report_context(asset) for asset in docs],
        }

    @staticmethod
    def _build_report_context(asset):
        version = asset.latest_version()
        payload = (version.payload or {}) if version else {}
        return {'asset': asset, 'svg': render_gantt_svg(payload)}
