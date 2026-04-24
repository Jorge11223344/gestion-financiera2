"""
Utilidades financieras para KPIs y métricas de salud empresarial.

ARQUITECTURA MONETARIA:
  Cada movimiento guarda SIEMPRE:
    - monto_moneda_orig  → valor en moneda original (USD, EUR, CLP)
    - moneda             → moneda original
    - tipo_cambio        → TC usado al registrar
    - monto              → equivalente en CLP (monto_base_clp)

  Los reportes tienen DOS miradas:
    1. Por moneda original (para revisar proveedores extranjeros en USD)
    2. Consolidado en CLP (para el P&L y dashboard general)
"""
from decimal import Decimal
from django.db.models import Sum, Q
import calendar


# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

_TIPOS_INGRESO = [
    'ingreso_caja', 'ingreso_banco', 'suma_boletas',
    'suma_facturas_emitidas', 'prestamo_recibido', 'otro_ingreso'
]

_CATEGORIAS_NEUTRAS = {'transferencia_interna', 'conversion_divisa'}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────

def _qs_operacional(qs):
    """
    Excluye transferencias internas y conversiones de divisa.
    Estas NO afectan el P&L — solo mueven dinero entre cuentas propias.
    """
    return qs.filter(
        es_transferencia_interna=False,
    ).exclude(
        categoria_normalizada__in=_CATEGORIAS_NEUTRAS
    )


def _es_movimiento_neutro(movimiento) -> bool:
    """
    Un movimiento es neutro SOLO para resultado/P&L cuando:
    - está marcado como transferencia interna, o
    - su categoría es transferencia_interna / conversion_divisa.

    Regla ERP importante:
    - Saldos por cuenta: SÍ incluyen estos movimientos.
    - Resultado/utilidad: NO los incluye.
    """
    return bool(
        getattr(movimiento, 'es_transferencia_interna', False) or
        getattr(movimiento, 'categoria_normalizada', None) in _CATEGORIAS_NEUTRAS
    )


def get_tc_vigente(moneda: str) -> Decimal:
    """
    Tipo de cambio vigente para consolidar en CLP.

    Estrategia: usa el ÚLTIMO tipo_cambio registrado en movimientos reales.
    Si no hay ninguno aún, usa fallback conservador.
    """
    if moneda == 'CLP':
        return Decimal('1')

    from .models import MovimientoDiario
    ultimo = (
        MovimientoDiario.objects
        .filter(moneda=moneda, tipo_cambio__isnull=False)
        .order_by('-fecha', '-creado_en')
        .values('tipo_cambio')
        .first()
    )
    if ultimo:
        return Decimal(str(ultimo['tipo_cambio']))

    FALLBACKS = {'USD': Decimal('950'), 'EUR': Decimal('1030')}
    return FALLBACKS.get(moneda, Decimal('1'))


def _monto_clp(movimiento) -> Decimal:
    """
    Retorna el monto en CLP de un movimiento.
    El campo `monto` debe ser SIEMPRE el monto_base_clp.
    """
    return Decimal(str(movimiento.monto or 0))


def _monto_clp_robusto(movimiento) -> Decimal:
    """
    Para movimientos en moneda extranjera, intenta reconstruir CLP desde
    monto_moneda_orig * tipo_cambio cuando el monto guardado parezca venir
    aún en moneda original.
    """
    monto = Decimal(str(movimiento.monto or 0))
    moneda = getattr(movimiento, 'moneda', 'CLP') or 'CLP'
    monto_orig = getattr(movimiento, 'monto_moneda_orig', None)
    tc = getattr(movimiento, 'tipo_cambio', None)

    if moneda != 'CLP' and monto_orig not in (None, '') and tc not in (None, ''):
        try:
            monto_orig_d = Decimal(str(monto_orig))
            tc_d = Decimal(str(tc))
            reconstruido = monto_orig_d * tc_d
            # Si el monto guardado es demasiado pequeño respecto al reconstruido,
            # asumimos que quedó grabado en moneda original.
            if reconstruido > 0 and (monto <= (reconstruido / Decimal('10'))):
                return reconstruido
        except Exception:
            pass
    return monto


# ─────────────────────────────────────────────────────────────────────────────
# Resumen del período (P&L)
# ─────────────────────────────────────────────────────────────────────────────

