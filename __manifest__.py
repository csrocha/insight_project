# -*- coding: utf-8 -*-
{
    'name': "Insight Project — TaskJuggler Integration",
    'summary': "Schedules Odoo projects via TaskJuggler 3 microservice",
    'version': '17.0.6.0.2',
    'category': 'Project',
    'author': "Cristian S. Rocha <csrocha@gmail.com>",
    'website': "https://github.com/csrocha/insight_project",
    'license': 'OPL-1',
    'depends': ['project', 'hr_holidays', 'hr_attendance', 'project_timesheet_holidays'],
    'data': [
        'security/ir.model.access.csv',
        'security/insight_user_session_security.xml',
        'data/insight_project_stages.xml',
        'data/insight_session_message_templates.xml',
        'views/res_config_settings_views.xml',
        'views/insight_scenario_views.xml',
        'views/project_project_views.xml',
        'views/project_task_views.xml',
        'views/insight_import_wizard_views.xml',
        'views/insight_session_message_template_views.xml',
        'views/insight_session_switch_wizard_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'insight_project/static/src/**/*',
        ],
    },
    'installable': True,
    'application': False,
}
