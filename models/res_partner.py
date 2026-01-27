# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields


class ResPartnerApiSf(models.Model):
    """
    Extensión de res.partner para gestión de alícuotas Santa Fe
    """
    _inherit = 'res.partner'

    def action_update_alicuot_api_sf(self):
        """
        Actualiza la alícuota del partner desde el último padrón PARP de Santa Fe cargado.
        
        Busca el padrón más reciente y actualiza o aplica alícuota por defecto
        según Resolución API SF 37/2025.
        """
        for partner in self:
            if not partner.vat:
                continue
                
            # Buscar el padrón más reciente de Santa Fe
            padron = self.env['res.company.jurisdiction.padron.api.sf'].search([
                ('state', '=', 'done'),
            ], limit=1, order='id desc')
            
            if padron:
                padron.action_update_partner_alicuot(partner)
            else:
                # Si no hay padrón, intentar con cualquiera cargado
                padron = self.env['res.company.jurisdiction.padron.api.sf'].search(
                    [], limit=1, order='id desc'
                )
                if padron:
                    padron.action_update_partner_alicuot(partner)


class ResPartnerArbaAlicuotApiSf(models.Model):
    """
    Extensión del modelo de alícuotas para Santa Fe
    """
    _inherit = 'res.partner.arba_alicuot'
    
    date_last_update = fields.Datetime(
        string='Última actualización',
        readonly=True,
        help='Fecha y hora de la última actualización de la alícuota',
    )
