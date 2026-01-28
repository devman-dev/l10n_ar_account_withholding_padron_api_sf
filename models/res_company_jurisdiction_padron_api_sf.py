# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, api, fields, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime
from dateutil.relativedelta import relativedelta
import base64
import tempfile
import zipfile
import os
import shutil
import logging
import csv
from io import StringIO

_logger = logging.getLogger(__name__)


class ResCompanyJurisdictionPadronApiSf(models.Model):
    """
    Modelo para gestionar el Padrón de Alícuotas de Retención y Percepción (PARP)
    de la Provincia de Santa Fe según Resolución API SF 37/2025.
    
    El padrón PARP es obligatorio para los agentes de retención y percepción
    y se publica mensualmente con 5 días hábiles de antelación a su vigencia.
    
    Características según Resolución 37/2025:
    - Alícuotas especiales para operaciones específicas
    - 5% para sujetos no incluidos en el padrón (retenciones)
    - 6% para sujetos no incluidos en el padrón (percepciones)
    - Montos mínimos actualizados
    """
    _name = 'res.company.jurisdiction.padron.api.sf'
    _description = 'Padrón PARP Santa Fe - Retenciones y Percepciones IIBB'
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Descripción',
        required=True,
        help='Descripción del período del padrón (ej: Enero 2026)',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company,
    )
    jurisdiction_id = fields.Many2one(
        'account.account.tag',
        string='Jurisdicción',
        domain="[('applicability', '=', 'taxes'), ('jurisdiction_code', '!=', False)]",
        required=True,
        help='Jurisdicción de Santa Fe (código 921)',
    )
    file_padron = fields.Binary(
        string='Archivo Padrón PARP',
        required=True,
        help='Archivo del padrón PARP de Santa Fe (formato TXT o ZIP)',
    )
    file_padron_name = fields.Char(
        string='Nombre del archivo',
    )
    l10n_ar_padron_from_date = fields.Date(
        string='Fecha Desde',
        required=True,
        help='Fecha de inicio de vigencia del padrón',
    )
    l10n_ar_padron_to_date = fields.Date(
        string='Fecha Hasta',
        required=True,
        help='Fecha de fin de vigencia del padrón',
    )
    
    # Configuración de alícuotas por defecto según Resolución 37/2025
    alicuota_retencion_default = fields.Float(
        string='Alícuota Retención (no incluidos)',
        default=5.0,
        help='Alícuota de retención para sujetos NO incluidos en el padrón (5% según Res. 37/2025)',
    )
    alicuota_percepcion_default = fields.Float(
        string='Alícuota Percepción (no incluidos)',
        default=6.0,
        help='Alícuota de percepción para sujetos NO incluidos en el padrón (6% según Res. 37/2025)',
    )
    
    # Montos mínimos según Resolución 37/2025
    monto_minimo_retencion_general = fields.Float(
        string='Monto Mínimo Retención (General)',
        default=650000.0,
        help='Monto mínimo para aplicar retención en operaciones generales ($650.000)',
    )
    monto_minimo_retencion_especial = fields.Float(
        string='Monto Mínimo Retención (Especial)',
        default=180000.0,
        help='Monto mínimo para aplicar retención en casos especiales ($180.000)',
    )
    monto_minimo_percepcion_general = fields.Float(
        string='Monto Mínimo Percepción (General)',
        default=360000.0,
        help='Monto mínimo para aplicar percepción en operaciones generales ($360.000)',
    )
    monto_minimo_percepcion_carnes = fields.Float(
        string='Monto Mínimo Percepción (Carnes)',
        default=650000.0,
        help='Monto mínimo para aplicar percepción en operaciones de carnes ($650.000)',
    )
    
    # Logs
    log_content = fields.Text(
        string='Contenido procesado',
        readonly=True,
    )
    log_process = fields.Text(
        string='Log de procesamiento',
        readonly=True,
    )
    log_no_process = fields.Text(
        string='Registros no procesados',
        readonly=True,
    )
    
    # Estado del procesamiento
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('processing', 'Procesando'),
        ('done', 'Completado'),
        ('error', 'Error'),
    ], string='Estado', default='draft', readonly=True)
    
    processed_count = fields.Integer(
        string='Registros procesados',
        readonly=True,
    )
    total_lines = fields.Integer(
        string='Total líneas',
        readonly=True,
    )

    @api.constrains('jurisdiction_id')
    def _check_jurisdiction_id(self):
        """
        Permite cualquier jurisdicción válida.
        Se recomienda usar la jurisdicción de Santa Fe (código 921)
        """
        pass

    def _init_logs(self):
        """Inicializa los campos de log"""
        self.log_content = ''
        self.log_process = f'Iniciando procesamiento: {datetime.now()}\n'
        self.log_no_process = ''
        self.processed_count = 0
        self.total_lines = 0
        self.state = 'processing'

    def _descompress_file(self, file_padron):
        """
        Descomprime el archivo del padrón si es ZIP.
        Retorna el nombre del archivo extraído o el archivo temporal si es TXT.
        
        Optimizado para archivos grandes.
        """
        if not file_padron:
            return ""
            
        ruta_extraccion = '/tmp'
        try:
            # Decodificar archivo base64
            file_data = base64.b64decode(file_padron)
            file_size = len(file_data)
            
            _logger.info(f"API SF: Procesando archivo de {file_size / (1024*1024):.1f} MB")
            
            # Crear archivo temporal
            with tempfile.NamedTemporaryFile(delete=False, suffix='.tmp') as fobj:
                fname = fobj.name
                # Escribir en chunks para archivos grandes
                chunk_size = 8192
                for i in range(0, len(file_data), chunk_size):
                    fobj.write(file_data[i:i + chunk_size])
            
            # Verificar si es ZIP
            try:
                with zipfile.ZipFile(fname, 'r') as zip_file:
                    if zip_file.filelist:
                        first_file = zip_file.filelist[0]
                        
                        if first_file.file_size > 500 * 1024 * 1024:  # 500 MB
                            _logger.warning(f"API SF: Archivo muy grande: {first_file.file_size / (1024*1024):.1f} MB")
                        
                        zip_file.extract(first_file, path=ruta_extraccion)
                        return first_file.filename
                    return ""
            except zipfile.BadZipFile:
                # No es ZIP, es archivo de texto plano
                txt_filename = f"padron_api_sf_{self.id}.txt"
                txt_path = os.path.join(ruta_extraccion, txt_filename)
                shutil.copy2(fname, txt_path)
                return txt_filename
            finally:
                try:
                    os.unlink(fname)
                except:
                    pass
                    
        except MemoryError:
            _logger.error("API SF: Error de memoria al procesar archivo")
            return ""
        except Exception as e:
            _logger.error(f"API SF: Error al descomprimir: {e}")
            return ""

    def _open_file(self):
        """
        Abre y lee el archivo del padrón.
        Retorna lista de líneas del archivo.
        
        Soporta formato TXT y ZIP.
        El formato esperado del padrón PARP es CSV con separador ; (punto y coma)
        
        Estructura esperada del archivo PARP Santa Fe:
        CUIT;TIPO_CONTRIBUYENTE;ALICUOTA_RETENCION;ALICUOTA_PERCEPCION;FECHA_DESDE;FECHA_HASTA;...
        
        Nota: El formato exacto puede variar según la publicación oficial de API Santa Fe.
        Este módulo está preparado para adaptarse cuando se publique el formato definitivo.
        """
        self._init_logs()
        
        try:
            # Intentar decodificar como texto plano primero
            txt_content = base64.b64decode(self.file_padron).decode('utf-8')
            lines = [line.strip() for line in txt_content.split('\n') if line.strip()]
            
            self.total_lines = len(lines)
            _logger.info(f"API SF: Archivo cargado con {len(lines)} líneas")
            
            if len(lines) > 1000000:
                _logger.warning(f"API SF: Archivo muy grande ({len(lines)} líneas)")
                # Para archivos muy grandes, procesar en chunks
                return self._process_large_file_lines(lines)
            
            return lines
            
        except UnicodeDecodeError:
            _logger.info('API SF: Intentando descomprimir archivo ZIP')
            file_name = self._descompress_file(self.file_padron)
            
            if not file_name:
                return []
            
            try:
                file_path = f'/tmp/{file_name}'
                file_size = os.path.getsize(file_path)
                
                if file_size > 100 * 1024 * 1024:  # 100 MB
                    return self._read_large_file(file_path)
                else:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as fp:
                        lines = [line.strip() for line in fp.readlines() if line.strip()]
                        self.total_lines = len(lines)
                        return lines
                        
            except FileNotFoundError:
                _logger.error(f'API SF: Archivo no encontrado: /tmp/{file_name}')
                return []
            except Exception as e:
                _logger.error(f'API SF: Error al leer archivo: {e}')
                return []

    def _process_large_file_lines(self, lines):
        """Procesa archivos con muchas líneas de manera optimizada"""
        chunk_size = 50000
        processed_lines = []
        
        for i in range(0, min(len(lines), 1000000), chunk_size):
            chunk = lines[i:i + chunk_size]
            processed_lines.extend(chunk)
            
        return processed_lines

    def _read_large_file(self, file_path):
        """Lee archivos grandes línea por línea"""
        lines = []
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as fp:
                line_count = 0
                for line in fp:
                    if line.strip():
                        lines.append(line.strip())
                        line_count += 1
                        
                        if line_count > 1000000:
                            _logger.warning("API SF: Límite de líneas alcanzado (1M)")
                            break
                        
                        if line_count % 100000 == 0:
                            _logger.info(f"API SF: Procesadas {line_count} líneas...")
                            
            self.total_lines = len(lines)
            return lines
        except Exception as e:
            _logger.error(f"API SF: Error leyendo archivo grande: {e}")
            return []

    def _parse_line(self, line):
        """
        Parsea una línea del padrón PARP de Santa Fe.
        
        Formato oficial del padrón PARP Santa Fe (separado por espacios):
        Posición | Campo                    | Ejemplo
        ---------|--------------------------|------------------
        0        | Fecha publicación        | 23122025 (DDMMAAAA)
        1        | Fecha desde              | 01012026 (DDMMAAAA)
        2        | Fecha hasta              | 31012026 (DDMMAAAA)
        3        | CUIT                     | 30111111118
        4        | Tipo contribuyente       | C (Común) / D (?)
        5        | Marca 1                  | S / N
        6        | Marca 2                  | S / N
        7        | Alícuota Percepción      | 3,50
        8        | Alícuota Retención       | 2,00
        9        | Código 1                 | 00
        10       | Código 2                 | 00
        11+      | Razón Social             | EMPRESA S.A.
        
        Returns:
            dict con los datos parseados o None si hay error
        """
        if not line:
            return None
            
        try:
            # El formato de Santa Fe usa espacios como separador
            # Dividir por espacios múltiples
            parts = line.split()
            
            # Necesitamos al menos 9 campos (hasta alícuota retención)
            if len(parts) < 9:
                _logger.debug(f"API SF: Línea con pocos campos ({len(parts)}): {line[:50]}...")
                return None
            
            # Parsear según el formato oficial de Santa Fe
            return self._parse_santa_fe_format(parts, line)
                
        except Exception as e:
            _logger.debug(f"API SF: Error parseando línea: {line[:50]}... - {e}")
            return None

    def _parse_santa_fe_format(self, parts, original_line):
        """
        Parsea el formato oficial del padrón PARP de Santa Fe.
        
        Formato: FECHA_PUB FECHA_DESDE FECHA_HASTA CUIT TIPO M1 M2 ALIC_PER ALIC_RET COD1 COD2 RAZON_SOCIAL
        """
        try:
            # Posición 0: Fecha de publicación (ignoramos)
            # Posición 1: Fecha desde
            from_date_str = parts[1]
            # Posición 2: Fecha hasta
            to_date_str = parts[2]
            # Posición 3: CUIT
            cuit = parts[3]
            # Posición 4: Tipo contribuyente (C=Común, D=?)
            # tipo_contribuyente = parts[4]
            # Posición 5-6: Marcas (S/N)
            # Posición 7: Alícuota Percepción
            alicuota_percepcion_str = parts[7]
            # Posición 8: Alícuota Retención
            alicuota_retencion_str = parts[8]
            
            # Parsear fechas
            try:
                from_date = datetime.strptime(from_date_str, '%d%m%Y').date()
            except ValueError:
                from_date = self.l10n_ar_padron_from_date
                
            try:
                to_date = datetime.strptime(to_date_str, '%d%m%Y').date()
            except ValueError:
                to_date = self.l10n_ar_padron_to_date
            
            # Parsear alícuotas (formato con coma decimal)
            try:
                alicuota_percepcion = float(alicuota_percepcion_str.replace(',', '.'))
            except (ValueError, AttributeError):
                alicuota_percepcion = 0.0
                
            try:
                alicuota_retencion = float(alicuota_retencion_str.replace(',', '.'))
            except (ValueError, AttributeError):
                alicuota_retencion = 0.0
            
            # Validar CUIT (debe tener 11 dígitos)
            if not cuit or len(cuit) != 11 or not cuit.isdigit():
                _logger.debug(f"API SF: CUIT inválido: {cuit}")
                return None
            
            return {
                'cuit': cuit,
                'from_date': from_date,
                'to_date': to_date,
                'alicuota_percepcion': alicuota_percepcion,
                'alicuota_retencion': alicuota_retencion,
            }
            
        except Exception as e:
            _logger.debug(f"API SF: Error en formato Santa Fe: {e}")
            return None

    def action_process_padron(self):
        """
        Acción principal para procesar el padrón PARP de Santa Fe.
        Solo procesa CUITs que ya existen como partners en Odoo.
        """
        for rec in self:
            if not rec.file_padron:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Error'),
                        'message': _('No se ha cargado el archivo del padrón'),
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            
            try:
                rec._process_padron_optimized()
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Procesamiento completado'),
                        'message': _('El padrón PARP de Santa Fe ha sido procesado correctamente. '
                                   'Revise los logs para más detalles.'),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            except Exception as e:
                _logger.error(f"API SF: Error procesando padrón: {str(e)}")
                rec.state = 'error'
                rec.log_no_process += f'\nError general: {str(e)}'
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Error en procesamiento'),
                        'message': str(e),
                        'type': 'danger',
                        'sticky': True,
                    }
                }

    def _process_padron_optimized(self):
        """
        Procesamiento optimizado del padrón PARP de Santa Fe.
        
        Características:
        - Pre-carga CUITs en memoria para búsquedas O(1)
        - Procesamiento en chunks con commits frecuentes
        - Logging detallado de progreso
        """
        lines = self._open_file()
        
        if not lines:
            raise UserError(_('No se pudieron leer líneas del archivo del padrón'))
        
        self.log_process += f'Total de líneas en archivo: {len(lines)}\n'
        
        # Pre-cargar todos los CUITs de partners existentes
        _logger.info("API SF: Cargando CUITs existentes en memoria...")
        all_partners = self.env['res.partner'].search([('vat', '!=', False)])
        cuit_to_partner_id = {p.vat: p.id for p in all_partners}
        _logger.info(f"API SF: {len(cuit_to_partner_id)} CUITs cargados")
        
        self.log_process += f'Partners con CUIT en sistema: {len(cuit_to_partner_id)}\n'
        
        # Pre-procesar líneas
        valid_data = []
        skipped_lines = 0
        
        for line in lines:
            parsed = self._parse_line(line)
            if parsed and parsed['cuit'] in cuit_to_partner_id:
                parsed['partner_id'] = cuit_to_partner_id[parsed['cuit']]
                valid_data.append(parsed)
            else:
                skipped_lines += 1
        
        total_valid = len(valid_data)
        self.log_process += f'Registros con partners existentes: {total_valid}\n'
        self.log_process += f'Registros sin partner (omitidos): {skipped_lines}\n'
        
        # Procesar en chunks
        chunk_size = 500
        processed = 0
        
        for i in range(0, total_valid, chunk_size):
            chunk = valid_data[i:i + chunk_size]
            processed_in_chunk = self._process_chunk(chunk)
            processed += processed_in_chunk
            
            # Commit intermedio
            self.env.cr.commit()
            
            # Log de progreso cada 10 chunks
            if (i // chunk_size) % 10 == 0:
                percentage = (processed / total_valid) * 100 if total_valid > 0 else 100
                _logger.info(f"API SF: Progreso {percentage:.1f}% ({processed}/{total_valid})")
        
        # Finalizar
        self.processed_count = processed
        self.state = 'done'
        self.log_process += f'\n=== RESUMEN FINAL ===\n'
        self.log_process += f'Total líneas archivo: {len(lines)}\n'
        self.log_process += f'Registros procesados: {processed}\n'
        self.log_process += f'Registros omitidos (sin partner): {skipped_lines}\n'
        self.log_process += f'Tasa de éxito: {(processed/len(lines))*100:.2f}%\n'
        self.log_process += f'Procesamiento finalizado: {datetime.now()}\n'

    def _process_chunk(self, chunk):
        """Procesa un chunk de datos del padrón"""
        processed = 0
        
        for data in chunk:
            try:
                partner_id = data['partner_id']
                
                # Buscar alícuota existente
                existing = self.env['res.partner.arba_alicuot'].search([
                    ('partner_id', '=', partner_id),
                    ('tag_id', '=', self.jurisdiction_id.id),
                    ('company_id', '=', self.company_id.id),
                ], limit=1)
                
                vals = {
                    'alicuota_retencion': data['alicuota_retencion'],
                    'alicuota_percepcion': data['alicuota_percepcion'],
                    'from_date': data['from_date'],
                    'to_date': data['to_date'],
                    'date_last_update': datetime.now(),
                }
                
                if existing:
                    # Actualizar existente
                    existing.sudo().write(vals)
                else:
                    # Crear nuevo
                    vals.update({
                        'partner_id': partner_id,
                        'tag_id': self.jurisdiction_id.id,
                        'company_id': self.company_id.id,
                        'withholding_amount_type': 'untaxed_amount',
                    })
                    self.env['res.partner.arba_alicuot'].sudo().create(vals)
                
                processed += 1
                
            except Exception as e:
                self.log_no_process += f"Error procesando CUIT {data.get('cuit', 'unknown')}: {e}\n"
                continue
        
        return processed

    def action_update_partner_alicuot(self, partner):
        """
        Actualiza la alícuota de un partner específico desde el padrón.
        
        Args:
            partner: res.partner record
            
        Returns:
            True si se actualizó, False si no se encontró en el padrón
        """
        if not partner.vat:
            return False
            
        lines = self._open_file()
        
        for line in lines:
            parsed = self._parse_line(line)
            if parsed and parsed['cuit'] == partner.vat:
                # Encontrado en el padrón
                existing = self.env['res.partner.arba_alicuot'].search([
                    ('partner_id', '=', partner.id),
                    ('tag_id', '=', self.jurisdiction_id.id),
                    ('company_id', '=', self.company_id.id),
                ], limit=1)
                
                vals = {
                    'alicuota_retencion': parsed['alicuota_retencion'],
                    'alicuota_percepcion': parsed['alicuota_percepcion'],
                    'from_date': parsed['from_date'],
                    'to_date': parsed['to_date'],
                    'date_last_update': datetime.now(),
                }
                
                if existing:
                    existing.sudo().write(vals)
                else:
                    vals.update({
                        'partner_id': partner.id,
                        'tag_id': self.jurisdiction_id.id,
                        'company_id': self.company_id.id,
                        'withholding_amount_type': 'untaxed_amount',
                    })
                    self.env['res.partner.arba_alicuot'].sudo().create(vals)
                
                return True
        
        # No encontrado en el padrón - aplicar alícuota por defecto
        return self._apply_default_alicuot(partner)

    def _apply_default_alicuot(self, partner):
        """
        Aplica alícuota por defecto para sujetos no incluidos en el padrón.
        
        Según Resolución 37/2025:
        - Retención: 5%
        - Percepción: 6%
        - EXENTOS: No se les aplica (retorna False)
        """
        # Verificar si el partner está exento de IIBB
        if partner.l10n_ar_gross_income_type == 'exempt':
            _logger.info(f"API SF: Partner {partner.vat} es EXENTO de IIBB - no se aplica alícuota")
            return False
        
        existing = self.env['res.partner.arba_alicuot'].search([
            ('partner_id', '=', partner.id),
            ('tag_id', '=', self.jurisdiction_id.id),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        
        vals = {
            'alicuota_retencion': self.alicuota_retencion_default,
            'alicuota_percepcion': self.alicuota_percepcion_default,
            'from_date': self.l10n_ar_padron_from_date,
            'to_date': self.l10n_ar_padron_to_date,
            'date_last_update': datetime.now(),
        }
        
        if existing:
            existing.sudo().write(vals)
        else:
            vals.update({
                'partner_id': partner.id,
                'tag_id': self.jurisdiction_id.id,
                'company_id': self.company_id.id,
                'withholding_amount_type': 'untaxed_amount',
            })
            self.env['res.partner.arba_alicuot'].sudo().create(vals)
        
        return True

    def action_view_processed_partners(self):
        """
        Abre una vista con los partners que tienen alícuotas asignadas
        para la jurisdicción de Santa Fe.
        """
        self.ensure_one()
        
        # Buscar partners con alícuotas para esta jurisdicción
        alicuotas = self.env['res.partner.arba_alicuot'].search([
            ('tag_id', '=', self.jurisdiction_id.id),
            ('company_id', '=', self.company_id.id),
        ])
        
        partner_ids = alicuotas.mapped('partner_id').ids
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Partners con Alícuotas Santa Fe'),
            'res_model': 'res.partner',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', partner_ids)],
            'context': {'search_default_customer': 0, 'search_default_supplier': 0},
        }

    def action_apply_default_to_missing(self):
        """
        Aplica alícuotas por defecto a los partners de SANTA FE que no están 
        incluidos en el padrón PARP.
        
        Solo aplica a partners que:
        - Tienen domicilio en la provincia de Santa Fe (state_id)
        - NO están exentos de Ingresos Brutos (l10n_ar_gross_income_type != 'exempt')
        - Son Local o Multilateral en IIBB
        
        Según Resolución 37/2025:
        - 5% retención para no incluidos
        - 6% percepción para no incluidos
        - EXENTOS: No se les aplica retención/percepción
        """
        for rec in self:
            if not rec.file_padron:
                raise UserError(_('Debe cargar primero el archivo del padrón'))
            
            lines = rec._open_file()
            
            # Obtener CUITs del padrón
            cuits_in_padron = set()
            for line in lines:
                parsed = rec._parse_line(line)
                if parsed:
                    cuits_in_padron.add(parsed['cuit'])
            
            # Buscar la provincia de Santa Fe
            santa_fe_state = self.env['res.country.state'].search([
                ('name', 'ilike', 'Santa Fe'),
                ('country_id.code', '=', 'AR'),
            ], limit=1)
            
            if not santa_fe_state:
                raise UserError(_('No se encontró la provincia de Santa Fe en el sistema'))
            
            # Buscar partners de Santa Fe no incluidos en el padrón
            # EXCLUIR EXENTOS - solo aplicar a 'local' o 'multilateral'
            domain = [
                ('vat', '!=', False),
                ('vat', 'not in', list(cuits_in_padron)),
                # Excluir exentos de IIBB
                ('l10n_ar_gross_income_type', 'in', ['local', 'multilateral']),
                '|',
                ('state_id', '=', santa_fe_state.id),
                ('state_id.name', 'ilike', 'Santa Fe'),
            ]
            
            partners_missing = self.env['res.partner'].search(domain)
            
            # Contar exentos para el log
            exentos_count = self.env['res.partner'].search_count([
                ('vat', '!=', False),
                ('vat', 'not in', list(cuits_in_padron)),
                ('l10n_ar_gross_income_type', '=', 'exempt'),
                '|',
                ('state_id', '=', santa_fe_state.id),
                ('state_id.name', 'ilike', 'Santa Fe'),
            ])
            
            applied_count = 0
            for partner in partners_missing:
                if rec._apply_default_alicuot(partner):
                    applied_count += 1
            
            rec.log_process += f'\n=== ALÍCUOTAS POR DEFECTO (SOLO SANTA FE) ===\n'
            rec.log_process += f'Partners de Santa Fe no incluidos en padrón: {len(partners_missing)}\n'
            rec.log_process += f'Partners EXENTOS (omitidos): {exentos_count}\n'
            rec.log_process += f'Alícuotas aplicadas (Local/Multilateral): {applied_count}\n'
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Alícuotas por defecto aplicadas'),
                    'message': _('Se aplicaron alícuotas a %d partners de Santa Fe. %d exentos omitidos.') % (applied_count, exentos_count),
                    'type': 'success',
                    'sticky': False,
                }
            }
