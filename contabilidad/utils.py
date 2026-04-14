"""
Utilidades financieras para KPIs y métricas de salud empresarial.
Los cálculos excluyen transferencias internas y conversiones de divisa
para no distorsionar el estado de resultados.
"""
from decimal import Decimal
from datetime import date, timedelta
from django.db.models import Sum, Q
import calendar


# Tipos que representan ingresos reales en el campo 'tipo' (legado)
_TIPOS_INGRESO = [
    'ingreso_caja', 'ingreso_banco', 'suma_boletas',
    'suma_facturas_emitidas', 'prestamo_recibido', 'otro_ingreso'
]

# Filtro base que excluye movimientos neutros (no afectan P&L)
def _qs_operacional(qs):
    """Excluye transferencias internas y conversiones de divisa del queryset."""
    return qs.filter(
        es_transferencia_interna=False,
    ).exclude(
        categoria_normalizada__in=['transferencia_interna', 'conversion_divisa']
    )


def get_resumen_periodo(fecha_desde, fecha_hasta):
    from .models import MovimientoDiario

    movs = _qs_operacional(
        MovimientoDiario.objects.filter(fecha__gte=fecha_desde, fecha__lte=fecha_hasta)
    )

    total_ingresos = movs.filter(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
    total_egresos = movs.exclude(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')

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

    margen_bruto = (utilidad_bruta / ventas * 100) if ventas > 0 else Decimal('0')
    margen_operacional = (utilidad_operacional / ventas * 100) if ventas > 0 else Decimal('0')
    margen_neto = (resultado_neto / (ventas + intereses + aportes_socio) * 100) \
        if (ventas + intereses + aportes_socio) > 0 else Decimal('0')

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
        'utilidad_bruta': utilidad_bruta,
        'utilidad_operacional': utilidad_operacional,
        'resultado_neto': resultado_neto,
        'margen_bruto': round(margen_bruto, 1),
        'margen_operacional': round(margen_operacional, 1),
        'margen_neto': round(margen_neto, 1),
    }


def get_flujo_mensual(anio, meses=12):
    from .models import MovimientoDiario

    resultado = []
    for mes in range(1, meses + 1):
        movs = _qs_operacional(
            MovimientoDiario.objects.filter(fecha__year=anio, fecha__month=mes)
        )
        ingresos = movs.filter(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
        egresos = movs.exclude(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
        resultado.append({
            'mes': mes,
            'mes_nombre': calendar.month_abbr[mes],
            'ingresos': int(ingresos),
            'egresos': int(egresos),
            'resultado': int(ingresos - egresos),
        })
    return resultado


def get_ventas_por_dia(fecha_desde, fecha_hasta):
    from .models import MovimientoDiario

    tipos_venta = ['suma_boletas', 'suma_facturas_emitidas', 'ingreso_caja', 'ingreso_banco', 'otro_ingreso']
    data = (_qs_operacional(
        MovimientoDiario.objects.filter(fecha__gte=fecha_desde, fecha__lte=fecha_hasta)
    ).filter(tipo__in=tipos_venta)
     .values('fecha')
     .annotate(total=Sum('monto'))
     .order_by('fecha'))

    return [{'fecha': str(d['fecha']), 'total': int(d['total'])} for d in data]


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
        MovimientoDiario.objects.filter(fecha__gte=fecha_desde, fecha__lte=fecha_hasta)
    )

    # Por categoría normalizada
    for cat, label in CATEGORIAS_GASTOS.items():
        total = movs.filter(categoria_normalizada=cat).aggregate(t=Sum('monto'))['t'] or Decimal('0')
        if total > 0:
            resultado.append({'categoria': label, 'total': int(total)})

    # Fallback: tipos legacy sin categoría normalizada
    tipos_egreso_legacy = {
        'suma_facturas_recibidas': 'Compras',
        'remuneracion': 'Remuneraciones',
        'impuesto': 'Impuestos',
        'egreso_caja': 'Gastos Caja',
        'egreso_banco': 'Gastos Banco',
        'otro_egreso': 'Otros Gastos',
    }
    for tipo, label in tipos_egreso_legacy.items():
        total = movs.filter(tipo=tipo, categoria_normalizada='sin_clasificar').aggregate(
            t=Sum('monto'))['t'] or Decimal('0')
        if total > 0:
            resultado.append({'categoria': label, 'total': int(total)})

    return sorted(resultado, key=lambda x: x['total'], reverse=True)


def get_kpis_salud(fecha_desde, fecha_hasta):
    resumen = get_resumen_periodo(fecha_desde, fecha_hasta)
    ventas = resumen['ventas']
    resultado = resumen['resultado_neto']
    costos = resumen['costos']
    remuneraciones = resumen['remuneraciones']
    total_egresos = resumen['total_egresos']

    kpis = []

    # 1. Resultado del período
    if resultado > 0:
        estado, mensaje = 'verde', 'La empresa está generando ganancias'
    elif resultado == 0:
        estado, mensaje = 'amarillo', 'La empresa está en punto de equilibrio'
    else:
        estado, mensaje = 'rojo', 'La empresa está perdiendo dinero'
    kpis.append({'nombre': 'Resultado del Período', 'valor': f"${int(resultado):,}".replace(',', '.'),
                 'estado': estado, 'mensaje': mensaje, 'icono': '💰'})

    # 2. Margen bruto
    mb = float(resumen['margen_bruto'])
    if mb >= 40:
        estado, mensaje = 'verde', 'Margen saludable sobre el 40%'
    elif mb >= 20:
        estado, mensaje = 'amarillo', 'Margen aceptable, revisar costos'
    else:
        estado, mensaje = 'rojo', 'Margen crítico, costos muy altos'
    kpis.append({'nombre': 'Margen Bruto', 'valor': f"{mb:.1f}%",
                 'estado': estado, 'mensaje': mensaje, 'icono': '📊'})

    # 3. Remuneraciones / Ventas
    if ventas > 0:
        peso_rem = float(remuneraciones / ventas * 100)
        if peso_rem <= 30:
            estado, mensaje = 'verde', 'Carga laboral controlada'
        elif peso_rem <= 50:
            estado, mensaje = 'amarillo', 'Carga laboral elevada'
        else:
            estado, mensaje = 'rojo', 'Remuneraciones consumen más del 50% de ventas'
        kpis.append({'nombre': 'Remuneraciones / Ventas', 'valor': f"{peso_rem:.1f}%",
                     'estado': estado, 'mensaje': mensaje, 'icono': '👥'})

    # 4. Cobertura de gastos
    if total_egresos > 0:
        cobertura = float(ventas / total_egresos)
        if cobertura >= 1.2:
            estado, mensaje = 'verde', 'Las ventas cubren holgadamente los gastos'
        elif cobertura >= 1.0:
            estado, mensaje = 'amarillo', 'Las ventas apenas cubren los gastos'
        else:
            estado, mensaje = 'rojo', 'Las ventas no alcanzan a cubrir los gastos'
        kpis.append({'nombre': 'Cobertura de Gastos', 'valor': f"{cobertura:.2f}x",
                     'estado': estado, 'mensaje': mensaje, 'icono': '🛡️'})

    # 5. Punto de equilibrio
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


def calcular_iva(monto_bruto):
    TASA_IVA = Decimal('0.19')
    neto = round(monto_bruto / (1 + TASA_IVA))
    iva = monto_bruto - neto
    return {'neto': neto, 'iva': iva, 'bruto': monto_bruto}


def _get_tipo_cambio_vigente(moneda: str) -> Decimal:
    """
    Retorna el tipo de cambio más reciente registrado en movimientos
    para la moneda dada respecto a CLP.
    Si no hay registros, usa un valor de respaldo conservador.
    Esto evita llamadas a APIs externas y mantiene coherencia con los
    datos reales de la empresa.
    """
    if moneda == 'CLP':
        return Decimal('1')

    from .models import MovimientoDiario
    # Busca el último movimiento con tipo_cambio registrado para esa moneda
    ultimo = (MovimientoDiario.objects
              .filter(moneda=moneda, tipo_cambio__isnull=False)
              .order_by('-fecha', '-creado_en')
              .values('tipo_cambio')
              .first())

    if ultimo and ultimo['tipo_cambio']:
        return Decimal(str(ultimo['tipo_cambio']))

    # Fallback si nunca se ha registrado tipo de cambio para esa moneda
    FALLBACKS = {
        'USD': Decimal('950'),
        'EUR': Decimal('1030'),
    }
    return FALLBACKS.get(moneda, Decimal('1'))


def get_saldo_actual():
    """
    Saldo consolidado en CLP considerando todas las cuentas.
    - Cuentas CLP: saldo en CLP directamente.
    - Cuentas USD/EUR: saldo en moneda original × tipo de cambio vigente.
    - Incluye saldo_inicial de ConfiguracionEmpresa para cuentas sin CuentaFinanciera.
    """
    from .models import MovimientoDiario, ConfiguracionEmpresa, CuentaFinanciera

    config = ConfiguracionEmpresa.get()

    # Movimientos sin cuenta financiera asignada (legado / ingreso manual)
    movs_sin_cuenta = MovimientoDiario.objects.filter(cuenta_financiera__isnull=True)
    ing_sc = movs_sin_cuenta.filter(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
    egr_sc = movs_sin_cuenta.exclude(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
    saldo_legacy = config.saldo_inicial_caja + config.saldo_inicial_banco + ing_sc - egr_sc

    # Movimientos con cuenta financiera: calculamos saldo por cuenta en su moneda,
    # luego convertimos a CLP para consolidar
    saldo_cuentas_clp = Decimal('0')
    cuentas = CuentaFinanciera.objects.filter(activa=True)
    for cuenta in cuentas:
        movs = MovimientoDiario.objects.filter(cuenta_financiera=cuenta)
        # Para cuentas en moneda extranjera, usamos monto_moneda_orig cuando está disponible
        if cuenta.moneda == 'CLP':
            ingresos = movs.filter(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
            egresos  = movs.exclude(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
            saldo_moneda = cuenta.saldo_inicial + ingresos - egresos
            saldo_cuentas_clp += saldo_moneda
        else:
            # Moneda extranjera: calculamos saldo en moneda original
            ingresos_orig = (movs.filter(tipo__in=_TIPOS_INGRESO, monto_moneda_orig__isnull=False)
                             .aggregate(t=Sum('monto_moneda_orig'))['t'] or Decimal('0'))
            egresos_orig  = (movs.exclude(tipo__in=_TIPOS_INGRESO).filter(monto_moneda_orig__isnull=False)
                             .aggregate(t=Sum('monto_moneda_orig'))['t'] or Decimal('0'))
            # Para movimientos sin monto_moneda_orig (ingresados manualmente), usamos monto en CLP
            ingresos_clp_fallback = (movs.filter(tipo__in=_TIPOS_INGRESO, monto_moneda_orig__isnull=True)
                                     .aggregate(t=Sum('monto'))['t'] or Decimal('0'))
            egresos_clp_fallback  = (movs.exclude(tipo__in=_TIPOS_INGRESO).filter(monto_moneda_orig__isnull=True)
                                     .aggregate(t=Sum('monto'))['t'] or Decimal('0'))
            saldo_moneda_orig = cuenta.saldo_inicial + ingresos_orig - egresos_orig
            tc = _get_tipo_cambio_vigente(cuenta.moneda)
            saldo_cuentas_clp += saldo_moneda_orig * tc + ingresos_clp_fallback - egresos_clp_fallback

    return saldo_legacy + saldo_cuentas_clp


def get_saldo_por_cuenta():
    """
    Retorna saldo por cuenta financiera con:
    - saldo en moneda original de la cuenta
    - saldo equivalente en CLP (para consolidación)
    - tipo de cambio usado
    """
    from .models import MovimientoDiario, CuentaFinanciera

    cuentas = CuentaFinanciera.objects.filter(activa=True)
    resultado = []

    for cuenta in cuentas:
        movs = MovimientoDiario.objects.filter(cuenta_financiera=cuenta)

        if cuenta.moneda == 'CLP':
            ingresos = movs.filter(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
            egresos  = movs.exclude(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
            saldo_orig = cuenta.saldo_inicial + ingresos - egresos
            saldo_clp  = saldo_orig
            tc = Decimal('1')
        else:
            # Saldo en moneda original
            ingresos_orig = (movs.filter(tipo__in=_TIPOS_INGRESO, monto_moneda_orig__isnull=False)
                             .aggregate(t=Sum('monto_moneda_orig'))['t'] or Decimal('0'))
            egresos_orig  = (movs.exclude(tipo__in=_TIPOS_INGRESO).filter(monto_moneda_orig__isnull=False)
                             .aggregate(t=Sum('monto_moneda_orig'))['t'] or Decimal('0'))
            saldo_orig = cuenta.saldo_inicial + ingresos_orig - egresos_orig

            # Convertir a CLP con tipo de cambio vigente
            tc = _get_tipo_cambio_vigente(cuenta.moneda)
            # Sumar también movimientos sin monto_moneda_orig (ya estaban en CLP)
            ingresos_clp_fb = (movs.filter(tipo__in=_TIPOS_INGRESO, monto_moneda_orig__isnull=True)
                               .aggregate(t=Sum('monto'))['t'] or Decimal('0'))
            egresos_clp_fb  = (movs.exclude(tipo__in=_TIPOS_INGRESO).filter(monto_moneda_orig__isnull=True)
                               .aggregate(t=Sum('monto'))['t'] or Decimal('0'))
            saldo_clp = saldo_orig * tc + ingresos_clp_fb - egresos_clp_fb

        # Indicar si el tipo de cambio es estimado (sin movimientos reales registrados)
        tc_es_estimado = (cuenta.moneda != 'CLP' and
                          not movs.filter(tipo_cambio__isnull=False).exists())

        resultado.append({
            'cuenta_id':       str(cuenta.pk),
            'nombre':          cuenta.nombre,
            'institucion':     cuenta.institucion,
            'moneda':          cuenta.moneda,
            'saldo':           float(round(saldo_orig, 2)),          # en moneda original
            'saldo_clp':       float(round(saldo_clp, 0)),           # equivalente en CLP
            'tipo_cambio':     float(tc),
            'tc_estimado':     tc_es_estimado,                       # True = TC sin movimientos reales
        })

    return resultado