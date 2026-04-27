import json
from datetime import date
from decimal import Decimal, InvalidOperation
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.shortcuts import render
from django.utils import timezone
from django.db.models import Sum, Q
import calendar

from .models import (MovimientoDiario, CierreDiario, PresupuestoMensual,
                     ConfiguracionEmpresa, CuentaContable, CentroCosto,
                     CuentaFinanciera, ControlSaldoReal, ControlSaldoRealDetalle)
from .utils import (get_resumen_periodo, get_flujo_mensual, get_flujo_mensual_periodo, get_ventas_por_dia,
                    get_distribucion_gastos, get_kpis_salud, calcular_iva,
                    get_saldo_actual, get_saldo_por_cuenta, get_detalle_saldos_cuentas,
                    get_detalle_saldo_cuenta_paginado)


def index(request):
    config = ConfiguracionEmpresa.get()
    return render(request, 'index.html', {'empresa': config})


# ──────────────────────────────────────────────
# MOVIMIENTOS
# ──────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET", "POST"])
def movimientos(request):
    if request.method == 'GET':
        fecha_desde = request.GET.get('desde')
        fecha_hasta = request.GET.get('hasta')
        tipo        = request.GET.get('tipo')
        categoria   = request.GET.get('categoria')
        cuenta_id   = request.GET.get('cuenta_financiera')
        solo_intern = request.GET.get('internos')
        limit       = int(request.GET.get('limit', 100))

        qs = MovimientoDiario.objects.select_related('cuenta_financiera')
        if fecha_desde:
            qs = qs.filter(fecha__gte=fecha_desde)
        if fecha_hasta:
            qs = qs.filter(fecha__lte=fecha_hasta)
        if tipo:
            qs = qs.filter(tipo=tipo)
        if categoria:
            qs = qs.filter(categoria_normalizada=categoria)
        if cuenta_id:
            qs = qs.filter(cuenta_financiera_id=cuenta_id)
        if solo_intern == '1':
            qs = qs.filter(es_transferencia_interna=True)
        elif solo_intern == '0':
            qs = qs.filter(es_transferencia_interna=False)

        qs = qs[:limit]

        _cat_map = dict(MovimientoDiario.CATEGORIAS_NORM)
        data = [{
            'id':                    str(m.id),
            'fecha':                 str(m.fecha),
            'tipo':                  m.tipo,
            'tipo_display':          m.get_tipo_display(),
            'descripcion':           m.descripcion,
            # monto es siempre monto_base_clp
            'monto':                 float(m.monto),
            'moneda':                m.moneda,
            # monto en moneda original (para mostrar "USD 1.234" al lado)
            'monto_moneda_orig':     float(m.monto_moneda_orig) if m.monto_moneda_orig else None,
            'tipo_cambio':           float(m.tipo_cambio) if m.tipo_cambio else None,
            'medio_pago':            m.medio_pago,
            'medio_pago_display':    m.get_medio_pago_display(),
            'categoria_normalizada': m.categoria_normalizada,
            'categoria_display':     _cat_map.get(m.categoria_normalizada, m.categoria_normalizada),
            'tercero':               m.tercero,
            'es_transferencia_interna': m.es_transferencia_interna,
            'afecta_resultado':      m.afecta_resultado,
            'cuenta_financiera':     str(m.cuenta_financiera) if m.cuenta_financiera else None,
            'cuenta_financiera_id':  str(m.cuenta_financiera_id) if m.cuenta_financiera_id else None,
            'referencia_externa':    m.referencia_externa,
            'cantidad_documentos':   m.cantidad_documentos,
            'rut_contraparte':       m.rut_contraparte,
            'nombre_contraparte':    m.nombre_contraparte,
            'monto_neto':            float(m.monto_neto) if m.monto_neto else None,
            'monto_iva':             float(m.monto_iva)  if m.monto_iva  else None,
            'notas':                 m.notas,
            'es_ingreso':            m.es_ingreso,
        } for m in qs]

        return JsonResponse({'movimientos': data, 'total': len(data)})

    # ── POST: crear movimiento manual ──
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    for field in ['fecha', 'tipo', 'descripcion', 'monto']:
        if not body.get(field):
            return JsonResponse({'error': f'Campo requerido: {field}'}, status=400)

    try:
        monto = Decimal(str(body['monto']))
        if monto <= 0:
            return JsonResponse({'error': 'El monto debe ser mayor a 0'}, status=400)
    except (InvalidOperation, ValueError):
        return JsonResponse({'error': 'Monto inválido'}, status=400)

    monto_neto = monto_iva = None
    if body['tipo'] in ['suma_facturas_emitidas', 'suma_facturas_recibidas']:
        info = calcular_iva(monto)
        monto_neto, monto_iva = info['neto'], info['iva']
    if body.get('monto_neto'):
        monto_neto = Decimal(str(body['monto_neto']))
    if body.get('monto_iva'):
        monto_iva = Decimal(str(body['monto_iva']))

    cuenta = None
    if body.get('cuenta_financiera_id'):
        from .models import CuentaFinanciera
        try:
            cuenta = CuentaFinanciera.objects.get(pk=body['cuenta_financiera_id'])
        except CuentaFinanciera.DoesNotExist:
            pass

    # Para movimientos manuales: si la cuenta es en moneda extranjera y viene tipo_cambio,
    # guardamos monto_moneda_orig = monto ingresado y monto = monto × TC (monto_base_clp)
    moneda_mov  = cuenta.moneda if cuenta else 'CLP'
    tipo_cambio = None
    monto_orig  = None
    monto_clp   = monto

    if moneda_mov != 'CLP' and body.get('tipo_cambio'):
        try:
            tipo_cambio = Decimal(str(body['tipo_cambio']))
            monto_orig  = monto
            monto_clp   = monto * tipo_cambio
        except (InvalidOperation, ValueError):
            pass

    m = MovimientoDiario.objects.create(
        fecha               = body['fecha'],
        tipo                = body['tipo'],
        descripcion         = body['descripcion'],
        monto               = monto_clp,          # siempre monto_base_clp
        medio_pago          = body.get('medio_pago', 'efectivo'),
        cantidad_documentos = body.get('cantidad_documentos'),
        rut_contraparte     = body.get('rut_contraparte', ''),
        nombre_contraparte  = body.get('nombre_contraparte', ''),
        monto_neto          = monto_neto,
        monto_iva           = monto_iva,
        notas               = body.get('notas', ''),
        cuenta_financiera   = cuenta,
        moneda              = moneda_mov,
        monto_moneda_orig   = monto_orig,
        tipo_cambio         = tipo_cambio,
    )

    return JsonResponse({
        'id':               str(m.id),
        'mensaje':          'Movimiento registrado exitosamente',
        'monto_neto':       int(monto_neto) if monto_neto else None,
        'monto_iva':        int(monto_iva)  if monto_iva  else None,
        'tipo_cambio_usado': float(tipo_cambio) if tipo_cambio else None,
        'moneda':           moneda_mov,
        'monto_clp':        int(monto_clp),
    }, status=201)


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
def movimiento_detalle(request, mov_id):
    try:
        m = MovimientoDiario.objects.get(id=mov_id)
    except MovimientoDiario.DoesNotExist:
        return JsonResponse({'error': 'No encontrado'}, status=404)

    if request.method == 'GET':
        return JsonResponse({
            'id':                    str(m.id),
            'fecha':                 str(m.fecha),
            'tipo':                  m.tipo,
            'tipo_display':          m.get_tipo_display(),
            'descripcion':           m.descripcion,
            'monto':                 float(m.monto),
            'moneda':                m.moneda,
            'monto_moneda_orig':     float(m.monto_moneda_orig) if m.monto_moneda_orig is not None else None,
            'tipo_cambio':           float(m.tipo_cambio) if m.tipo_cambio is not None else None,
            'medio_pago':            m.medio_pago,
            'cuenta_financiera_id':  str(m.cuenta_financiera_id) if m.cuenta_financiera_id else None,
            'categoria_normalizada': m.categoria_normalizada,
            'tercero':               m.tercero,
            'es_transferencia_interna': m.es_transferencia_interna,
            'referencia_externa':    m.referencia_externa,
            'cantidad_documentos':   m.cantidad_documentos,
            'rut_contraparte':       m.rut_contraparte,
            'nombre_contraparte':    m.nombre_contraparte,
            'notas':                 m.notas,
        })

    if request.method == 'DELETE':
        m.delete()
        return JsonResponse({'mensaje': 'Eliminado'})

    # ── PUT: editar movimiento ──
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    campos_simples = ['tipo', 'descripcion', 'medio_pago', 'notas',
                      'rut_contraparte', 'nombre_contraparte',
                      'categoria_normalizada', 'tercero', 'es_transferencia_interna']
    for field in campos_simples:
        if field in body:
            setattr(m, field, body[field])

    if 'fecha' in body and body.get('fecha'):
        m.fecha = body.get('fecha')

    if 'cantidad_documentos' in body:
        m.cantidad_documentos = body.get('cantidad_documentos') or None

    # Permitir cambiar cuenta financiera y, si corresponde, sincronizar moneda
    if 'cuenta_financiera_id' in body:
        cuenta_id = body.get('cuenta_financiera_id')
        if cuenta_id:
            try:
                from .models import CuentaFinanciera
                cuenta = CuentaFinanciera.objects.get(pk=cuenta_id)
                m.cuenta_financiera = cuenta
                m.moneda = cuenta.moneda or m.moneda
            except CuentaFinanciera.DoesNotExist:
                return JsonResponse({'error': 'Cuenta financiera no encontrada'}, status=404)
        else:
            m.cuenta_financiera = None
            if body.get('moneda'):
                m.moneda = body.get('moneda')

    if 'moneda' in body and body.get('moneda'):
        m.moneda = body.get('moneda')

    def _dec(v):
        if v in (None, '', 'null'):
            return None
        try:
            return Decimal(str(v).replace(',', '.'))
        except Exception:
            raise ValueError(f'Número inválido: {v}')

    # Recalcular importes.
    # m.monto siempre queda en CLP para reportes.
    try:
        recalcular_importes = any(k in body for k in ['monto', 'monto_clp', 'monto_moneda_orig', 'tipo_cambio', 'moneda'])
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    if recalcular_importes:
        monto_clp = _dec(body.get('monto_clp', body.get('monto')))
        monto_orig = _dec(body.get('monto_moneda_orig'))
        tipo_cambio = _dec(body.get('tipo_cambio'))

        if m.moneda != 'CLP':
            if monto_orig is None:
                monto_orig = m.monto_moneda_orig
            if tipo_cambio is None:
                tipo_cambio = m.tipo_cambio
            if monto_clp is None and monto_orig is not None and tipo_cambio is not None:
                monto_clp = monto_orig * tipo_cambio

            m.monto_moneda_orig = monto_orig
            m.tipo_cambio = tipo_cambio
            if monto_clp is not None:
                m.monto = monto_clp
            elif monto_orig is not None:
                # fallback cuando aún no hay TC
                m.monto = monto_orig
            m.tc_pendiente = bool(m.moneda != 'CLP' and not m.tipo_cambio)
        else:
            if monto_clp is None:
                monto_clp = monto_orig if monto_orig is not None else m.monto
            if monto_clp is not None:
                m.monto = monto_clp
            m.monto_moneda_orig = None
            m.tipo_cambio = None
            m.tc_pendiente = False

        if m.tipo in ['suma_facturas_emitidas', 'suma_facturas_recibidas']:
            info = calcular_iva(m.monto)
            m.monto_neto = info['neto']
            m.monto_iva = info['iva']

    m.save()
    return JsonResponse({
        'mensaje': 'Actualizado',
        'id': str(m.id),
        'monto_clp': float(m.monto),
        'monto_moneda_orig': float(m.monto_moneda_orig) if m.monto_moneda_orig is not None else None,
        'tipo_cambio': float(m.tipo_cambio) if m.tipo_cambio is not None else None,
        'moneda': m.moneda,
    })


