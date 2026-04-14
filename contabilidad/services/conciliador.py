"""
Conciliador de movimientos financieros.

Detecta automáticamente transferencias internas entre cuentas propias
y conversiones de divisa, vinculando los movimientos espejo.
"""

from __future__ import annotations
from datetime import timedelta
from decimal import Decimal
from typing import Optional


def _montos_equivalentes(monto_a: Decimal, monto_b: Decimal,
                          tipo_cambio: Optional[Decimal] = None,
                          tolerancia_pct: float = 3.0) -> bool:
    """
    Verifica si dos montos son equivalentes considerando tipo de cambio y tolerancia.
    """
    if monto_a == 0 or monto_b == 0:
        return False

    if tipo_cambio and tipo_cambio > 0:
        # Convertir monto_a a la moneda de monto_b
        monto_a_conv = monto_a / tipo_cambio
        diferencia_pct = abs(monto_a_conv - monto_b) / monto_b * 100
        return diferencia_pct <= tolerancia_pct

    # Misma moneda
    diferencia_pct = abs(monto_a - monto_b) / max(monto_a, monto_b) * 100
    return diferencia_pct <= tolerancia_pct


def detectar_transferencias_internas(dias_tolerancia: int = 2,
                                      tolerancia_monto_pct: float = 3.0) -> dict:
    """
    Busca en la BD movimientos que probablemente sean transferencias internas
    no detectadas aún.

    Casos que detecta:
    1. Conversión de divisa Global66 (CLP ↔ USD)
    2. Envío Global66 → recepción en Banco de Chile
    3. Traspasos entre cuentas propias mismo banco

    Retorna:
        {
            "emparejados": [(mov_a_id, mov_b_id, razon)],
            "guardados": int,
            "errores": [str]
        }
    """
    from ..models import MovimientoDiario

    emparejados = []
    errores = []
    ya_procesados = set()

    # ── Caso 1: Conversión de divisas (par CLP ↔ USD) ────────────────
    conversiones = MovimientoDiario.objects.filter(
        categoria_normalizada='conversion_divisa',
        movimiento_relacionado__isnull=True,
    ).select_related('cuenta_financiera')

    for mov_a in conversiones:
        if str(mov_a.pk) in ya_procesados:
            continue

        fecha_min = mov_a.fecha - timedelta(days=dias_tolerancia)
        fecha_max = mov_a.fecha + timedelta(days=dias_tolerancia)

        # Buscar el movimiento espejo: misma categoría, moneda diferente, fecha cercana
        candidatos = MovimientoDiario.objects.filter(
            categoria_normalizada='conversion_divisa',
            movimiento_relacionado__isnull=True,
            fecha__gte=fecha_min,
            fecha__lte=fecha_max,
        ).exclude(pk=mov_a.pk).exclude(pk__in=ya_procesados)

        # Filtrar por moneda opuesta si tenemos info de cuenta
        if mov_a.cuenta_financiera:
            moneda_a = mov_a.cuenta_financiera.moneda
            candidatos = candidatos.filter(
                cuenta_financiera__moneda__ne=moneda_a
            ) if hasattr(candidatos, 'exclude') else candidatos

        for mov_b in candidatos:
            # Verificar equivalencia de montos con tipo de cambio
            tc = mov_a.tipo_cambio or mov_b.tipo_cambio
            monto_a = mov_a.monto_moneda_orig or mov_a.monto
            monto_b = mov_b.monto_moneda_orig or mov_b.monto

            if _montos_equivalentes(mov_a.monto, mov_b.monto, tc, tolerancia_monto_pct) or \
               _montos_equivalentes(monto_a, monto_b, tc, tolerancia_monto_pct):
                emparejados.append({
                    "mov_a_id": str(mov_a.pk),
                    "mov_b_id": str(mov_b.pk),
                    "tipo": "conversion_divisa",
                    "razon": f"Conversión de divisa: ${mov_a.monto} ↔ ${mov_b.monto}",
                })
                ya_procesados.add(str(mov_a.pk))
                ya_procesados.add(str(mov_b.pk))
                break

    # ── Caso 2: Transferencia interna (mismo monto, fechas cercanas) ──
    transferencias = MovimientoDiario.objects.filter(
        categoria_normalizada='transferencia_interna',
        movimiento_relacionado__isnull=True,
    )

    for mov_a in transferencias:
        if str(mov_a.pk) in ya_procesados:
            continue

        fecha_min = mov_a.fecha - timedelta(days=dias_tolerancia)
        fecha_max = mov_a.fecha + timedelta(days=dias_tolerancia)

        candidatos = MovimientoDiario.objects.filter(
            fecha__gte=fecha_min,
            fecha__lte=fecha_max,
            movimiento_relacionado__isnull=True,
        ).filter(
            categoria_normalizada__in=['transferencia_interna', 'aporte_socio', 'ingreso_banco']
        ).exclude(pk=mov_a.pk).exclude(pk__in=ya_procesados)

        for mov_b in candidatos:
            if _montos_equivalentes(mov_a.monto, mov_b.monto, tolerancia_pct=tolerancia_monto_pct):
                # Un lado es egreso, otro es ingreso
                if mov_a.es_ingreso != mov_b.es_ingreso:
                    emparejados.append({
                        "mov_a_id": str(mov_a.pk),
                        "mov_b_id": str(mov_b.pk),
                        "tipo": "transferencia_interna",
                        "razon": f"Montos equivalentes en fechas cercanas: ${mov_a.monto} ≈ ${mov_b.monto}",
                    })
                    ya_procesados.add(str(mov_a.pk))
                    ya_procesados.add(str(mov_b.pk))
                    break

    # ── Guardar emparejamientos en BD ─────────────────────────────────
    guardados = 0
    for par in emparejados:
        try:
            mov_a = MovimientoDiario.objects.get(pk=par["mov_a_id"])
            mov_b = MovimientoDiario.objects.get(pk=par["mov_b_id"])

            mov_a.movimiento_relacionado = mov_b
            mov_a.es_transferencia_interna = True
            mov_a.save(update_fields=['movimiento_relacionado', 'es_transferencia_interna'])

            mov_b.movimiento_relacionado = mov_a
            mov_b.es_transferencia_interna = True
            mov_b.save(update_fields=['movimiento_relacionado', 'es_transferencia_interna'])

            guardados += 1
        except Exception as e:
            errores.append(f"Error emparejando {par['mov_a_id']}: {e}")

    return {
        "emparejados": emparejados,
        "guardados": guardados,
        "errores": errores,
    }


