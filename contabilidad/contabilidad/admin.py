"""
Admin de Django para FinanzasPRO.
Permite gestionar todos los modelos desde /admin/.
"""
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    CuentaContable, CentroCosto, CuentaFinanciera,
    RegistroImportacion, MovimientoDiario,
    CierreDiario, PresupuestoMensual, ConfiguracionEmpresa
)


# ──────────────────────────────────────────────
# Cuentas Contables
# ──────────────────────────────────────────────

@admin.register(CuentaContable)
class CuentaContableAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'nombre', 'tipo', 'activa']
    list_filter = ['tipo', 'activa']
    search_fields = ['codigo', 'nombre']
    ordering = ['codigo']


@admin.register(CentroCosto)
class CentroCostoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'activo']
    list_filter = ['activo']


# ──────────────────────────────────────────────
# Cuentas Financieras
# ──────────────────────────────────────────────

@admin.register(CuentaFinanciera)
class CuentaFinancieraAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'institucion', 'moneda', 'tipo_cuenta', 'titular', 'activa']
    list_filter = ['moneda', 'tipo_cuenta', 'activa', 'institucion']
    search_fields = ['nombre', 'institucion', 'titular']
    readonly_fields = ['id', 'creado_en']
    fieldsets = (
        ('Identificación', {
            'fields': ('id', 'nombre', 'institucion', 'tipo_cuenta', 'moneda')
        }),
        ('Titular y número', {
            'fields': ('titular', 'numero_parcial', 'activa')
        }),
        ('Saldo inicial', {
            'fields': ('saldo_inicial', 'fecha_saldo_inicial')
        }),
        ('Notas', {
            'fields': ('notas', 'creado_en')
        }),
    )


# ──────────────────────────────────────────────
# Registro de Importaciones
# ──────────────────────────────────────────────

@admin.register(RegistroImportacion)
class RegistroImportacionAdmin(admin.ModelAdmin):
    list_display = [
        'nombre_archivo', 'cuenta_financiera', 'banco_detectado',
        'fecha_importacion', 'total_importados', 'total_duplicados', 'estado'
    ]
    list_filter = ['estado', 'banco_detectado', 'cuenta_financiera']
    search_fields = ['nombre_archivo', 'banco_detectado']
    readonly_fields = ['id', 'hash_archivo', 'fecha_importacion']
    ordering = ['-fecha_importacion']

    def has_add_permission(self, request):
        return False  # Solo se crean automáticamente al importar


# ──────────────────────────────────────────────
# Movimientos Diarios
# ──────────────────────────────────────────────