# ──────────────────────────────────────────────
# DASHBOARD
# ──────────────────────────────────────────────

@require_http_methods(["GET"])
def dashboard_cuenta_detalle(request, cuenta_id):
    page = request.GET.get('page', 1)
    page_size = request.GET.get('page_size', 20)
    try:
        detalle = get_detalle_saldo_cuenta_paginado(cuenta_id, page=page, page_size=page_size)
        return JsonResponse(detalle)
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=404)


def _tipo_cambio_referencia(cuenta, saldos_cta=None):
    if cuenta.moneda == 'CLP':
        return Decimal('1')
    if saldos_cta:
        fila = next((c for c in saldos_cta if c['id'] == str(cuenta.id)), None)
        if fila and fila.get('tipo_cambio'):
            return Decimal(str(fila['tipo_cambio']))
    mov = MovimientoDiario.objects.filter(
        cuenta_financiera=cuenta,
        tipo_cambio__isnull=False,
    ).exclude(tipo_cambio=0).order_by('-fecha', '-creado_en').first()
    return Decimal(str(mov.tipo_cambio)) if mov and mov.tipo_cambio else Decimal('1')


def _serialize_control(control, saldos_cta=None):
    if not control:
        return None

    saldos_cta = saldos_cta or []
    saldos_map = {c['id']: c for c in saldos_cta}
    detalles = []

    # Totales CLP referenciales. Incluyen equivalentes de cuentas USD/EUR,
    # pero no se usan para validar diferencias de cuentas en moneda extranjera.
    total_real_clp = Decimal('0')
    total_sistema_clp = Decimal('0')

    # Totales conciliables en CLP: solo cuentas CLP + pendiente efectivo.
    total_real_conciliable_clp = Decimal('0')
    total_sistema_conciliable_clp = Decimal('0')
    diferencias_por_moneda = {}

    for det in control.detalles.select_related('cuenta_financiera').all():
        cuenta = det.cuenta_financiera
        moneda = cuenta.moneda or 'CLP'
        sistema = saldos_map.get(str(cuenta.id), {})
        tc = _tipo_cambio_referencia(cuenta, saldos_cta)

        saldo_real_orig = Decimal(str(det.saldo_real or 0))
        saldo_sistema_orig = Decimal(str(sistema.get('saldo', 0) or 0))
        saldo_sistema_clp = Decimal(str(sistema.get('saldo_clp', 0) or 0))
        saldo_real_clp = saldo_real_orig if moneda == 'CLP' else saldo_real_orig * tc

        total_real_clp += saldo_real_clp
        total_sistema_clp += saldo_sistema_clp

        diferencia_orig = saldo_real_orig - saldo_sistema_orig
        diferencia_clp_referencial = saldo_real_clp - saldo_sistema_clp

        if moneda == 'CLP':
            diferencia_conciliacion = diferencia_clp_referencial
            unidad_conciliacion = 'CLP'
            diferencia_clp_es_referencial = False
            total_real_conciliable_clp += saldo_real_orig
            total_sistema_conciliable_clp += saldo_sistema_clp
        else:
            diferencia_conciliacion = diferencia_orig
            unidad_conciliacion = moneda
            diferencia_clp_es_referencial = True
            diferencias_por_moneda[moneda] = diferencias_por_moneda.get(moneda, Decimal('0')) + diferencia_orig

        detalles.append({
            'cuenta_id': str(cuenta.id),
            'cuenta_nombre': cuenta.nombre,
            'institucion': cuenta.institucion,
            'moneda': moneda,
            'saldo_real_orig': float(round(saldo_real_orig, 4)),
            'saldo_real_clp': float(round(saldo_real_clp, 0)),
            'saldo_sistema_orig': float(round(saldo_sistema_orig, 4)),
            'saldo_sistema_clp': float(round(saldo_sistema_clp, 0)),
            'diferencia_orig': float(round(diferencia_orig, 4)),
            'diferencia_clp': float(round(diferencia_clp_referencial, 0)),
            'diferencia_conciliacion': float(round(diferencia_conciliacion, 4 if unidad_conciliacion != 'CLP' else 0)),
            'unidad_conciliacion': unidad_conciliacion,
            'diferencia_clp_referencial': float(round(diferencia_clp_referencial, 0)),
            'diferencia_clp_es_referencial': diferencia_clp_es_referencial,
            'tipo_cambio_ref': float(tc),
        })

    pendiente = Decimal(str(control.pendiente_efectivo_clp or 0))
    diferencia_total_clp = total_real_conciliable_clp + pendiente - total_sistema_conciliable_clp

    return {
        'id': control.id,
        'fecha': str(control.fecha),
        'pendiente_efectivo_clp': float(round(pendiente, 0)),
        'notas': control.notas,
        'detalles': detalles,
        'total_real_clp': float(round(total_real_clp, 0)),
        'total_sistema_clp': float(round(total_sistema_clp, 0)),
        'total_real_clp_referencial': float(round(total_real_clp, 0)),
        'total_sistema_clp_referencial': float(round(total_sistema_clp, 0)),
        'total_real_conciliable_clp': float(round(total_real_conciliable_clp + pendiente, 0)),
        'total_sistema_conciliable_clp': float(round(total_sistema_conciliable_clp, 0)),
        'diferencia_total_clp': float(round(diferencia_total_clp, 0)),
        'diferencias_por_moneda': {moneda: float(round(valor, 4)) for moneda, valor in diferencias_por_moneda.items()},
        'nota_multimoneda': 'Las cuentas en moneda extranjera se concilian en su moneda original; el CLP es solo referencial.',
    }