def sugerir_emparejamientos(dias_tolerancia: int = 3,
                             tolerancia_monto_pct: float = 3.0) -> list:
    """
    Retorna sugerencias de emparejamiento para revisión manual,
    SIN guardar nada en la BD.
    """
    from ..models import MovimientoDiario

    sugerencias = []
    ya_vistos = set()

    # Movimientos sin clasificar o con categoría que podría ser interna
    candidatos_egreso = MovimientoDiario.objects.filter(
        es_transferencia_interna=False,
        movimiento_relacionado__isnull=True,
    ).filter(
        categoria_normalizada__in=[
            'sin_clasificar', 'transferencia_interna', 'conversion_divisa', 'egreso_banco'
        ]
    ).order_by('-fecha')[:200]

    for mov_e in candidatos_egreso:
        if str(mov_e.pk) in ya_vistos:
            continue

        fecha_min = mov_e.fecha - timedelta(days=dias_tolerancia)
        fecha_max = mov_e.fecha + timedelta(days=dias_tolerancia)

        posibles = MovimientoDiario.objects.filter(
            fecha__gte=fecha_min,
            fecha__lte=fecha_max,
            es_transferencia_interna=False,
            movimiento_relacionado__isnull=True,
        ).exclude(pk=mov_e.pk).exclude(pk__in=ya_vistos)

        for mov_i in posibles:
            if _montos_equivalentes(mov_e.monto, mov_i.monto, tolerancia_pct=tolerancia_monto_pct):
                if mov_e.es_ingreso != mov_i.es_ingreso:
                    sugerencias.append({
                        "mov_egreso_id": str(mov_e.pk),
                        "mov_egreso_desc": mov_e.descripcion,
                        "mov_egreso_fecha": str(mov_e.fecha),
                        "mov_egreso_monto": float(mov_e.monto),
                        "mov_egreso_cuenta": str(mov_e.cuenta_financiera) if mov_e.cuenta_financiera else "—",
                        "mov_ingreso_id": str(mov_i.pk),
                        "mov_ingreso_desc": mov_i.descripcion,
                        "mov_ingreso_fecha": str(mov_i.fecha),
                        "mov_ingreso_monto": float(mov_i.monto),
                        "mov_ingreso_cuenta": str(mov_i.cuenta_financiera) if mov_i.cuenta_financiera else "—",
                        "diferencia_dias": abs((mov_e.fecha - mov_i.fecha).days),
                        "confianza": "alta" if mov_e.fecha == mov_i.fecha else "media",
                    })
                    ya_vistos.add(str(mov_e.pk))
                    ya_vistos.add(str(mov_i.pk))
                    break

    return sugerencias


def vincular_movimientos(mov_a_id: str, mov_b_id: str) -> dict:
    """Vincula manualmente dos movimientos como transferencia interna."""
    from ..models import MovimientoDiario
    try:
        mov_a = MovimientoDiario.objects.get(pk=mov_a_id)
        mov_b = MovimientoDiario.objects.get(pk=mov_b_id)
        mov_a.movimiento_relacionado = mov_b
        mov_a.es_transferencia_interna = True
        mov_a.categoria_normalizada = 'transferencia_interna'
        mov_a.save(update_fields=['movimiento_relacionado', 'es_transferencia_interna', 'categoria_normalizada'])
        mov_b.movimiento_relacionado = mov_a
        mov_b.es_transferencia_interna = True
        mov_b.categoria_normalizada = 'transferencia_interna'
        mov_b.save(update_fields=['movimiento_relacionado', 'es_transferencia_interna', 'categoria_normalizada'])
        return {"ok": True, "mensaje": "Movimientos vinculados correctamente"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def desvincular_movimiento(mov_id: str) -> dict:
    """Desvincula un movimiento de su par."""
    from ..models import MovimientoDiario
    try:
        mov = MovimientoDiario.objects.get(pk=mov_id)
        if mov.movimiento_relacionado:
            par = mov.movimiento_relacionado
            par.movimiento_relacionado = None
            par.es_transferencia_interna = False
            par.save(update_fields=['movimiento_relacionado', 'es_transferencia_interna'])
        mov.movimiento_relacionado = None
        mov.es_transferencia_interna = False
        mov.save(update_fields=['movimiento_relacionado', 'es_transferencia_interna'])
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}