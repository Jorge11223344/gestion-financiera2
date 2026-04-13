import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.shortcuts import render
from django.utils import timezone
from django.db.models import Sum, Count, Q
import calendar

from .models import MovimientoDiario, CierreDiario, PresupuestoMensual, ConfiguracionEmpresa, CuentaContable, CentroCosto
from .utils import (get_resumen_periodo, get_flujo_mensual, get_ventas_por_dia,
                    get_distribucion_gastos, get_kpis_salud, calcular_iva, get_saldo_actual)


def index(request):
    """Página principal - SPA"""
    config = ConfiguracionEmpresa.get()
    return render(request, 'index.html', {'empresa': config})


# ──────────────────────────────────────────────
# MOVIMIENTOS
# ──────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET", "POST"])
def movimientos(request):
    if request.method == 'GET':
        # Filtros opcionales
        fecha_desde = request.GET.get('desde')
        fecha_hasta = request.GET.get('hasta')
        tipo = request.GET.get('tipo')
        limit = int(request.GET.get('limit', 100))

        qs = MovimientoDiario.objects.all()
        if fecha_desde:
            qs = qs.filter(fecha__gte=fecha_desde)
        if fecha_hasta:
            qs = qs.filter(fecha__lte=fecha_hasta)
        if tipo:
            qs = qs.filter(tipo=tipo)

        qs = qs[:limit]
        data = [{
            'id': str(m.id),
            'fecha': str(m.fecha),
            'tipo': m.tipo,
            'tipo_display': m.get_tipo_display(),
            'descripcion': m.descripcion,
            'monto': int(m.monto),
            'medio_pago': m.medio_pago,
            'medio_pago_display': m.get_medio_pago_display(),
            'cantidad_documentos': m.cantidad_documentos,
            'rut_contraparte': m.rut_contraparte,
            'nombre_contraparte': m.nombre_contraparte,
            'monto_neto': int(m.monto_neto) if m.monto_neto else None,
            'monto_iva': int(m.monto_iva) if m.monto_iva else None,
            'notas': m.notas,
            'es_ingreso': m.es_ingreso,
        } for m in qs]
        return JsonResponse({'movimientos': data, 'total': len(data)})

    elif request.method == 'POST':
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'JSON inválido'}, status=400)

        # Validaciones básicas
        required = ['fecha', 'tipo', 'descripcion', 'monto']
        for field in required:
            if not body.get(field):
                return JsonResponse({'error': f'Campo requerido: {field}'}, status=400)

        try:
            monto = Decimal(str(body['monto']))
            if monto <= 0:
                return JsonResponse({'error': 'El monto debe ser mayor a 0'}, status=400)
        except (InvalidOperation, ValueError):
            return JsonResponse({'error': 'Monto inválido'}, status=400)

        # Calcular IVA automáticamente para facturas
        monto_neto = None
        monto_iva = None
        if body['tipo'] in ['suma_facturas_emitidas', 'suma_facturas_recibidas']:
            iva_info = calcular_iva(monto)
            monto_neto = iva_info['neto']
            monto_iva = iva_info['iva']

        # Sobreescribir si el usuario ingresó neto/iva manualmente
        if body.get('monto_neto'):
            monto_neto = Decimal(str(body['monto_neto']))
        if body.get('monto_iva'):
            monto_iva = Decimal(str(body['monto_iva']))

        m = MovimientoDiario.objects.create(
            fecha=body['fecha'],
            tipo=body['tipo'],
            descripcion=body['descripcion'],
            monto=monto,
            medio_pago=body.get('medio_pago', 'efectivo'),
            cantidad_documentos=body.get('cantidad_documentos'),
            rut_contraparte=body.get('rut_contraparte', ''),
            nombre_contraparte=body.get('nombre_contraparte', ''),
            monto_neto=monto_neto,
            monto_iva=monto_iva,
            notas=body.get('notas', ''),
        )

        return JsonResponse({
            'id': str(m.id),
            'mensaje': 'Movimiento registrado exitosamente',
            'monto_neto': int(monto_neto) if monto_neto else None,
            'monto_iva': int(monto_iva) if monto_iva else None,
        }, status=201)