def dashboard_data(request):
    hoy         = date.today()
    fecha_desde = date(hoy.year, hoy.month, 1)
    fecha_hasta = hoy

    if request.GET.get('desde'):
        fecha_desde = date.fromisoformat(request.GET['desde'])
    if request.GET.get('hasta'):
        fecha_hasta = date.fromisoformat(request.GET['hasta'])

    resumen     = get_resumen_periodo(fecha_desde, fecha_hasta)
    kpis        = get_kpis_salud(fecha_desde, fecha_hasta)
    # El gráfico de Flujo Mensual debe respetar el rango filtrado por la UI.
    # Antes se calculaba con hoy.year, quedando fijo en el año actual.
    flujo       = get_flujo_mensual_periodo(fecha_desde, fecha_hasta)
    ventas_dia  = get_ventas_por_dia(fecha_desde, fecha_hasta)
    dist_gastos = get_distribucion_gastos(fecha_desde, fecha_hasta)
    saldo_actual= get_saldo_actual()
    saldos_cta  = get_saldo_por_cuenta()
    detalle_cuentas = get_detalle_saldos_cuentas()
    latest_control = ControlSaldoReal.objects.prefetch_related('detalles__cuenta_financiera').first()

    sin_clasificar = MovimientoDiario.objects.filter(
        categoria_normalizada='sin_clasificar'
    ).count()

    anios_disponibles = [
        d.year for d in MovimientoDiario.objects.dates('fecha', 'year', order='ASC')
    ]
    if not anios_disponibles:
        anios_disponibles = [hoy.year]

    ultimos = MovimientoDiario.objects.select_related('cuenta_financiera').all()[:10]
    ultimos_data = [{
        'fecha':                   str(m.fecha),
        'tipo_display':            m.get_tipo_display(),
        'descripcion':             m.descripcion,
        'monto':                   float(m.monto),
        'moneda':                  m.moneda,
        'monto_moneda_orig':       float(m.monto_moneda_orig) if m.monto_moneda_orig else None,
        'tipo_cambio':             float(m.tipo_cambio) if m.tipo_cambio else None,
        'es_ingreso':              m.es_ingreso,
        'es_transferencia_interna':m.es_transferencia_interna,
        'categoria_normalizada':   m.categoria_normalizada,
        'cuenta':                  str(m.cuenta_financiera) if m.cuenta_financiera else None,
    } for m in ultimos]

    def _v(v):
        return int(v) if isinstance(v, Decimal) else v

    # Resumen multimoneda para el panel de saldos
    saldo_usd_orig = sum(c['saldo'] for c in saldos_cta if c['moneda'] == 'USD')
    saldo_eur_orig = sum(c['saldo'] for c in saldos_cta if c['moneda'] == 'EUR')
    tc_usd = next((c['tipo_cambio'] for c in saldos_cta if c['moneda'] == 'USD'), None)
    tc_eur = next((c['tipo_cambio'] for c in saldos_cta if c['moneda'] == 'EUR'), None)

    return JsonResponse({
        'resumen':             {k: _v(v) for k, v in resumen.items()},
        'kpis':                kpis,
        'flujo_mensual':       flujo,
        'ventas_por_dia':      ventas_dia,
        'distribucion_gastos': dist_gastos,
        'saldo_actual':        int(saldo_actual),
        'saldos_por_cuenta':   saldos_cta,          # incluye saldo (orig) + saldo_clp
        'detalle_cuentas':     detalle_cuentas,
        'saldo_multimoneda': {
            'total_clp':       int(saldo_actual),
            'usd_saldo':       round(saldo_usd_orig, 2) if saldo_usd_orig else None,
            'usd_tipo_cambio': float(tc_usd) if tc_usd else None,
            'eur_saldo':       round(saldo_eur_orig, 2) if saldo_eur_orig else None,
            'eur_tipo_cambio': float(tc_eur) if tc_eur else None,
            'tc_estimado':     any(c.get('tc_estimado') for c in saldos_cta),
        },
        'sin_clasificar':      sin_clasificar,
        'ultimos_movimientos': ultimos_data,
        'control_saldos':      _serialize_control(latest_control, saldos_cta),
        'anios_disponibles':   anios_disponibles,
        'periodo':             {'desde': str(fecha_desde), 'hasta': str(fecha_hasta)},
    })


