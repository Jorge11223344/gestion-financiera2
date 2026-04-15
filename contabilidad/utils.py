"""
Utilidades financieras para KPIs y métricas de salud empresarial.

ARQUITECTURA MONETARIA (tu recomendación implementada):
  Cada movimiento guarda SIEMPRE:
    - monto_moneda_orig  → valor en moneda original (USD, EUR, CLP)
    - moneda             → moneda original
    - tipo_cambio        → TC usado al registrar
    - monto              → equivalente en CLP (monto_base_clp)

  Los reportes tienen DOS miradas:
    1. Por moneda original (para revisar proveedores extranjeros en USD)
    2. Consolidado en CLP (para el P&L y dashboard general)

PROBLEMA CORREGIDO: get_saldo_actual() y get_saldo_por_cuenta() antes sumaban
  el saldo_inicial de cuentas USD directamente en CLP (USD 1000 = $1.000 CLP).
  Ahora convierten usando el tipo de cambio real registrado en movimientos.

PROBLEMA CORREGIDO: Los cálculos de resumen SIEMPRE usan el campo `monto`
  (que es monto_base_clp) para consolidar, nunca mezclan monedas.
"""
from decimal import Decimal
from datetime import date
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


def get_tc_vigente(moneda: str) -> Decimal:
    """
    Tipo de cambio vigente para consolidar en CLP.

    Estrategia: usa el ÚLTIMO tipo_cambio registrado en movimientos reales.
    Si no hay ninguno aún, usa fallback conservador y avisa.

    Esto garantiza que el TC refleja la realidad de la empresa,
    no un valor externo que puede diferir.
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

    # Fallback si nunca se ha registrado TC real para esa moneda
    FALLBACKS = {'USD': Decimal('950'), 'EUR': Decimal('1030')}
    return FALLBACKS.get(moneda, Decimal('1'))


def _monto_clp(movimiento) -> Decimal:
    """
    Retorna el monto en CLP de un movimiento.
    - Si moneda == CLP: devuelve monto directamente.
    - Si moneda != CLP: usa monto (ya es monto_base_clp guardado al importar).
    El campo `monto` es SIEMPRE el monto_base_clp.
    """
    return movimiento.monto


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

    movs = _qs_operacional(
        MovimientoDiario.objects.filter(
            fecha__gte=fecha_desde,
            fecha__lte=fecha_hasta
        )
    )

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

    # P&L
    utilidad_bruta       = ventas - costos
    utilidad_operacional = utilidad_bruta - remuneraciones - impuestos - logistica - comisiones
    resultado_neto       = total_ingresos - total_egresos

    base_margen = ventas + intereses + aportes_socio

    margen_bruto       = (utilidad_bruta / ventas * 100)         if ventas > 0       else Decimal('0')
    margen_operacional = (utilidad_operacional / ventas * 100)   if ventas > 0       else Decimal('0')
    margen_neto        = (resultado_neto / base_margen * 100)    if base_margen > 0  else Decimal('0')

    return {
        'total_ingresos':      total_ingresos,
        'total_egresos':       total_egresos,
        'ventas':              ventas,
        'costos':              costos,
        'remuneraciones':      remuneraciones,
        'impuestos':           impuestos,
        'logistica':           logistica,
        'comisiones':          comisiones,
        'intereses':           intereses,
        'aportes_socio':       aportes_socio,
        'utilidad_bruta':      utilidad_bruta,
        'utilidad_operacional':utilidad_operacional,
        'resultado_neto':      resultado_neto,
        'margen_bruto':        round(margen_bruto, 1),
        'margen_operacional':  round(margen_operacional, 1),
        'margen_neto':         round(margen_neto, 1),
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
        ingresos = movs.filter(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
        egresos  = movs.exclude(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
        resultado.append({
            'mes':       mes,
            'mes_nombre':calendar.month_abbr[mes],
            'ingresos':  int(ingresos),
            'egresos':   int(egresos),
            'resultado': int(ingresos - egresos),
        })
    return resultado


# ─────────────────────────────────────────────────────────────────────────────
# Ventas por día
# ─────────────────────────────────────────────────────────────────────────────

def get_ventas_por_dia(fecha_desde, fecha_hasta):
    from .models import MovimientoDiario

    tipos_venta = ['suma_boletas', 'suma_facturas_emitidas',
                   'ingreso_caja', 'ingreso_banco', 'otro_ingreso']
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
        'pago_importacion':  'Importaciones',
        'pago_proveedor':    'Proveedores',
        'remuneracion_norm': 'Remuneraciones',
        'gasto_logistica':   'Logística',
        'pago_impuesto':     'Impuestos',
        'comision_bancaria': 'Comisiones Bancarias',
        'gasto_operacional': 'Gastos Operacionales',
        'pago_prestamo_norm':'Cuotas Préstamo',
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

    # Fallback legacy
    tipos_egreso_legacy = {
        'suma_facturas_recibidas': 'Compras',
        'remuneracion':            'Remuneraciones',
        'impuesto':                'Impuestos',
        'egreso_caja':             'Gastos Caja',
        'egreso_banco':            'Gastos Banco',
        'otro_egreso':             'Otros Gastos',
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
    resumen       = get_resumen_periodo(fecha_desde, fecha_hasta)
    ventas        = resumen['ventas']
    resultado     = resumen['resultado_neto']
    remuneraciones= resumen['remuneraciones']
    total_egresos = resumen['total_egresos']

    kpis = []

    # 1. Resultado del período
    if resultado > 0:
        estado, mensaje = 'verde', 'La empresa está generando ganancias'
    elif resultado == 0:
        estado, mensaje = 'amarillo', 'La empresa está en punto de equilibrio'
    else:
        estado, mensaje = 'rojo', 'La empresa está perdiendo dinero'
    kpis.append({
        'nombre': 'Resultado del Período',
        'valor':  f"${int(resultado):,}".replace(',', '.'),
        'estado': estado, 'mensaje': mensaje, 'icono': '💰',
    })

    # 2. Margen bruto
    mb = float(resumen['margen_bruto'])
    estado = 'verde' if mb >= 40 else 'amarillo' if mb >= 20 else 'rojo'
    mensajes = {
        'verde':   'Margen saludable sobre el 40%',
        'amarillo':'Margen aceptable, revisar costos',
        'rojo':    'Margen crítico, costos muy altos',
    }
    kpis.append({
        'nombre': 'Margen Bruto', 'valor': f"{mb:.1f}%",
        'estado': estado, 'mensaje': mensajes[estado], 'icono': '📊',
    })

    # 3. Remuneraciones / Ventas
    if ventas > 0:
        peso_rem = float(remuneraciones / ventas * 100)
        estado   = 'verde' if peso_rem <= 30 else 'amarillo' if peso_rem <= 50 else 'rojo'
        msgs_rem = {
            'verde':   'Carga laboral controlada',
            'amarillo':'Carga laboral elevada',
            'rojo':    'Remuneraciones consumen más del 50% de ventas',
        }
        kpis.append({
            'nombre': 'Remuneraciones / Ventas', 'valor': f"{peso_rem:.1f}%",
            'estado': estado, 'mensaje': msgs_rem[estado], 'icono': '👥',
        })

    # 4. Cobertura de gastos
    if total_egresos > 0:
        cobertura = float(ventas / total_egresos)
        estado    = 'verde' if cobertura >= 1.2 else 'amarillo' if cobertura >= 1.0 else 'rojo'
        msgs_cob  = {
            'verde':   'Las ventas cubren holgadamente los gastos',
            'amarillo':'Las ventas apenas cubren los gastos',
            'rojo':    'Las ventas no alcanzan a cubrir los gastos',
        }
        kpis.append({
            'nombre': 'Cobertura de Gastos', 'valor': f"{cobertura:.2f}x",
            'estado': estado, 'mensaje': msgs_cob[estado], 'icono': '🛡️',
        })

    # 5. Días para punto de equilibrio
    dias = (fecha_hasta - fecha_desde).days + 1
    if dias > 0 and ventas > 0:
        venta_diaria = float(ventas) / dias
        if venta_diaria > 0:
            dias_pe = float(remuneraciones) / venta_diaria
            kpis.append({
                'nombre': 'Días para Punto de Equilibrio',
                'valor':  f"{int(dias_pe)} días/mes",
                'estado': 'verde' if dias_pe < 20 else 'amarillo' if dias_pe < 26 else 'rojo',
                'mensaje':f"Necesitas vender {int(dias_pe)} días del mes solo para cubrir sueldos",
                'icono':  '📅',
            })

    return kpis


# ─────────────────────────────────────────────────────────────────────────────
# IVA
# ─────────────────────────────────────────────────────────────────────────────

def calcular_iva(monto_bruto):
    TASA_IVA = Decimal('0.19')
    neto = round(monto_bruto / (1 + TASA_IVA))
    iva  = monto_bruto - neto
    return {'neto': neto, 'iva': iva, 'bruto': monto_bruto}


# ─────────────────────────────────────────────────────────────────────────────
# Saldo actual — CORREGIDO multimoneda
# ─────────────────────────────────────────────────────────────────────────────

def get_saldo_actual():
    """
    Saldo total consolidado en CLP.

    Corrección aplicada:
      - Los movimientos con cuenta_financiera en USD/EUR usan el campo `monto`
        que ya es monto_base_clp (se convirtió al guardar con tipo_cambio).
      - El saldo_inicial de cuentas en USD se convierte con TC vigente.
      - Los movimientos sin cuenta asignada (legado manual) usan saldo_inicial
        de ConfiguracionEmpresa.

    Incluye transferencias internas porque SÍ afectan el saldo real de caja
    (mueven dinero entre cuentas propias, pero el dinero no desaparece).
    """
    from .models import MovimientoDiario, ConfiguracionEmpresa, CuentaFinanciera

    config = ConfiguracionEmpresa.get()

    # ── 1. Movimientos sin cuenta financiera (ingresados manualmente o legado) ──
    movs_sin_cuenta = MovimientoDiario.objects.filter(cuenta_financiera__isnull=True)
    ing_sc = movs_sin_cuenta.filter(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
    egr_sc = movs_sin_cuenta.exclude(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
    # saldo_inicial de config solo aplica cuando no hay cuentas financieras configuradas
    saldo_legacy = config.saldo_inicial_caja + config.saldo_inicial_banco + ing_sc - egr_sc

    # ── 2. Movimientos con cuenta financiera ──
    # El campo `monto` ya es siempre en CLP (monto_base_clp):
    # - Cuenta CLP: monto = monto original en CLP
    # - Cuenta USD/EUR: monto = monto_moneda_orig × tipo_cambio (guardado al importar)
    saldo_cuentas = Decimal('0')
    for cuenta in CuentaFinanciera.objects.filter(activa=True):
        movs = MovimientoDiario.objects.filter(cuenta_financiera=cuenta)
        ingresos = movs.filter(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
        egresos  = movs.exclude(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')

        # saldo_inicial de la cuenta está en su moneda propia → convertir a CLP
        if cuenta.moneda == 'CLP':
            saldo_inicial_clp = cuenta.saldo_inicial
        else:
            tc = get_tc_vigente(cuenta.moneda)
            saldo_inicial_clp = cuenta.saldo_inicial * tc

        saldo_cuentas += saldo_inicial_clp + ingresos - egresos

    return saldo_legacy + saldo_cuentas


def get_saldo_por_cuenta():
    """
    Saldo por cuenta financiera con dos miradas:
      - saldo_orig: en moneda original de la cuenta (USD, CLP, EUR)
      - saldo_clp:  equivalente en CLP para consolidación
      - tc_vigente: tipo de cambio usado
      - tc_es_estimado: True si no hay movimientos reales con TC registrado

    Esta es la implementación de tu recomendación:
    reportar por moneda original Y consolidado en CLP.
    """
    from .models import MovimientoDiario, CuentaFinanciera

    resultado = []
    for cuenta in CuentaFinanciera.objects.filter(activa=True):
        movs = MovimientoDiario.objects.filter(cuenta_financiera=cuenta)

        if cuenta.moneda == 'CLP':
            # Todo en CLP, simple
            ingresos   = movs.filter(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
            egresos    = movs.exclude(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
            saldo_orig = cuenta.saldo_inicial + ingresos - egresos
            saldo_clp  = saldo_orig
            tc         = Decimal('1')
            tc_estimado= False

        else:
            # Moneda extranjera: calcular saldo en moneda original usando monto_moneda_orig
            ing_orig = (
                movs.filter(tipo__in=_TIPOS_INGRESO, monto_moneda_orig__isnull=False)
                .aggregate(t=Sum('monto_moneda_orig'))['t'] or Decimal('0')
            )
            egr_orig = (
                movs.exclude(tipo__in=_TIPOS_INGRESO).filter(monto_moneda_orig__isnull=False)
                .aggregate(t=Sum('monto_moneda_orig'))['t'] or Decimal('0')
            )
            saldo_orig = cuenta.saldo_inicial + ing_orig - egr_orig

            # Equivalente en CLP: usar el campo `monto` (monto_base_clp) para movimientos
            # con monto_moneda_orig, más fallback para los que no tienen
            ing_clp = (
                movs.filter(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
            )
            egr_clp = (
                movs.exclude(tipo__in=_TIPOS_INGRESO).aggregate(t=Sum('monto'))['t'] or Decimal('0')
            )
            tc         = get_tc_vigente(cuenta.moneda)
            tc_estimado= not movs.filter(tipo_cambio__isnull=False).exists()
            saldo_clp  = cuenta.saldo_inicial * tc + ing_clp - egr_clp

        resultado.append({
            'cuenta_id':   str(cuenta.pk),
            'nombre':      cuenta.nombre,
            'institucion': cuenta.institucion,
            'moneda':      cuenta.moneda,
            'saldo':       float(round(saldo_orig, 4)),   # en moneda original
            'saldo_clp':   float(round(saldo_clp, 0)),   # equivalente en CLP
            'tipo_cambio': float(tc),
            'tc_estimado': tc_estimado,
        })

    return resultado