@csrf_exempt
@require_http_methods(["PUT", "DELETE"])
def movimiento_detalle(request, mov_id):
    try:
        m = MovimientoDiario.objects.get(id=mov_id)
    except MovimientoDiario.DoesNotExist:
        return JsonResponse({'error': 'No encontrado'}, status=404)

    if request.method == 'DELETE':
        m.delete()
        return JsonResponse({'mensaje': 'Eliminado'})

    if request.method == 'PUT':
        body = json.loads(request.body)
        for field in ['fecha', 'tipo', 'descripcion', 'monto', 'medio_pago', 'notas',
                      'cantidad_documentos', 'rut_contraparte', 'nombre_contraparte']:
            if field in body:
                setattr(m, field, body[field])
        m.save()
        return JsonResponse({'mensaje': 'Actualizado'})


# ──────────────────────────────────────────────
# DASHBOARD Y KPIs
# ──────────────────────────────────────────────

def dashboard_data(request):
    """Datos principales para el dashboard."""
    hoy = date.today()

    # Período por defecto: mes actual
    fecha_desde = date(hoy.year, hoy.month, 1)
    fecha_hasta = hoy

    # Parámetros opcionales
    if request.GET.get('desde'):
        fecha_desde = date.fromisoformat(request.GET['desde'])
    if request.GET.get('hasta'):
        fecha_hasta = date.fromisoformat(request.GET['hasta'])

    resumen = get_resumen_periodo(fecha_desde, fecha_hasta)
    kpis = get_kpis_salud(fecha_desde, fecha_hasta)
    flujo = get_flujo_mensual(hoy.year)
    ventas_dia = get_ventas_por_dia(fecha_desde, fecha_hasta)
    dist_gastos = get_distribucion_gastos(fecha_desde, fecha_hasta)
    saldo_actual = get_saldo_actual()

    # Últimos 10 movimientos
    ultimos = MovimientoDiario.objects.all()[:10]
    ultimos_data = [{
        'fecha': str(m.fecha),
        'tipo_display': m.get_tipo_display(),
        'descripcion': m.descripcion,
        'monto': int(m.monto),
        'es_ingreso': m.es_ingreso,
    } for m in ultimos]

    return JsonResponse({
        'resumen': {k: int(v) if isinstance(v, Decimal) else v for k, v in resumen.items()},
        'kpis': kpis,
        'flujo_mensual': flujo,
        'ventas_por_dia': ventas_dia,
        'distribucion_gastos': dist_gastos,
        'saldo_actual': int(saldo_actual),
        'ultimos_movimientos': ultimos_data,
        'periodo': {'desde': str(fecha_desde), 'hasta': str(fecha_hasta)},
    })


def resumen_mensual(request, anio, mes):
    """Resumen detallado de un mes específico."""
    fecha_desde = date(anio, mes, 1)
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    fecha_hasta = date(anio, mes, ultimo_dia)

    resumen = get_resumen_periodo(fecha_desde, fecha_hasta)
    dist_gastos = get_distribucion_gastos(fecha_desde, fecha_hasta)
    ventas_dia = get_ventas_por_dia(fecha_desde, fecha_hasta)

    return JsonResponse({
        'anio': anio,
        'mes': mes,
        'mes_nombre': calendar.month_name[mes],
        'resumen': {k: int(v) if isinstance(v, Decimal) else v for k, v in resumen.items()},
        'distribucion_gastos': dist_gastos,
        'ventas_por_dia': ventas_dia,
    })