def resumen_mensual(request, anio, mes):
    fecha_desde = date(anio, mes, 1)
    ultimo_dia  = calendar.monthrange(anio, mes)[1]
    fecha_hasta = date(anio, mes, ultimo_dia)

    resumen     = get_resumen_periodo(fecha_desde, fecha_hasta)
    dist_gastos = get_distribucion_gastos(fecha_desde, fecha_hasta)
    ventas_dia  = get_ventas_por_dia(fecha_desde, fecha_hasta)

    return JsonResponse({
        'anio':      anio,
        'mes':       mes,
        'mes_nombre':calendar.month_name[mes],
        'resumen':   {k: int(v) if isinstance(v, Decimal) else v for k, v in resumen.items()},
        'distribucion_gastos': dist_gastos,
        'ventas_por_dia':      ventas_dia,
    })


# ──────────────────────────────────────────────
# CIERRES DIARIOS
# ──────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET", "POST"])
def cierres(request):
    if request.method == 'GET':
        limit = int(request.GET.get('limit', 30))
        cs    = CierreDiario.objects.all()[:limit]
        return JsonResponse({'cierres': [{
            'fecha':             str(c.fecha),
            'saldo_inicial_caja':int(c.saldo_inicial_caja),
            'total_ingresos':    int(c.total_ingresos),
            'total_egresos':     int(c.total_egresos),
            'saldo_final_caja':  int(c.saldo_final_caja),
            'resultado_dia':     int(c.resultado_dia),
            'cerrado':           c.cerrado,
            'notas':             c.notas,
        } for c in cs]})

    body      = json.loads(request.body)
    fecha_str = body.get('fecha', str(date.today()))
    fecha     = date.fromisoformat(fecha_str)

    tipos_ingreso = ['ingreso_caja', 'ingreso_banco', 'suma_boletas',
                     'suma_facturas_emitidas', 'prestamo_recibido', 'otro_ingreso']

    movs_dia = MovimientoDiario.objects.filter(
        fecha=fecha, es_transferencia_interna=False
    ).exclude(categoria_normalizada__in=['transferencia_interna', 'conversion_divisa'])

    ingresos = movs_dia.filter(tipo__in=tipos_ingreso).aggregate(t=Sum('monto'))['t'] or Decimal('0')
    egresos  = movs_dia.exclude(tipo__in=tipos_ingreso).aggregate(t=Sum('monto'))['t'] or Decimal('0')

    cierre_ant = CierreDiario.objects.filter(fecha__lt=fecha).first()
    saldo_inic = cierre_ant.saldo_final_caja if cierre_ant else Decimal('0')

    cierre, _ = CierreDiario.objects.update_or_create(
        fecha=fecha,
        defaults={
            'saldo_inicial_caja': saldo_inic,
            'total_ingresos':     ingresos,
            'total_egresos':      egresos,
            'saldo_final_caja':   saldo_inic + ingresos - egresos,
            'cerrado':            True,
            'cerrado_en':         timezone.now(),
            'notas':              body.get('notas', ''),
        }
    )
    return JsonResponse({
        'fecha':      str(cierre.fecha),
        'saldo_final':int(cierre.saldo_final_caja),
        'resultado':  int(cierre.resultado_dia),
        'mensaje':    'Cierre registrado exitosamente',
    }, status=201)


