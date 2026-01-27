# -*- coding: utf-8 -*-
{
    'name': 'Padrón API Santa Fe - Retenciones y Percepciones IIBB',
    'version': '16.0.1.0.0',
    'description': '''
        Módulo para gestión del Padrón de Alícuotas de Retención y Percepción (PARP)
        de la Provincia de Santa Fe según Resolución API SF 37/2025.
        
        Características principales:
        - Importación del padrón mensual PARP
        - Asignación automática de alícuotas a partners
        - Configuración de alícuotas por defecto para sujetos no incluidos
        - Soporte para diferentes tipos de alícuotas (general, carnes, especiales)
        
        Referencias:
        - Resolución (API Santa Fe) 37/2025
        - RG API Santa Fe 15/1997 (modificada)
    ''',
    'summary': 'Padrón de Alícuotas IIBB Santa Fe - PARP',
    'author': 'Chapas Rosario',
    'website': '',
    'license': 'LGPL-3',
    'category': 'Accounting/Localizations',
    'depends': [
        'l10n_ar_account_withholding',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/res_company_jurisdiction_padron_api_sf_views.xml',
        'views/res_partner_view.xml',
    ],
    'demo': [],
    'auto_install': False,
    'application': False,
    'installable': True,
}
