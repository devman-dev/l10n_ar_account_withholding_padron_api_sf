# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models, fields, _


class ResPartnerApiSf(models.Model):
    """
    Extensión de res.partner para gestión de alícuotas Santa Fe
    """
    _inherit = 'res.partner'

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override para auto-buscar en padrón PARP de Santa Fe al crear partners.
        """
        partners = super().create(vals_list)
        
        # Auto-buscar en padrón solo para partners con CUIT
        for partner in partners:
            if partner.vat and partner.l10n_ar_gross_income_type in ['local', 'multilateral']:
                # Buscar el padrón más reciente de Santa Fe procesado
                padron = self.env['res.company.jurisdiction.padron.api.sf'].search([
                    ('state', '=', 'done'),
                ], limit=1, order='id desc')
                
                if padron:
                    try:
                        padron.action_update_partner_alicuot(partner)
                    except Exception:
                        pass  # No interrumpir creación si falla
        
        return partners

    def action_update_alicuot_api_sf(self):
        """
        Actualiza la alícuota del partner desde el último padrón PARP de Santa Fe cargado.
        
        Busca el padrón más reciente y actualiza o aplica alícuota por defecto
        según Resolución API SF 37/2025.
        """
        messages = []
        
        for partner in self:
            if not partner.vat:
                messages.append(_('Partner %s: Sin CUIT definido') % partner.name)
                continue
            
            if partner.l10n_ar_gross_income_type == 'exempt':
                messages.append(_('Partner %s: Exento de IIBB - no aplica') % partner.name)
                continue
                
            # Buscar el padrón más reciente de Santa Fe procesado
            padron = self.env['res.company.jurisdiction.padron.api.sf'].search([
                ('state', '=', 'done'),
            ], limit=1, order='id desc')
            
            if not padron:
                # Si no hay padrón procesado, intentar con cualquiera cargado
                padron = self.env['res.company.jurisdiction.padron.api.sf'].search(
                    [], limit=1, order='id desc'
                )
            
            if padron:
                result = padron.action_update_partner_alicuot(partner)
                if isinstance(result, dict):
                    messages.append(_('Partner %s: %s') % (partner.name, result.get('message', 'Procesado')))
                else:
                    messages.append(_('Partner %s: Procesado') % partner.name)
            else:
                messages.append(_('Partner %s: No hay padrón PARP de Santa Fe cargado') % partner.name)
        
        # Mostrar notificación al usuario
        message = '\n'.join(messages) if messages else _('No se procesó ningún partner')
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Actualización Padrón PARP Santa Fe'),
                'message': message,
                'type': 'success' if any('Alícuotas' in m for m in messages) else 'warning',
                'sticky': False,
            }
        }


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
