# -*- coding: utf-8 -*-
{
    'name': "Insight Project — TaskJuggler Integration",
    'summary': "Schedules Odoo projects via TaskJuggler 3 microservice",
    'version': '17.0.1.1.0',
    'category': 'Project',
    'author': "Cristian S. Rocha <csrocha@gmail.com>",
    'website': "https://github.com/csrocha/insight_project",
    'license': 'OPL-1',
    'depends': ['project', 'hr_holidays'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/insight_scenario_views.xml',
        'views/insight_resource_views.xml',
        'views/project_project_views.xml',
        'views/project_task_views.xml',
    ],
    'installable': True,
    'application': False,
}
