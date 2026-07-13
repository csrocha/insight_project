from odoo import models


class ReportInsightProjectCostReportHtml(models.AbstractModel):
    _name = 'report.insight_project.report_cost_report_html'
    _description = 'Reporte HTML de costo (fase/skill/departamento)'

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
        items = payload.get('items') or []
        max_cost = max((item.get('cost', 0.0) for item in items), default=0.0) or 1.0
        rows = [{
            'label': item.get('label') or '',
            'cost': item.get('cost', 0.0),
            'percent': min((item.get('cost', 0.0) / max_cost) * 100.0, 100.0),
        } for item in items]
        return {
            'asset': asset,
            'title': payload.get('title') or asset.name,
            'currency': payload.get('currency') or '',
            'total': payload.get('total') or 0.0,
            'generated_at': payload.get('generated_at') or '',
            'rows': rows,
        }
