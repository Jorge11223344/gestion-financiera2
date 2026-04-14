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


def get_saldo_actual():
    from .models import MovimientoDiario, ConfiguracionEmpresa

    config = ConfiguracionEmpresa.get()
    saldo_inicial = config.saldo_inicial_caja + config.saldo_inicial_banco

    # El saldo SÍ incluye transferencias internas (afectan el saldo real de caja)
    total_ingresos = MovimientoDiario.objects.filter(
        tipo__in=_TIPOS_INGRESO
    ).aggregate(t=Sum('monto'))['t'] or Decimal('0')
    total_egresos = MovimientoDiario.objects.exclude(
        tipo__in=_TIPOS_INGRESO
    ).aggregate(t=Sum('monto'))['t'] or Decimal('0')

    return saldo_inicial + total_ingresos - total_egresos


def get_saldo_por_cuenta():
    """Retorna saldo actual desglosado por cuenta financiera."""
    from .models import MovimientoDiario, CuentaFinanciera

    cuentas = CuentaFinanciera.objects.filter(activa=True)
    resultado = []

    for cuenta in cuentas:
        movs = MovimientoDiario.objects.filter(cuenta_financiera=cuenta)
        ingresos = movs.filter(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
        egresos = movs.exclude(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
        saldo = cuenta.saldo_inicial + ingresos - egresos
        resultado.append({
            'cuenta_id': str(cuenta.pk),
            'nombre': cuenta.nombre,
            'institucion': cuenta.institucion,
            'moneda': cuenta.moneda,
            'saldo': float(saldo),
        })

    return resultado