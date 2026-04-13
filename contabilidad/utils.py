"""
Utilidades financieras para calcular KPIs y métricas de salud empresarial.
"""
from decimal import Decimal
from datetime import date, timedelta
from django.db.models import Sum, Count, Q
from django.utils import timezone
import calendar


def get_resumen_periodo(fecha_desde, fecha_hasta):
    """Resumen financiero para un período dado."""
    from .models import MovimientoDiario

    movs = MovimientoDiario.objects.filter(fecha__gte=fecha_desde, fecha__lte=fecha_hasta)

    # Ingresos por tipo
    tipos_ingreso = ['ingreso_caja', 'ingreso_banco', 'suma_boletas',
                     'suma_facturas_emitidas', 'prestamo_recibido', 'otro_ingreso']
    tipos_egreso = ['egreso_caja', 'egreso_banco', 'suma_facturas_recibidas',
                    'remuneracion', 'impuesto', 'pago_prestamo', 'inversion', 'otro_egreso']

    total_ingresos = movs.filter(tipo__in=tipos_ingreso).aggregate(t=Sum('monto'))['t'] or Decimal('0')
    total_egresos = movs.filter(tipo__in=tipos_egreso).aggregate(t=Sum('monto'))['t'] or Decimal('0')

    ventas = movs.filter(tipo__in=['suma_boletas', 'suma_facturas_emitidas']).aggregate(t=Sum('monto'))['t'] or Decimal('0')
    costos = movs.filter(tipo='suma_facturas_recibidas').aggregate(t=Sum('monto'))['t'] or Decimal('0')
    remuneraciones = movs.filter(tipo='remuneracion').aggregate(t=Sum('monto'))['t'] or Decimal('0')
    impuestos = movs.filter(tipo='impuesto').aggregate(t=Sum('monto'))['t'] or Decimal('0')

    utilidad_bruta = ventas - costos
    utilidad_operacional = utilidad_bruta - remuneraciones - impuestos
    resultado_neto = total_ingresos - total_egresos

    margen_bruto = (utilidad_bruta / ventas * 100) if ventas > 0 else Decimal('0')
    margen_operacional = (utilidad_operacional / ventas * 100) if ventas > 0 else Decimal('0')
    margen_neto = (resultado_neto / ventas * 100) if ventas > 0 else Decimal('0')

    return {
        'total_ingresos': total_ingresos,
        'total_egresos': total_egresos,
        'ventas': ventas,
        'costos': costos,
        'remuneraciones': remuneraciones,
        'impuestos': impuestos,
        'utilidad_bruta': utilidad_bruta,
        'utilidad_operacional': utilidad_operacional,
        'resultado_neto': resultado_neto,
        'margen_bruto': round(margen_bruto, 1),
        'margen_operacional': round(margen_operacional, 1),
        'margen_neto': round(margen_neto, 1),
    }


def get_flujo_mensual(anio, meses=12):
    """Flujo de ingresos/egresos mes a mes para el año dado."""
    from .models import MovimientoDiario

    tipos_ingreso = ['ingreso_caja', 'ingreso_banco', 'suma_boletas',
                     'suma_facturas_emitidas', 'prestamo_recibido', 'otro_ingreso']

    resultado = []
    for mes in range(1, meses + 1):
        movs = MovimientoDiario.objects.filter(fecha__year=anio, fecha__month=mes)
        ingresos = movs.filter(tipo__in=tipos_ingreso).aggregate(t=Sum('monto'))['t'] or Decimal('0')
        egresos = movs.exclude(tipo__in=tipos_ingreso).aggregate(t=Sum('monto'))['t'] or Decimal('0')
        resultado.append({
            'mes': mes,
            'mes_nombre': calendar.month_abbr[mes],
            'ingresos': int(ingresos),
            'egresos': int(egresos),
            'resultado': int(ingresos - egresos),
        })
    return resultado


def get_ventas_por_dia(fecha_desde, fecha_hasta):
    """Ventas día a día en el período."""
    from .models import MovimientoDiario
    from django.db.models.functions import TruncDate

    tipos_venta = ['suma_boletas', 'suma_facturas_emitidas', 'ingreso_caja', 'ingreso_banco', 'otro_ingreso']
    data = (MovimientoDiario.objects
            .filter(fecha__gte=fecha_desde, fecha__lte=fecha_hasta, tipo__in=tipos_venta)
            .values('fecha')
            .annotate(total=Sum('monto'))
            .order_by('fecha'))

    return [{'fecha': str(d['fecha']), 'total': int(d['total'])} for d in data]


def get_distribucion_gastos(fecha_desde, fecha_hasta):
    """Distribución de gastos por tipo para gráfico de torta."""
    from .models import MovimientoDiario

    tipos_egreso = {
        'suma_facturas_recibidas': 'Compras/Insumos',
        'remuneracion': 'Remuneraciones',
        'impuesto': 'Impuestos',
        'pago_prestamo': 'Cuotas Préstamo',
        'inversion': 'Inversiones',
        'egreso_caja': 'Gastos Caja',
        'egreso_banco': 'Gastos Banco',
        'otro_egreso': 'Otros Gastos',
    }

    resultado = []
    for tipo, label in tipos_egreso.items():
        total = (MovimientoDiario.objects
                 .filter(fecha__gte=fecha_desde, fecha__lte=fecha_hasta, tipo=tipo)
                 .aggregate(t=Sum('monto'))['t'] or Decimal('0'))
        if total > 0:
            resultado.append({'categoria': label, 'total': int(total)})

    return sorted(resultado, key=lambda x: x['total'], reverse=True)