# ──────────────────────────────────────────────
# CIERRES DIARIOS
# ──────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET", "POST"])
def cierres(request):
    if request.method == 'GET':
        limit = int(request.GET.get('limit', 30))
        cs = CierreDiario.objects.all()[:limit]
        data = [{
            'fecha': str(c.fecha),
            'saldo_inicial_caja': int(c.saldo_inicial_caja),
            'total_ingresos': int(c.total_ingresos),
            'total_egresos': int(c.total_egresos),
            'saldo_final_caja': int(c.saldo_final_caja),
            'resultado_dia': int(c.resultado_dia),
            'cerrado': c.cerrado,
            'notas': c.notas,
        } for c in cs]
        return JsonResponse({'cierres': data})

    elif request.method == 'POST':
        body = json.loads(request.body)
        fecha_str = body.get('fecha', str(date.today()))
        fecha = date.fromisoformat(fecha_str)

        # Calcular totales del día
        tipos_ingreso = ['ingreso_caja', 'ingreso_banco', 'suma_boletas',
                         'suma_facturas_emitidas', 'prestamo_recibido', 'otro_ingreso']
        movs_dia = MovimientoDiario.objects.filter(fecha=fecha)
        ingresos = movs_dia.filter(tipo__in=tipos_ingreso).aggregate(t=Sum('monto'))['t'] or Decimal('0')
        egresos = movs_dia.exclude(tipo__in=tipos_ingreso).aggregate(t=Sum('monto'))['t'] or Decimal('0')

        # Saldo inicial = saldo final del día anterior
        cierre_anterior = CierreDiario.objects.filter(fecha__lt=fecha).first()
        saldo_inicial = cierre_anterior.saldo_final_caja if cierre_anterior else Decimal('0')

        cierre, created = CierreDiario.objects.update_or_create(
            fecha=fecha,
            defaults={
                'saldo_inicial_caja': saldo_inicial,
                'total_ingresos': ingresos,
                'total_egresos': egresos,
                'saldo_final_caja': saldo_inicial + ingresos - egresos,
                'cerrado': True,
                'cerrado_en': timezone.now(),
                'notas': body.get('notas', ''),
            }
        )

        return JsonResponse({
            'fecha': str(cierre.fecha),
            'saldo_final': int(cierre.saldo_final_caja),
            'resultado': int(cierre.resultado_dia),
            'mensaje': 'Cierre registrado exitosamente',
        }, status=201)


# ──────────────────────────────────────────────
# PRESUPUESTO
# ──────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET", "POST"])
def presupuesto(request):
    if request.method == 'GET':
        anio = int(request.GET.get('anio', date.today().year))
        mes = request.GET.get('mes')
        qs = PresupuestoMensual.objects.filter(anio=anio)
        if mes:
            qs = qs.filter(mes=int(mes))
        data = [{
            'id': p.id,
            'anio': p.anio,
            'mes': p.mes,
            'categoria': p.categoria,
            'categoria_display': p.get_categoria_display(),
            'monto_presupuestado': int(p.monto_presupuestado),
        } for p in qs]
        return JsonResponse({'presupuestos': data})

    elif request.method == 'POST':
        body = json.loads(request.body)
        p, created = PresupuestoMensual.objects.update_or_create(
            anio=body['anio'],
            mes=body['mes'],
            categoria=body['categoria'],
            defaults={'monto_presupuestado': Decimal(str(body['monto_presupuestado']))}
        )
        return JsonResponse({'id': p.id, 'mensaje': 'Guardado'}, status=201)


# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET", "POST"])
def configuracion(request):
    config = ConfiguracionEmpresa.get()
    if request.method == 'GET':
        return JsonResponse({
            'nombre': config.nombre,
            'rut': config.rut,
            'giro': config.giro,
            'direccion': config.direccion,
            'telefono': config.telefono,
            'email': config.email,
            'moneda': config.moneda,
            'saldo_inicial_caja': int(config.saldo_inicial_caja),
            'saldo_inicial_banco': int(config.saldo_inicial_banco),
            'fecha_inicio_operaciones': str(config.fecha_inicio_operaciones) if config.fecha_inicio_operaciones else None,
        })
    elif request.method == 'POST':
        body = json.loads(request.body)
        for field in ['nombre', 'rut', 'giro', 'direccion', 'telefono', 'email',
                      'saldo_inicial_caja', 'saldo_inicial_banco', 'fecha_inicio_operaciones']:
            if field in body:
                setattr(config, field, body[field])
        config.save()
        return JsonResponse({'mensaje': 'Configuración guardada'})


# ──────────────────────────────────────────────
# CATÁLOGOS
# ──────────────────────────────────────────────

def tipos_movimiento(request):
    """Devuelve los tipos de movimiento disponibles."""
    tipos = [{'value': k, 'label': v} for k, v in MovimientoDiario.TIPOS]
    medios = [{'value': k, 'label': v} for k, v in MovimientoDiario.MEDIOS_PAGO]
    return JsonResponse({'tipos': tipos, 'medios_pago': medios})


def calcular_iva_view(request):
    """Endpoint para calcular IVA desde el frontend."""
    monto = request.GET.get('monto', 0)
    try:
        resultado = calcular_iva(Decimal(str(monto)))
        return JsonResponse({k: int(v) for k, v in resultado.items()})
    except Exception:
        return JsonResponse({'error': 'Monto inválido'}, status=400)
