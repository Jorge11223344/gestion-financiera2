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
    path('api/resumen/<int:anio>/<int:mes>', views.resumen_mensual, name='resumen_mensual'),

    # Cierres diarios
    path('api/cierres', views.cierres, name='cierres'),

    # Presupuesto
    path('api/presupuesto', views.presupuesto, name='presupuesto'),

    # Configuración empresa
    path('api/configuracion', views.configuracion, name='configuracion'),

    # Catálogos
    path('api/tipos', views.tipos_movimiento, name='tipos'),
    path('api/calcular-iva', views.calcular_iva_view, name='calcular_iva'),

    # Importación cartola bancaria
    path('api/banco/preview', views_banco.preview_cartola, name='banco_preview'),
    path('api/banco/confirmar', views_banco.confirmar_importacion, name='banco_confirmar'),

    # Asistente contable de balance
    path('api/asistente/balance', views_asistente.asistente_balance, name='asistente_balance'),
    path('api/asistente/cuentas', views_asistente.cuentas_balance, name='cuentas_balance'),
    path('api/asistente/estado', views_asistente.estado_api, name='asistente_estado'),
]