# ──────────────────────────────────────────────
# PRESUPUESTO
# ──────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET", "POST"])
def presupuesto(request):
    if request.method == 'GET':
        anio = int(request.GET.get('anio', date.today().year))
        mes  = request.GET.get('mes')
        qs   = PresupuestoMensual.objects.filter(anio=anio)
        if mes:
            qs = qs.filter(mes=int(mes))
        return JsonResponse({'presupuestos': [{
            'id':                  p.id,
            'anio':                p.anio,
            'mes':                 p.mes,
            'categoria':           p.categoria,
            'categoria_display':   p.get_categoria_display(),
            'monto_presupuestado': int(p.monto_presupuestado),
        } for p in qs]})

    body = json.loads(request.body)
    p, _ = PresupuestoMensual.objects.update_or_create(
        anio=body['anio'], mes=body['mes'], categoria=body['categoria'],
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
            'nombre':              config.nombre,
            'rut':                 config.rut,
            'giro':                config.giro,
            'direccion':           config.direccion,
            'telefono':            config.telefono,
            'email':               config.email,
            'moneda':              config.moneda,
            'saldo_inicial_caja':  int(config.saldo_inicial_caja),
            'saldo_inicial_banco': int(config.saldo_inicial_banco),
            'fecha_inicio_operaciones': str(config.fecha_inicio_operaciones)
                                        if config.fecha_inicio_operaciones else None,
        })
    body = json.loads(request.body)
    for f in ['nombre', 'rut', 'giro', 'direccion', 'telefono', 'email',
              'saldo_inicial_caja', 'saldo_inicial_banco', 'fecha_inicio_operaciones']:
        if f in body:
            setattr(config, f, body[f])
    config.save()
    return JsonResponse({'mensaje': 'Configuración guardada'})


