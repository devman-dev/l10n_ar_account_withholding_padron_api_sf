# Padrón API Santa Fe - Retenciones y Percepciones IIBB

## Descripción

Módulo para gestión del **Padrón de Alícuotas de Retención y Percepción (PARP)** de la Provincia de Santa Fe según la **Resolución API SF 37/2025**.

Este módulo permite importar el padrón mensual publicado por API Santa Fe y asignar automáticamente las alícuotas de retención y percepción a los partners de Odoo.

## Resolución API Santa Fe 37/2025

La Resolución 37/2025 introduce modificaciones significativas al régimen de retenciones y percepciones del Impuesto sobre los Ingresos Brutos (RG API Santa Fe 15/1997).

### Principales cambios:

#### 1. Nuevo Padrón Mensual PARP
- **Obligatorio** para todos los agentes de retención y percepción
- Se publica con **5 días hábiles de antelación** a su vigencia
- Contiene las alícuotas individualizadas por CUIT

#### 2. Alícuotas por Defecto
Para sujetos **NO incluidos** en el padrón:
- **Retención:** 5%
- **Percepción:** 6%

#### 3. Montos Mínimos Actualizados

| Concepto | Monto |
|----------|-------|
| Retención General | $650.000 |
| Retención Especial | $180.000 |
| Percepción General | $360.000 |
| Percepción Carnes | $650.000 |

#### 4. Requisitos para ser Agente
- Ingresos superiores a **$3.000.000.000** en Santa Fe
- Ingresos superiores a **$3.500.000.000** a nivel total

#### 5. Redefinición de Habitualidad
- **3 operaciones mensuales** por más de $30.000

#### 6. Procedimientos Digitales
- Inscripción, baja y constancias de exención se gestionan mediante el **Sistema Integral de Administración Tributaria (SIAT)**

## Instalación

1. Copiar el módulo a la carpeta de addons de Odoo
2. Actualizar la lista de módulos
3. Instalar `l10n_ar_account_withholding_padron_api_sf`

### Dependencias
- `l10n_ar_account_withholding`

## Uso

### 1. Cargar un Padrón PARP

1. Ir a **Contabilidad > Configuración > Padrón PARP Santa Fe**
2. Crear nuevo registro
3. Completar:
   - **Descripción:** Nombre del período (ej: "Enero 2026")
   - **Compañía:** Seleccionar la compañía
   - **Jurisdicción:** Seleccionar Santa Fe (código 921)
   - **Archivo:** Subir el archivo TXT o ZIP del padrón
   - **Fecha Desde/Hasta:** Período de vigencia

4. Click en **🚀 Procesar Padrón**

### 2. Aplicar Alícuotas por Defecto

Para partners que no están incluidos en el padrón, se pueden aplicar las alícuotas por defecto (5% ret / 6% per):

1. Una vez procesado el padrón (estado "Completado")
2. Click en **📋 Aplicar Alícuotas por Defecto**

### 3. Actualización Individual

Desde la ficha de cualquier partner con CUIT:
1. Click en el botón **Actualizar PARP SF** en el área de botones
2. Se buscará el CUIT en el último padrón cargado y se actualizará la alícuota

## Formato del Archivo PARP

El módulo soporta dos formatos de archivo:

### Formato Simple
```
CUIT;ALICUOTA_RETENCION;ALICUOTA_PERCEPCION;FECHA_DESDE;FECHA_HASTA
```

### Formato Extendido (similar a ARBA/AGIP)
```
LOTE;FECHA_INT;FECHA_DESDE;FECHA_HASTA;CUIT;TIPO_CONTRIB;MARCA_ALTA;MARCA_CBU;ALICUOTA_PER;ALICUOTA_RET
```

**Nota:** El formato exacto será confirmado cuando API Santa Fe publique las especificaciones oficiales del PARP.

## Configuración

### Alícuotas por Defecto
Se pueden modificar las alícuotas por defecto en cada registro de padrón:
- **Alícuota Retención (no incluidos):** Por defecto 5%
- **Alícuota Percepción (no incluidos):** Por defecto 6%

### Montos Mínimos
Se pueden ajustar los montos mínimos según actualizaciones de la normativa.

## Logs y Diagnóstico

El módulo mantiene logs detallados en cada padrón:
- **Log de Procesamiento:** Progreso y estadísticas
- **No Procesados:** CUITs no encontrados o errores
- **Contenido:** Muestra de líneas procesadas

## Referencias Legales

- [Resolución API SF 37/2025](https://www.cpcesfe2.org.ar/wp-content/uploads/2026/01/37-RES-2025-00000037-APPSF-ODAPI.pdf)
- [Anexo I - Formato PARP](https://www.cpcesfe2.org.ar/wp-content/uploads/2026/01/37-RES-2025-00000037-APPSF-ODAPI-ANEXO-I.pdf)
- [Anexo II](https://www.cpcesfe2.org.ar/wp-content/uploads/2026/01/37-RES-2025-00000037-APPSF-ODAPI-ANEXO-II.pdf)
- [Nota CPCE Santa Fe](https://www.cpcesfe2.org.ar/tecnica/santa-fe-actualiza-el-regimen-de-retenciones-y-percepciones-de-ingresos-brutos/)

## Soporte

Para reportar problemas o solicitar mejoras, contactar al equipo de desarrollo.

## Changelog

### Versión 16.0.1.0.0
- Versión inicial
- Soporte para importación de padrón PARP
- Asignación automática de alícuotas
- Alícuotas por defecto según Res. 37/2025
- Configuración de montos mínimos

## Licencia

LGPL-3