def get_kpis_salud(fecha_desde, fecha_hasta):
    """
    KPIs de salud financiera con semáforo (verde/amarillo/rojo).
    Pensados para dueños de empresa sin formación financiera.
    """
    resumen = get_resumen_periodo(fecha_desde, fecha_hasta)
    ventas = resumen['ventas']
    resultado = resumen['resultado_neto']
    costos = resumen['costos']
    remuneraciones = resumen['remuneraciones']
    total_egresos = resumen['total_egresos']

    kpis = []

    # 1. Resultado del período
    if resultado > 0:
        estado = 'verde'
        mensaje = 'La empresa está generando ganancias'
    elif resultado == 0:
        estado = 'amarillo'
        mensaje = 'La empresa está en punto de equilibrio'
    else:
        estado = 'rojo'
        mensaje = 'La empresa está perdiendo dinero'
    kpis.append({
        'nombre': 'Resultado del Período',
        'valor': f"${int(resultado):,}".replace(',', '.'),
        'estado': estado,
        'mensaje': mensaje,
        'icono': '💰',
    })

    # 2. Margen bruto
    mb = float(resumen['margen_bruto'])
    if mb >= 40:
        estado = 'verde'
        mensaje = 'Margen saludable sobre el 40%'
    elif mb >= 20:
        estado = 'amarillo'
        mensaje = 'Margen aceptable, revisar costos'
    else:
        estado = 'rojo'
        mensaje = 'Margen crítico, costos muy altos'
    kpis.append({
        'nombre': 'Margen Bruto',
        'valor': f"{mb:.1f}%",
        'estado': estado,
        'mensaje': mensaje,
        'icono': '📊',
    })

    # 3. Peso remuneraciones sobre ventas
    if ventas > 0:
        peso_rem = float(remuneraciones / ventas * 100)
        if peso_rem <= 30:
            estado = 'verde'
            mensaje = 'Carga laboral controlada'
        elif peso_rem <= 50:
            estado = 'amarillo'
            mensaje = 'Carga laboral elevada'
        else:
            estado = 'rojo'
            mensaje = 'Remuneraciones consumen más del 50% de ventas'
        kpis.append({
            'nombre': 'Remuneraciones / Ventas',
            'valor': f"{peso_rem:.1f}%",
            'estado': estado,
            'mensaje': mensaje,
            'icono': '👥',
        })

    # 4. Cobertura de gastos (¿cuántas veces las ventas cubren los egresos?)
    if total_egresos > 0:
        cobertura = float(ventas / total_egresos)
        if cobertura >= 1.2:
            estado = 'verde'
            mensaje = 'Las ventas cubren holgadamente los gastos'
        elif cobertura >= 1.0:
            estado = 'amarillo'
            mensaje = 'Las ventas apenas cubren los gastos'
        else:
            estado = 'rojo'
            mensaje = 'Las ventas no alcanzan a cubrir los gastos'
        kpis.append({
            'nombre': 'Cobertura de Gastos',
            'valor': f"{cobertura:.2f}x",
            'estado': estado,
            'mensaje': mensaje,
            'icono': '🛡️',
        })

    # 5. Punto de equilibrio estimado (mensual)
    dias = (fecha_hasta - fecha_desde).days + 1
    if dias > 0 and ventas > 0:
        venta_diaria = float(ventas) / dias
        egreso_fijo_estimado = float(remuneraciones)  # simplificado
        if venta_diaria > 0:
            dias_pe = egreso_fijo_estimado / venta_diaria
            kpis.append({
                'nombre': 'Días para Punto de Equilibrio',
                'valor': f"{int(dias_pe)} días/mes",
                'estado': 'verde' if dias_pe < 20 else 'amarillo' if dias_pe < 26 else 'rojo',
                'mensaje': f"Necesitas vender {int(dias_pe)} días del mes solo para cubrir sueldos",
                'icono': '📅',
            })

    return kpis


def calcular_iva(monto_bruto):
    """Calcula neto e IVA desde monto bruto (tasa IVA Chile 19%)."""
    TASA_IVA = Decimal('0.19')
    neto = round(monto_bruto / (1 + TASA_IVA))
    iva = monto_bruto - neto
    return {'neto': neto, 'iva': iva, 'bruto': monto_bruto}


def get_saldo_actual():
    """Calcula el saldo de caja+banco acumulado desde el inicio."""
    from .models import MovimientoDiario, ConfiguracionEmpresa

    config = ConfiguracionEmpresa.get()
    saldo_inicial = config.saldo_inicial_caja + config.saldo_inicial_banco

    tipos_ingreso = ['ingreso_caja', 'ingreso_banco', 'suma_boletas',
                     'suma_facturas_emitidas', 'prestamo_recibido', 'otro_ingreso']

    total_ingresos = MovimientoDiario.objects.filter(tipo__in=tipos_ingreso).aggregate(t=Sum('monto'))['t'] or Decimal('0')
    total_egresos = MovimientoDiario.objects.exclude(tipo__in=tipos_ingreso).aggregate(t=Sum('monto'))['t'] or Decimal('0')

    return saldo_inicial + total_ingresos - total_egresos