# ──────────────────────────────────────────────
# CONTROL DE SALDOS REALES
# ──────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET", "POST"])
def control_saldos(request):
    if request.method == 'GET':
        saldos_cta = get_saldo_por_cuenta()
        fecha = request.GET.get('fecha')
        qs = ControlSaldoReal.objects.prefetch_related('detalles__cuenta_financiera')
        control = qs.filter(fecha=fecha).first() if fecha else qs.first()
        historial = []
        for c in qs[:20]:
            historial.append({
                'id': c.id,
                'fecha': str(c.fecha),
                'pendiente_efectivo_clp': float(round(c.pendiente_efectivo_clp, 0)),
                'cuentas': c.detalles.count(),
                'notas': c.notas,
            })
        return JsonResponse({
            'control': _serialize_control(control, saldos_cta),
            'historial': historial,
            'cuentas_sistema': saldos_cta,
        })

    body = json.loads(request.body)
    fecha = body.get('fecha') or str(date.today())
    pendiente = Decimal(str(body.get('pendiente_efectivo_clp') or 0))
    notas = body.get('notas', '')
    detalles = body.get('detalles', [])

    control, _ = ControlSaldoReal.objects.update_or_create(
        fecha=fecha,
        defaults={
            'pendiente_efectivo_clp': pendiente,
            'notas': notas,
        }
    )
    control.detalles.all().delete()
    cuentas = {str(c.id): c for c in CuentaFinanciera.objects.filter(activa=True)}
    nuevos = []
    for d in detalles:
        cuenta_id = str(d.get('cuenta_financiera_id') or '')
        if not cuenta_id or cuenta_id not in cuentas:
            continue
        saldo_real = Decimal(str(d.get('saldo_real') or 0))
        nuevos.append(ControlSaldoRealDetalle(
            control=control,
            cuenta_financiera=cuentas[cuenta_id],
            saldo_real=saldo_real,
        ))
    if nuevos:
        ControlSaldoRealDetalle.objects.bulk_create(nuevos)

    control = ControlSaldoReal.objects.prefetch_related('detalles__cuenta_financiera').get(pk=control.pk)
    return JsonResponse({
        'ok': True,
        'control': _serialize_control(control, get_saldo_por_cuenta()),
        'mensaje': 'Control de saldos guardado',
    }, status=201)


