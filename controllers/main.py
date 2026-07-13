# -*- coding: utf-8 -*-
from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request


class InsightProjectGantt(http.Controller):

    @http.route(
        '/insight_project/gantt/<int:project_id>',
        auth='user',
        type='http',
        methods=['GET'],
    )
    def gantt(self, project_id, **kwargs):
        project = request.env['project.project'].browse(project_id)
        if not project.exists() or not project.is_tj_enabled:
            return request.not_found()
        svg = project._render_gantt_svg()
        return request.make_response(
            svg,
            headers=[
                ('Content-Type', 'image/svg+xml; charset=utf-8'),
                ('X-Content-Type-Options', 'nosniff'),
            ],
        )


class InsightProjectCostReport(http.Controller):
    """Rendering de los reportes de costo (ver
    project.project._compute_and_save_cost_reports) guardados como
    knowledge.asset — knowledge_asset deliberadamente no rendariza nada,
    eso queda a cargo de cada consumidor (ver su AGENTS.md)."""

    @http.route(
        '/insight_project/cost_report/<int:asset_id>',
        auth='user',
        type='http',
        methods=['GET'],
    )
    def cost_report(self, asset_id, **kwargs):
        asset = request.env['knowledge.asset'].browse(asset_id)
        # Sin sudo(): el ir.rule de knowledge.asset (owner/shared/company)
        # decide el acceso — no se delega en el modelo relacionado. Leer
        # cualquier campo (asset.name, .latest_version()) puede levantar
        # AccessError si el usuario no tiene permiso; se captura acá en vez
        # de dejarla propagar como un 500 (mismo patrón que el controller
        # propio de knowledge_asset).
        try:
            if not asset.exists():
                return request.not_found()
            version = asset.latest_version()
            asset_name = asset.name
        except (AccessError, MissingError):
            return request.not_found()
        if not version:
            return request.not_found()
        html = self._render_bar_chart(asset_name, version.payload or {})
        return request.make_response(
            html,
            headers=[
                ('Content-Type', 'text/html; charset=utf-8'),
                ('X-Content-Type-Options', 'nosniff'),
            ],
        )

    @staticmethod
    def _render_bar_chart(asset_name, payload):
        def _esc(value):
            return (str(value)
                    .replace('&', '&amp;')
                    .replace('<', '&lt;')
                    .replace('>', '&gt;')
                    .replace('"', '&quot;'))

        title = payload.get('title') or asset_name
        currency = payload.get('currency') or ''
        items = payload.get('items') or []
        total = payload.get('total') or 0.0
        generated_at = payload.get('generated_at') or ''

        LW, BAR_MAX_W, ROW_H = 220, 400, 28
        TOP = 60
        width = LW + BAR_MAX_W + 100
        height = TOP + max(len(items), 1) * ROW_H + 20
        max_value = max((item.get('cost', 0.0) for item in items), default=0.0) or 1.0

        rows = []
        y = TOP
        for item in items:
            label = _esc((item.get('label') or '')[:40])
            cost = item.get('cost', 0.0)
            bar_w = max((cost / max_value) * BAR_MAX_W, 2.0)
            rows.append(
                f'<text x="8" y="{y + 18}" font-size="12" fill="#424242">{label}</text>'
                f'<rect x="{LW}" y="{y + 4}" width="{bar_w:.1f}" height="{ROW_H - 10}"'
                f' fill="#1E88E5" rx="3"/>'
                f'<text x="{LW + bar_w + 6:.1f}" y="{y + 18}" font-size="11" fill="#212121">'
                f'{cost:,.2f} {_esc(currency)}</text>'
            )
            y += ROW_H

        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"'
            f' font-family="Arial, Helvetica, sans-serif">'
            f'<rect width="{width}" height="{height}" fill="#ffffff"/>'
            f'<text x="8" y="24" font-size="15" font-weight="bold" fill="#212121">{_esc(title)}</text>'
            f'<text x="8" y="42" font-size="10" fill="#9E9E9E">'
            f'Total: {total:,.2f} {_esc(currency)} — Generado: {_esc(generated_at)}</text>'
            + ''.join(rows)
            + '</svg>'
        )
        if not items:
            svg = svg.replace(
                '</svg>',
                '<text x="8" y="80" font-size="12" fill="#757575">Sin datos.</text></svg>',
            )
        return (
            '<!doctype html><html><head><meta charset="utf-8">'
            f'<title>{_esc(title)}</title></head>'
            f'<body style="margin:0;padding:16px;background:#fafafa">{svg}</body></html>'
        )