@admin.register(MovimientoDiario)
class MovimientoDiarioAdmin(admin.ModelAdmin):
    list_display = [
        'fecha', 'descripcion_corta', 'tipo_display_badge',
        'categoria_badge', 'monto_display', 'moneda',
        'cuenta_financiera', 'es_transferencia_interna'
    ]
    list_filter = [
        'tipo', 'categoria_normalizada', 'moneda',
        'es_transferencia_interna', 'cuenta_financiera',
        'clasificacion_confianza', 'fecha'
    ]
    search_fields = ['descripcion', 'tercero', 'referencia_externa', 'notas']
    readonly_fields = [
        'id', 'creado_en', 'actualizado_en',
        'clasificacion_razon', 'clasificacion_confianza'
    ]
    date_hierarchy = 'fecha'
    ordering = ['-fecha', '-creado_en']

    fieldsets = (
        ('Movimiento', {
            'fields': ('id', 'fecha', 'tipo', 'descripcion', 'monto', 'medio_pago')
        }),
        ('Clasificación', {
            'fields': ('categoria_normalizada', 'tercero', 'pais_tercero',
                       'clasificacion_confianza', 'clasificacion_razon')
        }),
        ('Moneda y cuenta', {
            'fields': ('moneda', 'monto_moneda_orig', 'tipo_cambio', 'cuenta_financiera')
        }),
        ('Transferencias internas', {
            'fields': ('es_transferencia_interna', 'movimiento_relacionado'),
            'classes': ('collapse',)
        }),
        ('Trazabilidad', {
            'fields': ('importacion', 'referencia_externa', 'notas', 'creado_en', 'actualizado_en'),
            'classes': ('collapse',)
        }),
        ('Documentos (boletas/facturas)', {
            'fields': ('cantidad_documentos', 'rut_contraparte', 'nombre_contraparte',
                       'monto_neto', 'monto_iva'),
            'classes': ('collapse',)
        }),
    )

    def descripcion_corta(self, obj):
        return obj.descripcion[:60] + '…' if len(obj.descripcion) > 60 else obj.descripcion
    descripcion_corta.short_description = 'Descripción'

    def tipo_display_badge(self, obj):
        return obj.get_tipo_display()
    tipo_display_badge.short_description = 'Tipo'

    def categoria_badge(self, obj):
        colores = {
            'venta': 'green', 'aporte_socio': 'blue', 'interes_ganado': 'green',
            'pago_importacion': 'red', 'gasto_logistica': 'orange',
            'remuneracion_norm': 'red', 'comision_bancaria': 'orange',
            'pago_impuesto': 'red', 'transferencia_interna': 'gray',
            'conversion_divisa': 'gray', 'sin_clasificar': 'darkorange',
        }
        cat = obj.categoria_normalizada or 'sin_clasificar'
        color = colores.get(cat, 'black')
        label = dict(MovimientoDiario.CATEGORIAS_NORM).get(cat, cat)
        return format_html(
            '<span style="color:{};font-weight:600;">{}</span>',
            color, label
        )
    categoria_badge.short_description = 'Categoría'

    def monto_display(self, obj):
        color = 'green' if obj.es_ingreso and not obj.es_transferencia_interna else \
                'gray' if obj.es_transferencia_interna else 'red'
        signo = '+' if obj.es_ingreso and not obj.es_transferencia_interna else \
                '↔' if obj.es_transferencia_interna else '-'
        return format_html(
            '<span style="color:{};font-weight:600;">{} ${:,.0f}</span>',
            color, signo, obj.monto
        )
    monto_display.short_description = 'Monto'

    actions = ['marcar_como_interna', 'marcar_como_sin_clasificar', 'reclasificar_automatico']

    def marcar_como_interna(self, request, queryset):
        n = queryset.update(
            es_transferencia_interna=True,
            categoria_normalizada='transferencia_interna'
        )
        self.message_user(request, f'{n} movimientos marcados como transferencia interna.')
    marcar_como_interna.short_description = '🔄 Marcar como transferencia interna'

    def marcar_como_sin_clasificar(self, request, queryset):
        n = queryset.update(categoria_normalizada='sin_clasificar', clasificacion_razon='')
        self.message_user(request, f'{n} movimientos marcados como sin clasificar para reclasificar.')
    marcar_como_sin_clasificar.short_description = '❓ Resetear clasificación'

    def reclasificar_automatico(self, request, queryset):
        from .services.clasificador import clasificar_movimiento
        n = 0
        for mov in queryset:
            resultado = clasificar_movimiento(
                descripcion=mov.descripcion,
                tipo_banco='',
                es_cargo=mov.es_egreso,
                moneda=mov.moneda,
            )
            mov.categoria_normalizada = resultado['categoria_normalizada']
            mov.es_transferencia_interna = resultado['es_transferencia_interna']
            mov.clasificacion_confianza = resultado['confianza']
            mov.clasificacion_razon = resultado['razon']
            mov.save(update_fields=[
                'categoria_normalizada', 'es_transferencia_interna',
                'clasificacion_confianza', 'clasificacion_razon'
            ])
            n += 1
        self.message_user(request, f'{n} movimientos reclasificados automáticamente.')
    reclasificar_automatico.short_description = '🤖 Reclasificar automáticamente'


# ──────────────────────────────────────────────
# Cierre Diario
# ──────────────────────────────────────────────

@admin.register(CierreDiario)
class CierreDiarioAdmin(admin.ModelAdmin):
    list_display = ['fecha', 'saldo_inicial_caja', 'total_ingresos',
                    'total_egresos', 'resultado_dia_display', 'saldo_final_caja']
    ordering = ['-fecha']
    readonly_fields = ['cerrado_en']

    def resultado_dia_display(self, obj):
        r = obj.resultado_dia
        color = 'green' if r >= 0 else 'red'
        return format_html('<span style="color:{};font-weight:600;">${:,.0f}</span>', color, r)
    resultado_dia_display.short_description = 'Resultado'


# ──────────────────────────────────────────────
# Presupuesto
# ──────────────────────────────────────────────

@admin.register(PresupuestoMensual)
class PresupuestoMensualAdmin(admin.ModelAdmin):
    list_display = ['anio', 'mes', 'categoria', 'monto_presupuestado']
    list_filter = ['anio', 'mes', 'categoria']
    ordering = ['-anio', '-mes']


# ──────────────────────────────────────────────
# Configuración Empresa
# ──────────────────────────────────────────────

@admin.register(ConfiguracionEmpresa)
class ConfiguracionEmpresaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'rut', 'moneda', 'actualizado_en']

    def has_add_permission(self, request):
        return not ConfiguracionEmpresa.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False