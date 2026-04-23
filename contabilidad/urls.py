from django.urls import path
from . import views
from . import views_banco
from . import views_asistente

urlpatterns = [
    # Frontend SPA
    path('', views.index, name='index'),

    # Movimientos diarios
    path('api/movimientos', views.movimientos, name='movimientos'),
    path('api/movimientos/<str:mov_id>', views.movimiento_detalle, name='movimiento_detalle'),

    # Dashboard y análisis
    path('api/dashboard', views.dashboard_data, name='dashboard'),
    path('api/dashboard/cuentas/<str:cuenta_id>', views.dashboard_cuenta_detalle, name='dashboard_cuenta_detalle'),
    path('api/resumen/<int:anio>/<int:mes>', views.resumen_mensual, name='resumen_mensual'),

    # Cierres diarios
    path('api/cierres', views.cierres, name='cierres'),

    # Presupuesto
    path('api/presupuesto', views.presupuesto, name='presupuesto'),

    # Configuración empresa
    path('api/configuracion', views.configuracion, name='configuracion'),

    # Control de saldos reales
    path('api/control-saldos', views.control_saldos, name='control_saldos'),
    path('api/control-saldos/<int:control_id>', views.control_saldos_detalle, name='control_saldos_detalle'),

    # Catálogos
    path('api/tipos', views.tipos_movimiento, name='tipos'),
    path('api/calcular-iva', views.calcular_iva_view, name='calcular_iva'),

    # Cuentas financieras
    path('api/cuentas-financieras', views_banco.cuentas_financieras, name='cuentas_financieras'),
    path('api/cuentas-financieras/<str:cuenta_id>', views_banco.cuenta_financiera_detalle, name='cuenta_financiera_detalle'),

    # Importación cartola bancaria
    path('api/banco/preview', views_banco.preview_cartola, name='banco_preview'),
    path('api/banco/confirmar', views_banco.confirmar_importacion, name='banco_confirmar'),
    path('api/banco/importaciones', views_banco.historial_importaciones, name='banco_importaciones'),
    path('api/banco/importaciones/<str:importacion_id>', views_banco.importacion_detalle, name='banco_importacion_detalle'),
    path('api/banco/revertir/<str:importacion_id>', views_banco.revertir_importacion, name='banco_revertir'),

    # Tipo de cambio
    path('api/tipo-cambio', views_banco.tipo_cambio, name='tipo_cambio'),

    # Revisión manual
    path('api/revision/pendientes', views_banco.revision_pendientes, name='revision_pendientes'),
    path('api/movimientos/<str:mov_id>/clasificar', views_banco.clasificar_movimiento_view, name='clasificar_movimiento'),

    # Asistente contable
    path('api/asistente/balance', views_asistente.asistente_balance, name='asistente_balance'),
    path('api/asistente/cuentas', views_asistente.cuentas_balance, name='cuentas_balance'),
    path('api/asistente/estado', views_asistente.estado_api, name='asistente_estado'),
]