from odoo import models


class ReportInsightProjectDeviationReportHtml(models.AbstractModel):
    _name = 'report.insight_project.report_deviation_report_html'
    _description = 'Reporte HTML de desviación (baseline vs. real)'

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
        rows = [{
            'name': item.get('name') or '',
            'baseline_end': item.get('baseline_end') or '',
            'current_end': item.get('current_end') or '',
            'end_delta_days': item.get('end_delta_days'),
            'baseline_cost': item.get('baseline_cost', 0.0),
            'current_cost': item.get('current_cost', 0.0),
            'cost_delta': item.get('cost_delta', 0.0),
            'complete': item.get('complete', 0.0),
        } for item in (payload.get('items') or [])]
        return {
            'asset': asset,
            'currency': payload.get('currency') or '',
            'generated_at': payload.get('generated_at') or '',
            'frozen_at': payload.get('frozen_at') or '',
            'rows': rows,
            'total_baseline_cost': payload.get('total_baseline_cost', 0.0),
            'total_current_cost': payload.get('total_current_cost', 0.0),
            'total_cost_delta': payload.get('total_cost_delta', 0.0),
            'planned_value': payload.get('planned_value'),
            'earned_value': payload.get('earned_value'),
            'actual_cost': payload.get('actual_cost'),
            'cost_performance_index': payload.get('cost_performance_index'),
            'schedule_performance_index': payload.get('schedule_performance_index'),
        }