def get_resumen_periodo(fecha_desde, fecha_hasta):
    """
    Estado de resultados del período.
    SIEMPRE en CLP (campo `monto` = monto_base_clp).
    Excluye transferencias internas y conversiones de divisa.
    """
    from .models import MovimientoDiario

    movs_base = MovimientoDiario.objects.filter(
        fecha__gte=fecha_desde,
        fecha__lte=fecha_hasta
    )

    # P&L operacional: excluye transferencias internas y conversiones.
    movs = _qs_operacional(movs_base)

    # Flujo interno financiero: NO afecta resultado, pero sí explica depósitos
    # entre cuentas propias, como Banco Chile → Global66 CLP y CLP → USD.
    movs_internos = movs_base.filter(
        Q(es_transferencia_interna=True) |
        Q(categoria_normalizada__in=_CATEGORIAS_NEUTRAS)
    )
    transferencias_recibidas = (
        movs_internos.filter(tipo__in=_TIPOS_INGRESO)
        .aggregate(t=Sum('monto'))['t'] or Decimal('0')
    )
    transferencias_enviadas = (
        movs_internos.exclude(tipo__in=_TIPOS_INGRESO)
        .aggregate(t=Sum('monto'))['t'] or Decimal('0')
    )
    transferencias_neto = transferencias_recibidas - transferencias_enviadas

    total_ingresos = (
        movs.filter(tipo__in=_TIPOS_INGRESO)
        .aggregate(t=Sum('monto'))['t'] or Decimal('0')
    )
    total_egresos = (
        movs.exclude(tipo__in=_TIPOS_INGRESO)
        .aggregate(t=Sum('monto'))['t'] or Decimal('0')
    )

    ventas = movs.filter(
        Q(tipo__in=['suma_boletas', 'suma_facturas_emitidas']) |
        Q(categoria_normalizada='venta')
    ).aggregate(t=Sum('monto'))['t'] or Decimal('0')

    costos = movs.filter(
        Q(tipo='suma_facturas_recibidas') |
        Q(categoria_normalizada__in=['pago_proveedor', 'pago_importacion'])
    ).aggregate(t=Sum('monto'))['t'] or Decimal('0')

    remuneraciones = movs.filter(
        Q(tipo='remuneracion') |
        Q(categoria_normalizada='remuneracion_norm')
    ).aggregate(t=Sum('monto'))['t'] or Decimal('0')

    impuestos = movs.filter(
        Q(tipo='impuesto') |
        Q(categoria_normalizada='pago_impuesto')
    ).aggregate(t=Sum('monto'))['t'] or Decimal('0')

    logistica = movs.filter(
        categoria_normalizada='gasto_logistica'
    ).aggregate(t=Sum('monto'))['t'] or Decimal('0')

    comisiones = movs.filter(
        categoria_normalizada='comision_bancaria'
    ).aggregate(t=Sum('monto'))['t'] or Decimal('0')

    intereses = movs.filter(
        categoria_normalizada='interes_ganado'
    ).aggregate(t=Sum('monto'))['t'] or Decimal('0')

    aportes_socio = movs.filter(
        categoria_normalizada='aporte_socio'
    ).aggregate(t=Sum('monto'))['t'] or Decimal('0')

    utilidad_bruta = ventas - costos
    utilidad_operacional = utilidad_bruta - remuneraciones - impuestos - logistica - comisiones
    resultado_neto = total_ingresos - total_egresos

    base_margen = ventas + intereses + aportes_socio

    margen_bruto = (utilidad_bruta / ventas * 100) if ventas > 0 else Decimal('0')
    margen_operacional = (utilidad_operacional / ventas * 100) if ventas > 0 else Decimal('0')
    margen_neto = (resultado_neto / base_margen * 100) if base_margen > 0 else Decimal('0')

    return {
        'total_ingresos': total_ingresos,
        'total_egresos': total_egresos,
        'ventas': ventas,
        'costos': costos,
        'remuneraciones': remuneraciones,
        'impuestos': impuestos,
        'logistica': logistica,
        'comisiones': comisiones,
        'intereses': intereses,
        'aportes_socio': aportes_socio,
        'transferencias_recibidas': transferencias_recibidas,
        'transferencias_enviadas': transferencias_enviadas,
        'transferencias_neto': transferencias_neto,
        'utilidad_bruta': utilidad_bruta,
        'utilidad_operacional': utilidad_operacional,
        'resultado_neto': resultado_neto,
        'margen_bruto': round(margen_bruto, 1),
        'margen_operacional': round(margen_operacional, 1),
        'margen_neto': round(margen_neto, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Flujo mensual
# ─────────────────────────────────────────────────────────────────────────────

def get_flujo_mensual(anio, meses=12):
    from .models import MovimientoDiario

    resultado = []
    for mes in range(1, meses + 1):
        movs = _qs_operacional(
            MovimientoDiario.objects.filter(fecha__year=anio, fecha__month=mes)
        )
        ingresos = sum((_monto_clp_robusto(m) for m in movs.filter(tipo__in=_TIPOS_INGRESO)), Decimal('0'))
        egresos = sum((_monto_clp_robusto(m) for m in movs.exclude(tipo__in=_TIPOS_INGRESO)), Decimal('0'))
        resultado.append({
            'mes': mes,
            'mes_nombre': calendar.month_abbr[mes],
            'ingresos': int(ingresos),
            'egresos': int(egresos),
            'resultado': int(ingresos - egresos),
        })
    return resultado


# ─────────────────────────────────────────────────────────────────────────────
# Ventas por día
# ─────────────────────────────────────────────────────────────────────────────

def get_ventas_por_dia(fecha_desde, fecha_hasta):
    from .models import MovimientoDiario

    tipos_venta = [
        'suma_boletas', 'suma_facturas_emitidas',
        'ingreso_caja', 'ingreso_banco', 'otro_ingreso'
    ]
    data = (
        _qs_operacional(
            MovimientoDiario.objects.filter(
                fecha__gte=fecha_desde,
                fecha__lte=fecha_hasta
            )
        )
        .filter(tipo__in=tipos_venta)
        .values('fecha')
        .annotate(total=Sum('monto'))
        .order_by('fecha')
    )
    return [{'fecha': str(d['fecha']), 'total': int(d['total'])} for d in data]


# ─────────────────────────────────────────────────────────────────────────────
# Distribución de gastos
# ─────────────────────────────────────────────────────────────────────────────

def get_distribucion_gastos(fecha_desde, fecha_hasta):
    from .models import MovimientoDiario

    CATEGORIAS_GASTOS = {
        'pago_importacion': 'Importaciones',
        'pago_proveedor': 'Proveedores',
        'remuneracion_norm': 'Remuneraciones',
        'gasto_logistica': 'Logística',
        'pago_impuesto': 'Impuestos',
        'comision_bancaria': 'Comisiones Bancarias',
        'gasto_operacional': 'Gastos Operacionales',
        'pago_prestamo_norm': 'Cuotas Préstamo',
    }

    resultado = []
    movs = _qs_operacional(
        MovimientoDiario.objects.filter(
            fecha__gte=fecha_desde,
            fecha__lte=fecha_hasta
        )
    )

    for cat, label in CATEGORIAS_GASTOS.items():
        total = movs.filter(categoria_normalizada=cat).aggregate(t=Sum('monto'))['t'] or Decimal('0')
        if total > 0:
            resultado.append({'categoria': label, 'total': int(total)})

    tipos_egreso_legacy = {
        'suma_facturas_recibidas': 'Compras',
        'remuneracion': 'Remuneraciones',
        'impuesto': 'Impuestos',
        'egreso_caja': 'Gastos Caja',
        'egreso_banco': 'Gastos Banco',
        'otro_egreso': 'Otros Gastos',
    }
    for tipo, label in tipos_egreso_legacy.items():
        total = movs.filter(
            tipo=tipo, categoria_normalizada='sin_clasificar'
        ).aggregate(t=Sum('monto'))['t'] or Decimal('0')
        if total > 0:
            resultado.append({'categoria': label, 'total': int(total)})

    return sorted(resultado, key=lambda x: x['total'], reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# KPIs de salud financiera
# ─────────────────────────────────────────────────────────────────────────────

def get_kpis_salud(fecha_desde, fecha_hasta):
    resumen = get_resumen_periodo(fecha_desde, fecha_hasta)
    ventas = resumen['ventas']
    resultado = resumen['resultado_neto']
    remuneraciones = resumen['remuneraciones']
    total_egresos = resumen['total_egresos']

    kpis = []

    if resultado > 0:
        estado, mensaje = 'verde', 'La empresa está generando ganancias'
    elif resultado == 0:
        estado, mensaje = 'amarillo', 'La empresa está en punto de equilibrio'
    else:
        estado, mensaje = 'rojo', 'La empresa está perdiendo dinero'
    kpis.append({
        'nombre': 'Resultado del Período',
        'valor': f"${int(resultado):,}".replace(',', '.'),
        'estado': estado, 'mensaje': mensaje, 'icono': '💰',
    })

    mb = float(resumen['margen_bruto'])
    estado = 'verde' if mb >= 40 else 'amarillo' if mb >= 20 else 'rojo'
    mensajes = {
        'verde': 'Margen saludable sobre el 40%',
        'amarillo': 'Margen aceptable, revisar costos',
        'rojo': 'Margen crítico, costos muy altos',
    }
    kpis.append({
        'nombre': 'Margen Bruto', 'valor': f"{mb:.1f}%",
        'estado': estado, 'mensaje': mensajes[estado], 'icono': '📊',
    })

    if ventas > 0:
        peso_rem = float(remuneraciones / ventas * 100)
        estado = 'verde' if peso_rem <= 30 else 'amarillo' if peso_rem <= 50 else 'rojo'
        msgs_rem = {
            'verde': 'Carga laboral controlada',
            'amarillo': 'Carga laboral elevada',
            'rojo': 'Remuneraciones consumen más del 50% de ventas',
        }
        kpis.append({
            'nombre': 'Remuneraciones / Ventas', 'valor': f"{peso_rem:.1f}%",
            'estado': estado, 'mensaje': msgs_rem[estado], 'icono': '👥',
        })

    if total_egresos > 0:
        cobertura = float(ventas / total_egresos)
        estado = 'verde' if cobertura >= 1.2 else 'amarillo' if cobertura >= 1.0 else 'rojo'
        msgs_cob = {
            'verde': 'Las ventas cubren holgadamente los gastos',
            'amarillo': 'Las ventas apenas cubren los gastos',
            'rojo': 'Las ventas no alcanzan a cubrir los gastos',
        }
        kpis.append({
            'nombre': 'Cobertura de Gastos', 'valor': f"{cobertura:.2f}x",
            'estado': estado, 'mensaje': msgs_cob[estado], 'icono': '🛡️',
        })

    dias = (fecha_hasta - fecha_desde).days + 1
    if dias > 0 and ventas > 0:
        venta_diaria = float(ventas) / dias
        if venta_diaria > 0:
            dias_pe = float(remuneraciones) / venta_diaria
            kpis.append({
                'nombre': 'Días para Punto de Equilibrio',
                'valor': f"{int(dias_pe)} días/mes",
                'estado': 'verde' if dias_pe < 20 else 'amarillo' if dias_pe < 26 else 'rojo',
                'mensaje': f"Necesitas vender {int(dias_pe)} días del mes solo para cubrir sueldos",
                'icono': '📅',
            })

    return kpis


# ─────────────────────────────────────────────────────────────────────────────
# IVA
# ─────────────────────────────────────────────────────────────────────────────

def calcular_iva(monto_bruto):
    TASA_IVA = Decimal('0.19')
    neto = round(monto_bruto / (1 + TASA_IVA))
    iva = monto_bruto - neto
    return {'neto': neto, 'iva': iva, 'bruto': monto_bruto}


# ─────────────────────────────────────────────────────────────────────────────
# Debug auditable de cuentas
# ─────────────────────────────────────────────────────────────────────────────

def _serializar_movimiento_detalle_cuenta(m):
    """
    Serializa un movimiento para el detalle auditable de una cuenta.

    Regla ERP:
      - Para SALDO DE CUENTA, una transferencia interna SÍ suma o resta.
      - Para RESULTADO/P&L, una transferencia interna es neutra.
    """
    es_ingreso = m.tipo in _TIPOS_INGRESO
    neutro_resultado = _es_movimiento_neutro(m)
    efecto_saldo = 'suma' if es_ingreso else 'resta'
    signo = '+' if es_ingreso else '-'

    monto_orig = m.monto_moneda_orig if m.monto_moneda_orig is not None else m.monto
    monto_clp = _monto_clp_robusto(m)

    return {
        'id': str(m.id),
        'fecha': str(m.fecha),
        'descripcion': m.descripcion,
        'tipo': m.tipo,
        'tipo_display': m.get_tipo_display(),
        'categoria': m.categoria_normalizada,
        'tercero': m.tercero,
        'moneda': m.moneda,
        'monto_clp': float(round(monto_clp, 2)),
        'monto_moneda_orig': float(round(Decimal(str(monto_orig or 0)), 4)) if monto_orig is not None else None,
        'tipo_cambio': float(m.tipo_cambio) if m.tipo_cambio else None,
        'es_transferencia_interna': bool(m.es_transferencia_interna),
        'afecta_resultado': not neutro_resultado,
        'efecto': efecto_saldo,
        'efecto_saldo': efecto_saldo,
        'efecto_resultado': 'neutro' if neutro_resultado else efecto_saldo,
        'signo': signo,
    }


def _calcular_saldo_cuenta(cuenta):
    """
    Cálculo centralizado de saldo por cuenta.

    Regla ERP:
      - Incluye TODOS los movimientos asociados a la cuenta.
      - Incluye transferencias internas y conversiones de divisa.
      - No decide utilidad ni resultado; solo calcula saldo financiero.
    """
    from .models import MovimientoDiario

    movs = MovimientoDiario.objects.filter(cuenta_financiera=cuenta)
    saldo_inicial_orig = Decimal(str(cuenta.saldo_inicial or 0))

    if cuenta.moneda == 'CLP':
        tc = Decimal('1')
        tc_estimado = False
        saldo_inicial_clp = saldo_inicial_orig
    else:
        tc = get_tc_vigente(cuenta.moneda)
        tc_estimado = not movs.filter(tipo_cambio__isnull=False).exists()
        saldo_inicial_clp = saldo_inicial_orig * tc

    ingresos_orig = Decimal('0')
    egresos_orig = Decimal('0')
    ingresos_clp = Decimal('0')
    egresos_clp = Decimal('0')
    transferencias_internas_clp = Decimal('0')
    transferencias_internas_count = 0

    for m in movs:
        monto_orig = m.monto_moneda_orig if m.monto_moneda_orig is not None else m.monto
        monto_orig = Decimal(str(monto_orig or 0))
        monto_clp = _monto_clp_robusto(m)
        es_ingreso = m.tipo in _TIPOS_INGRESO

        if es_ingreso:
            ingresos_orig += monto_orig
            ingresos_clp += monto_clp
        else:
            egresos_orig += monto_orig
            egresos_clp += monto_clp

        if _es_movimiento_neutro(m):
            transferencias_internas_count += 1
            transferencias_internas_clp += monto_clp if es_ingreso else -monto_clp

    saldo_final_orig = saldo_inicial_orig + ingresos_orig - egresos_orig
    saldo_final_clp = saldo_inicial_clp + ingresos_clp - egresos_clp

    return {
        'saldo_inicial_orig': saldo_inicial_orig,
        'saldo_inicial_clp': saldo_inicial_clp,
        'ingresos_orig': ingresos_orig,
        'egresos_orig': egresos_orig,
        'ingresos_clp': ingresos_clp,
        'egresos_clp': egresos_clp,
        'saldo_final_orig': saldo_final_orig,
        'saldo_final_clp': saldo_final_clp,
        'tipo_cambio': tc,
        'tc_estimado': tc_estimado,
        'transferencias_internas_clp': transferencias_internas_clp,
        'transferencias_internas_count': transferencias_internas_count,
        'movimientos_count': movs.count(),
    }


def _resumen_detalle_saldo_cuenta(cuenta):
    data = _calcular_saldo_cuenta(cuenta)

    return {
        'cuenta_id': str(cuenta.pk),
        'id': str(cuenta.pk),
        'nombre': cuenta.nombre,
        'institucion': cuenta.institucion,
        'tipo_cuenta': cuenta.get_tipo_cuenta_display(),
        'moneda': cuenta.moneda,
        'saldo_inicial_orig': float(round(data['saldo_inicial_orig'], 4)),
        'saldo_inicial_clp': float(round(data['saldo_inicial_clp'], 0)),
        'ingresos_orig': float(round(data['ingresos_orig'], 4)),
        'egresos_orig': float(round(data['egresos_orig'], 4)),
        'ingresos_clp': float(round(data['ingresos_clp'], 0)),
        'egresos_clp': float(round(data['egresos_clp'], 0)),
        'saldo_final_orig': float(round(data['saldo_final_orig'], 4)),
        'saldo_final_clp': float(round(data['saldo_final_clp'], 0)),
        'saldo': float(round(data['saldo_final_orig'], 4)),
        'saldo_clp': float(round(data['saldo_final_clp'], 0)),
        'tipo_cambio': float(data['tipo_cambio']),
        'tc_estimado': data['tc_estimado'],
        'transferencias_internas_clp': float(round(data['transferencias_internas_clp'], 0)),
        'transferencias_internas_count': data['transferencias_internas_count'],
        'movimientos_count': data['movimientos_count'],
    }


def get_detalle_saldo_cuenta_paginado(cuenta_id, page=1, page_size=20):
    from .models import MovimientoDiario, CuentaFinanciera

    cuenta = CuentaFinanciera.objects.get(pk=cuenta_id, activa=True)
    resumen = _resumen_detalle_saldo_cuenta(cuenta)

    page = max(int(page or 1), 1)
    page_size = max(1, min(int(page_size or 20), 100))

    movs = (
        MovimientoDiario.objects
        .filter(cuenta_financiera=cuenta)
        .order_by('-fecha', '-creado_en')
    )
    total = movs.count()
    start = (page - 1) * page_size
    end = start + page_size
    items = [_serializar_movimiento_detalle_cuenta(m) for m in movs[start:end]]

    return {
        **resumen,
        'page': page,
        'page_size': page_size,
        'pages': (total + page_size - 1) // page_size,
        'movimientos_mostrados': len(items),
        'movimientos': items,
    }


def get_detalle_saldos_cuentas():
    """
    Resumen por cuenta para dashboard.
    Incluye transferencias internas porque este bloque explica saldos financieros,
    no resultado operacional.
    """
    from .models import CuentaFinanciera

    detalle = [_resumen_detalle_saldo_cuenta(cuenta) for cuenta in CuentaFinanciera.objects.filter(activa=True)]
    detalle.sort(key=lambda x: abs(x['saldo_final_clp']), reverse=True)
    return detalle


# ─────────────────────────────────────────────────────────────────────────────
# Saldo actual consolidado
# ─────────────────────────────────────────────────────────────────────────────

def get_saldo_actual():
    """
    Saldo financiero total consolidado en CLP.

    Regla ERP:
      - Incluye movimientos con cuenta financiera, incluyendo transferencias internas.
      - Los movimientos sin cuenta se mantienen como legacy.
      - Este saldo NO es utilidad; la utilidad se calcula con _qs_operacional().
    """
    from .models import MovimientoDiario, ConfiguracionEmpresa, CuentaFinanciera

    config = ConfiguracionEmpresa.get()

    movs_sin_cuenta = MovimientoDiario.objects.filter(cuenta_financiera__isnull=True)
    ing_sc = sum((_monto_clp_robusto(m) for m in movs_sin_cuenta.filter(tipo__in=_TIPOS_INGRESO)), Decimal('0'))
    egr_sc = sum((_monto_clp_robusto(m) for m in movs_sin_cuenta.exclude(tipo__in=_TIPOS_INGRESO)), Decimal('0'))
    saldo_legacy = Decimal(str(config.saldo_inicial_caja or 0)) + Decimal(str(config.saldo_inicial_banco or 0)) + ing_sc - egr_sc

    saldo_cuentas = Decimal('0')
    for cuenta in CuentaFinanciera.objects.filter(activa=True):
        saldo_cuentas += _calcular_saldo_cuenta(cuenta)['saldo_final_clp']

    return saldo_legacy + saldo_cuentas


def get_saldo_por_cuenta():
    """
    Saldos actuales por cuenta financiera.

    Regla ERP:
      - Incluye transferencias internas para cuadrar Banco Chile ↔ Global66.
      - Devuelve valores JSON-safe para vistas y APIs.
    """
    from .models import CuentaFinanciera

    resultado = []
    for cuenta in CuentaFinanciera.objects.filter(activa=True):
        resumen = _resumen_detalle_saldo_cuenta(cuenta)
        resultado.append({
            'cuenta_id': resumen['cuenta_id'],
            'id': resumen['cuenta_id'],
            'nombre': resumen['nombre'],
            'institucion': resumen['institucion'],
            'moneda': resumen['moneda'],
            'saldo_inicial_orig': resumen['saldo_inicial_orig'],
            'saldo_inicial_clp': resumen['saldo_inicial_clp'],
            'ingresos_orig': resumen['ingresos_orig'],
            'egresos_orig': resumen['egresos_orig'],
            'ingresos_clp': resumen['ingresos_clp'],
            'egresos_clp': resumen['egresos_clp'],
            'saldo': resumen['saldo'],                 # saldo en moneda de la cuenta
            'saldo_clp': resumen['saldo_clp'],         # saldo equivalente CLP
            'saldo_final_orig': resumen['saldo_final_orig'],
            'saldo_final_clp': resumen['saldo_final_clp'],
            'tipo_cambio': resumen['tipo_cambio'],
            'tc_estimado': resumen['tc_estimado'],
            'transferencias_internas_clp': resumen['transferencias_internas_clp'],
            'transferencias_internas_count': resumen['transferencias_internas_count'],
            'movimientos_count': resumen['movimientos_count'],
        })

    return resultado
