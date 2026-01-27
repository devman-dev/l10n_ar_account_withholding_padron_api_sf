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
        
        IMPORTANTE: El formato exacto del archivo PARP será definido por API Santa Fe.
        Esta implementación asume un formato similar al de ARBA/AGIP pero puede
        necesitar ajustes cuando se publique la especificación oficial.
        
        Formato esperado tentativo (basado en prácticas comunes):
        Posición | Campo
        ---------|------
        0        | Número de publicación/lote
        1        | Fecha intermedia (opcional)
        2        | Fecha desde (DDMMAAAA)
        3        | Fecha hasta (DDMMAAAA)
        4        | CUIT (sin guiones)
        5        | Tipo de contribuyente
        6        | Marca alta/baja
        7        | Marca CBU
        8        | Alícuota Percepción (con coma decimal)
        9        | Alícuota Retención (con coma decimal)
        
        Formato alternativo (más simple):
        CUIT;ALICUOTA_RETENCION;ALICUOTA_PERCEPCION;FECHA_DESDE;FECHA_HASTA
        
        Returns:
            dict con los datos parseados o None si hay error
        """
        if not line or ';' not in line:
            return None
            
        try:
            parts = line.split(';')
            
            # Detectar formato del archivo basado en la cantidad de campos
            if len(parts) >= 10:
                # Formato extendido (similar a ARBA/AGIP)
                return self._parse_extended_format(parts)
            elif len(parts) >= 5:
                # Formato simple
                return self._parse_simple_format(parts)
            else:
                return None
                
        except Exception as e:
            _logger.debug(f"API SF: Error parseando línea: {line} - {e}")
            return None

    def _parse_extended_format(self, parts):
        """
        Parsea formato extendido del padrón (similar a ARBA/AGIP)
        """
        try:
            # Índices basados en formato similar a AGIP
            cuit = parts[4] if len(parts) > 4 else parts[0]
            
            # Intentar extraer fechas
            from_date = None
            to_date = None
            
            # Buscar fechas en posiciones comunes
            for i, part in enumerate(parts):
                if len(part) == 8 and part.isdigit():
                    try:
                        parsed_date = datetime.strptime(part, '%d%m%Y').date()
                        if from_date is None:
                            from_date = parsed_date
                        else:
                            to_date = parsed_date
                            break
                    except ValueError:
                        continue
            
            # Usar fechas del padrón si no se encuentran en la línea
            if from_date is None:
                from_date = self.l10n_ar_padron_from_date
            if to_date is None:
                to_date = self.l10n_ar_padron_to_date
            
            # Extraer alícuotas
            alicuota_percepcion = 0.0
            alicuota_retencion = 0.0
            
            # Buscar valores numéricos que parezcan alícuotas
            for i in range(len(parts) - 1, max(4, len(parts) - 4), -1):
                try:
                    value = float(parts[i].replace(',', '.'))
                    if 0 <= value <= 100:  # Rango válido para alícuotas
                        if alicuota_retencion == 0.0:
                            alicuota_retencion = value
                        elif alicuota_percepcion == 0.0:
                            alicuota_percepcion = value
                            break
                except (ValueError, IndexError):
                    continue
            
            return {
                'cuit': cuit,
                'from_date': from_date,
                'to_date': to_date,
                'alicuota_percepcion': alicuota_percepcion,
                'alicuota_retencion': alicuota_retencion,
            }
            
        except Exception as e:
            _logger.debug(f"API SF: Error en formato extendido: {e}")
            return None

    def _parse_simple_format(self, parts):
        """
        Parsea formato simple del padrón
        Formato: CUIT;ALICUOTA_RET;ALICUOTA_PER;FECHA_DESDE;FECHA_HASTA
        """
        try:
            cuit = parts[0]
            alicuota_retencion = float(parts[1].replace(',', '.')) if len(parts) > 1 else 0.0
            alicuota_percepcion = float(parts[2].replace(',', '.')) if len(parts) > 2 else 0.0
            
            from_date = self.l10n_ar_padron_from_date
            to_date = self.l10n_ar_padron_to_date
            
            # Intentar parsear fechas si están presentes
            if len(parts) > 3:
                try:
                    from_date = datetime.strptime(parts[3], '%d%m%Y').date()
                except ValueError:
                    pass
            if len(parts) > 4:
                try:
                    to_date = datetime.strptime(parts[4], '%d%m%Y').date()
                except ValueError:
                    pass
            
            return {
                'cuit': cuit,
                'from_date': from_date,
                'to_date': to_date,
                'alicuota_percepcion': alicuota_percepcion,
                'alicuota_retencion': alicuota_retencion,
            }
            
        except Exception as e:
            _logger.debug(f"API SF: Error en formato simple: {e}")
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
        """
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

    def action_apply_default_to_missing(self):
        """
        Aplica alícuotas por defecto a todos los partners que no están 
        incluidos en el padrón PARP.
        
        Útil para cumplir con la Resolución 37/2025 que indica:
        - 5% retención para no incluidos
        - 6% percepción para no incluidos
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
            
            # Buscar partners no incluidos
            partners_missing = self.env['res.partner'].search([
                ('vat', '!=', False),
                ('vat', 'not in', list(cuits_in_padron)),
            ])
            
            applied_count = 0
            for partner in partners_missing:
                if rec._apply_default_alicuot(partner):
                    applied_count += 1
            
            rec.log_process += f'\n=== ALÍCUOTAS POR DEFECTO ===\n'
            rec.log_process += f'Partners no incluidos en padrón: {len(partners_missing)}\n'
            rec.log_process += f'Alícuotas aplicadas: {applied_count}\n'
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Alícuotas por defecto aplicadas'),
                    'message': _('Se aplicaron alícuotas por defecto a %d partners') % applied_count,
                    'type': 'success',
                    'sticky': False,
                }
            }
