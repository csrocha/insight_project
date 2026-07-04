# -*- coding: utf-8 -*-
{
    'name': "Insight Project — TaskJuggler Integration",
    'summary': "Schedules Odoo projects via TaskJuggler 3 microservice",
    'version': '17.0.9.0.0',
    'category': 'Project',
    'author': "Cristian S. Rocha <csrocha@gmail.com>",
    'website': "https://github.com/csrocha/insight_project",
    'license': 'OPL-1',
    'depends': ['project_improve', 'project', 'hr_holidays', 'hr_attendance', 'project_timesheet_holidays'],
    'data': [
        'security/ir.model.access.csv',
        'data/insight_project_stages.xml',
        'data/insight_cron.xml',
        'views/res_config_settings_views.xml',
        'views/insight_scenario_views.xml',
        'views/project_project_views.xml',
        'views/project_task_views.xml',
        'views/insight_import_wizard_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
}
