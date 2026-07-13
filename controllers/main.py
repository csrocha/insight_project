# -*- coding: utf-8 -*-
from odoo import http
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