@csrf_exempt
@require_http_methods(["GET", "DELETE"])
def control_saldos_detalle(request, control_id):
    try:
        control = ControlSaldoReal.objects.prefetch_related('detalles__cuenta_financiera').get(pk=control_id)
    except ControlSaldoReal.DoesNotExist:
        return JsonResponse({'error': 'Control no encontrado'}, status=404)

    if request.method == 'DELETE':
        control.delete()
        return JsonResponse({'ok': True})

    return JsonResponse({'control': _serialize_control(control, get_saldo_por_cuenta())})


# ──────────────────────────────────────────────
# CATÁLOGOS
# ──────────────────────────────────────────────

def tipos_movimiento(request):
    return JsonResponse({
        'tipos':      [{'value': k, 'label': v} for k, v in MovimientoDiario.TIPOS],
        'medios_pago':[{'value': k, 'label': v} for k, v in MovimientoDiario.MEDIOS_PAGO],
        'categorias': [{'value': k, 'label': v} for k, v in MovimientoDiario.CATEGORIAS_NORM],
    })


def calcular_iva_view(request):
    try:
        resultado = calcular_iva(Decimal(str(request.GET.get('monto', 0))))
        return JsonResponse({k: int(v) for k, v in resultado.items()})
    except Exception:
        return JsonResponse({'error': 'Monto inválido'}, status=400)
