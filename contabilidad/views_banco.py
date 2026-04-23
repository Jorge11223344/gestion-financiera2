"""
Vistas para importación de cartola bancaria.
Flujo:
  1. GET  /api/cuentas-financieras       → lista cuentas para selector
  2. POST /api/cuentas-financieras       → crear cuenta nueva
  3. POST /api/banco/preview             → analiza archivo, devuelve preview
  4. POST /api/banco/confirmar           → guarda movimientos seleccionados
  5. GET  /api/banco/importaciones       → historial de importaciones
  6. POST /api/banco/revertir/<id>       → revierte una importación
  7. GET  /api/revision/pendientes       → movimientos sin clasificar + sugerencias
  8. PATCH /api/movimientos/<id>/clasificar → edición manual de clasificación
"""

import json
import hashlib
from decimal import Decimal

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import MovimientoDiario, CuentaFinanciera, RegistroImportacion
from .importador_banco import parsear_excel, parsear_csv, convertir_a_movimientos
from .services.clasificador import clasificar_movimiento
from .services.conciliador import detectar_transferencias_internas, sugerir_emparejamientos
from .utils import get_saldo_por_cuenta


# ─────────────────────────────────────────────
# Cuentas Financieras
# ─────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET", "POST"])
def cuentas_financieras(request):
    if request.method == "GET":
        cuentas = CuentaFinanciera.objects.filter(activa=True)
        saldos = {str(s.get('cuenta_id') or s.get('id')): s for s in get_saldo_por_cuenta()}
        return JsonResponse({"cuentas": [
            {
                "id": str(c.pk),
                "activa": c.activa,
                "nombre": c.nombre,
                "institucion": c.institucion,
                "tipo_cuenta": c.tipo_cuenta,
                "tipo_cuenta_display": c.get_tipo_cuenta_display(),
                "moneda": c.moneda,
                "moneda_display": c.get_moneda_display(),
                "titular": c.titular,
                "numero_parcial": c.numero_parcial,
                "saldo_inicial": float(c.saldo_inicial),
                # Saldo que se muestra en tarjetas de cuentas.
                # Para CLP debe leer saldo_clp; antes usaba "saldo" y podía no reflejar transferencias internas.
                "saldo_actual": float((saldos.get(str(c.pk)) or {}).get('saldo_clp', 0) or 0),
                "saldo_original": float((saldos.get(str(c.pk)) or {}).get('saldo', 0) or 0),
                "saldo_actual_clp": float((saldos.get(str(c.pk)) or {}).get('saldo_clp', 0) or 0),
                "tipo_cambio": float((saldos.get(str(c.pk)) or {}).get('tipo_cambio', 1) or 1),
                "tc_estimado": bool((saldos.get(str(c.pk)) or {}).get('tc_estimado', False)),
            }
            for c in cuentas
        ]})

    # POST — crear cuenta
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    try:
        cuenta = CuentaFinanciera.objects.create(
            nombre=body.get("nombre", "").strip(),
            institucion=body.get("institucion", "").strip(),
            tipo_cuenta=body.get("tipo_cuenta", "cuenta_corriente"),
            moneda=body.get("moneda", "CLP"),
            titular=body.get("titular", ""),
            numero_parcial=body.get("numero_parcial", ""),
            saldo_inicial=Decimal(str(body.get("saldo_inicial", 0))),
            fecha_saldo_inicial=body.get("fecha_saldo_inicial") or None,
            notas=body.get("notas", ""),
        )
        return JsonResponse({"id": str(cuenta.pk), "nombre": cuenta.nombre}, status=201)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@csrf_exempt
@require_http_methods(["DELETE"])
def cuenta_financiera_detalle(request, cuenta_id):
    try:
        cuenta = CuentaFinanciera.objects.get(pk=cuenta_id)
        cuenta.activa = False
        cuenta.save(update_fields=['activa'])
        return JsonResponse({"ok": True})
    except CuentaFinanciera.DoesNotExist:
        return JsonResponse({"error": "No encontrada"}, status=404)


# ─────────────────────────────────────────────
# Preview de Cartola
# ─────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def preview_cartola(request):
    if "archivo" not in request.FILES:
        return JsonResponse({"error": "No se recibió ningún archivo"}, status=400)

    archivo = request.FILES["archivo"]
    nombre = archivo.name
    contenido = archivo.read()

    # Verificar si ya fue importado (hash SHA256)
    hash_archivo = hashlib.sha256(contenido).hexdigest()
    if RegistroImportacion.objects.filter(hash_archivo=hash_archivo).exists():
        reg = RegistroImportacion.objects.get(hash_archivo=hash_archivo)
        return JsonResponse({
            "error": f"Este archivo ya fue importado el {reg.fecha_importacion.strftime('%d/%m/%Y %H:%M')}. "
                     f"Se importaron {reg.total_importados} movimientos.",
            "ya_importado": True,
        }, status=409)

    nombre_lower = nombre.lower()
    if nombre_lower.endswith((".xlsx", ".xls")):
        resultado = parsear_excel(contenido, nombre)
    elif nombre_lower.endswith(".csv"):
        resultado = parsear_csv(contenido, nombre)
    else:
        return JsonResponse({"error": "Formato no soportado. Usa .xlsx, .xls o .csv"}, status=400)

    if resultado.errores:
        return JsonResponse({
            "error": resultado.errores[0],
            "todos_errores": resultado.errores,
        }, status=422)

    movimientos_propuestos = convertir_a_movimientos(resultado)

    # Obtener cuenta financiera si se envió
    cuenta_id = request.POST.get("cuenta_financiera_id", "")
    cuenta = None
    moneda_cuenta = "CLP"
    if cuenta_id:
        try:
            cuenta = CuentaFinanciera.objects.get(pk=cuenta_id)
            moneda_cuenta = cuenta.moneda
        except CuentaFinanciera.DoesNotExist:
            pass

    # Clasificar y detectar duplicados
    for mov in movimientos_propuestos:
        # Clasificación automática
        clasificacion = clasificar_movimiento(
            descripcion=mov.get("descripcion", ""),
            tipo_banco=mov.get("tipo_banco", ""),
            es_cargo=mov.get("es_cargo", False),
            institucion=cuenta.institucion if cuenta else resultado.banco_detectado,
            moneda=moneda_cuenta,
        )
        mov["categoria_normalizada"] = clasificacion["categoria_normalizada"]
        mov["es_transferencia_interna"] = clasificacion["es_transferencia_interna"]
        mov["clasificacion_confianza"] = clasificacion["confianza"]
        mov["clasificacion_razon"] = clasificacion["razon"]
        mov["tercero"] = clasificacion.get("tercero", "")

        # Detección de duplicados por hash: fecha + monto + referencia
        ref = mov.get("referencia_externa", "")
        existe = MovimientoDiario.objects.filter(
            fecha=mov["fecha"],
            monto=mov["monto"],
            medio_pago="transferencia",
        )
        if ref:
            existe = existe.filter(referencia_externa=ref)
        mov["posible_duplicado"] = existe.exists()
        mov["fecha"] = str(mov["fecha"])
        mov["monto"] = float(mov["monto"])
        if mov.get("monto_moneda_orig") is not None:
            mov["monto_moneda_orig"] = float(mov["monto_moneda_orig"])
        if mov.get("tipo_cambio") is not None:
            mov["tipo_cambio"] = float(mov["tipo_cambio"])
        # tc_estimado ya viene como bool desde convertir_a_movimientos

    # Estadísticas del preview
    movs_reales = [m for m in movimientos_propuestos if not m.get("es_transferencia_interna")]
    total_ingresos = sum(
        m["monto"] for m in movs_reales
        if m["tipo"] in ["ingreso_banco", "ingreso_caja", "otro_ingreso", "prestamo_recibido"]
    )
    total_egresos = sum(
        m["monto"] for m in movs_reales
        if m["tipo"] not in ["ingreso_banco", "ingreso_caja", "otro_ingreso", "prestamo_recibido"]
    )
    duplicados = sum(1 for m in movimientos_propuestos if m["posible_duplicado"])
    transferencias_internas = sum(1 for m in movimientos_propuestos if m.get("es_transferencia_interna"))
    tc_pendientes = sum(1 for m in movimientos_propuestos if m.get("tc_estimado"))

    return JsonResponse({
        "banco_detectado": resultado.banco_detectado,
        "hash_archivo": hash_archivo,
        "moneda_cuenta": moneda_cuenta,
        "total_filas_archivo": resultado.total_filas_archivo,
        "total_filas_validas": resultado.total_filas_validas,
        "advertencias": resultado.advertencias,
        "movimientos": movimientos_propuestos,
        "estadisticas": {
            "total_ingresos": total_ingresos,
            "total_egresos": total_egresos,
            "resultado": total_ingresos - total_egresos,
            "posibles_duplicados": duplicados,
            "transferencias_internas": transferencias_internas,
            "tc_pendientes": tc_pendientes,
        },
        "aviso_tc": (
            f"⚠️ {tc_pendientes} movimiento(s) en USD no tienen tipo de cambio en la cartola "
            f"(comisiones, envíos, intereses). Puedes editarlos después de importar desde "
            f"Historial → movimiento → editar TC."
        ) if tc_pendientes > 0 else None,
    })


# ─────────────────────────────────────────────
# Confirmar Importación
# ─────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def confirmar_importacion(request):
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    movimientos = body.get("movimientos", [])
    if not movimientos:
        return JsonResponse({"error": "No hay movimientos para importar"}, status=400)

    cuenta_id = body.get("cuenta_financiera_id", "")
    hash_archivo = body.get("hash_archivo", "")
    nombre_archivo = body.get("nombre_archivo", "archivo")
    banco_detectado = body.get("banco_detectado", "")
    advertencias = body.get("advertencias", [])

    cuenta = None
    moneda_cuenta = "CLP"
    if cuenta_id:
        try:
            cuenta = CuentaFinanciera.objects.get(pk=cuenta_id)
            moneda_cuenta = cuenta.moneda
        except CuentaFinanciera.DoesNotExist:
            pass

    # Crear registro de importación
    registro = None
    if hash_archivo:
        try:
            registro = RegistroImportacion.objects.create(
                cuenta_financiera=cuenta,
                nombre_archivo=nombre_archivo,
                banco_detectado=banco_detectado,
                total_filas_archivo=body.get("total_filas_archivo", 0),
                hash_archivo=hash_archivo,
                advertencias=advertencias,
            )
        except Exception:
            pass  # Si ya existe el hash, continuar sin registro

    creados = 0
    duplicados = 0
    errores = []

    for mov in movimientos:
        if not mov.get("incluir", True):
            duplicados += 1
            continue

        try:
            # Desde el importador, mov["monto"] ya viene SIEMPRE en CLP.
            monto_clp = Decimal(str(mov["monto"]))
            moneda_mov = mov.get("moneda") or moneda_cuenta or "CLP"
            monto_orig = mov.get("monto_moneda_orig")
            monto_orig = Decimal(str(monto_orig)) if monto_orig not in (None, "", "null") else None
            tipo_cambio = mov.get("tipo_cambio")
            tipo_cambio = Decimal(str(tipo_cambio)) if tipo_cambio not in (None, "", "null") else None

            obj = MovimientoDiario.objects.create(
                fecha=mov["fecha"],
                tipo=mov["tipo"],
                descripcion=mov["descripcion"][:250],
                monto=monto_clp,
                medio_pago=mov.get("medio_pago", "transferencia"),
                notas=mov.get("notas", ""),
                # Campos nuevos
                cuenta_financiera=cuenta,
                moneda=moneda_mov,
                monto_moneda_orig=monto_orig,
                tipo_cambio=tipo_cambio,
                tc_pendiente=mov.get("tc_estimado", False),
                importacion=registro,
                referencia_externa=mov.get("referencia_externa", "")[:100],
                es_transferencia_interna=mov.get("es_transferencia_interna", False),
                categoria_normalizada=mov.get("categoria_normalizada", "sin_clasificar"),
                tercero=mov.get("tercero", "")[:200],
                pais_tercero=mov.get("pais_tercero", "")[:5],
                clasificacion_confianza=mov.get("clasificacion_confianza", ""),
                clasificacion_razon=mov.get("clasificacion_razon", "")[:250],
            )
            creados += 1
        except Exception as e:
            errores.append(f"{mov.get('descripcion', '?')[:50]}: {str(e)}")

    # Actualizar registro
    if registro:
        registro.total_importados = creados
        registro.total_duplicados = duplicados
        registro.total_errores = len(errores)
        registro.estado = 'completado' if not errores else 'con_errores'
        registro.save(update_fields=['total_importados', 'total_duplicados', 'total_errores', 'estado'])

    # Ejecutar conciliación automática en background
    try:
        detectar_transferencias_internas()
    except Exception:
        pass

    return JsonResponse({
        "mensaje": f"✅ {creados} movimientos importados correctamente",
        "creados": creados,
        "duplicados": duplicados,
        "errores": errores,
        "importacion_id": str(registro.pk) if registro else None,
    }, status=201)


# ─────────────────────────────────────────────
# Historial de Importaciones
# ─────────────────────────────────────────────

@require_http_methods(["GET"])
def historial_importaciones(request):
    registros = RegistroImportacion.objects.select_related('cuenta_financiera')[:50]
    return JsonResponse({"importaciones": [
        {
            "id": str(r.pk),
            "nombre_archivo": r.nombre_archivo,
            "banco_detectado": r.banco_detectado,
            "cuenta": str(r.cuenta_financiera) if r.cuenta_financiera else "—",
            "fecha": r.fecha_importacion.strftime('%d/%m/%Y %H:%M'),
            "total_importados": r.total_importados,
            "total_duplicados": r.total_duplicados,
            "total_errores": r.total_errores,
            "estado": r.estado,
        }
        for r in registros
    ]})


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
def importacion_detalle(request, importacion_id):
    """CRUD de una importación individual."""
    try:
        registro = RegistroImportacion.objects.select_related('cuenta_financiera').get(pk=importacion_id)
    except RegistroImportacion.DoesNotExist:
        return JsonResponse({"error": "Importación no encontrada"}, status=404)

    if request.method == "GET":
        return JsonResponse({
            "id": str(registro.pk),
            "nombre_archivo": registro.nombre_archivo,
            "banco_detectado": registro.banco_detectado,
            "cuenta": str(registro.cuenta_financiera) if registro.cuenta_financiera else "—",
            "cuenta_financiera_id": str(registro.cuenta_financiera_id) if registro.cuenta_financiera_id else None,
            "fecha": registro.fecha_importacion.strftime('%Y-%m-%dT%H:%M'),
            "total_filas_archivo": registro.total_filas_archivo,
            "total_importados": registro.total_importados,
            "total_duplicados": registro.total_duplicados,
            "total_errores": registro.total_errores,
            "estado": registro.estado,
            "advertencias": registro.advertencias or [],
            "hash_archivo": registro.hash_archivo,
        })

    if request.method == "PUT":
        try:
            body = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        if 'nombre_archivo' in body:
            registro.nombre_archivo = (body.get('nombre_archivo') or '').strip()[:255]
        if 'banco_detectado' in body:
            registro.banco_detectado = (body.get('banco_detectado') or '').strip()[:100]
        if 'estado' in body:
            estados_validos = {e[0] for e in RegistroImportacion.ESTADOS}
            if body['estado'] not in estados_validos:
                return JsonResponse({"error": "Estado inválido"}, status=400)
            registro.estado = body['estado']
        if 'cuenta_financiera_id' in body:
            cuenta_id = body.get('cuenta_financiera_id')
            if cuenta_id:
                try:
                    registro.cuenta_financiera = CuentaFinanciera.objects.get(pk=cuenta_id)
                except CuentaFinanciera.DoesNotExist:
                    return JsonResponse({"error": "Cuenta financiera no encontrada"}, status=404)
            else:
                registro.cuenta_financiera = None

        registro.save()
        return JsonResponse({"ok": True, "mensaje": "Importación actualizada"})

    eliminados, _ = MovimientoDiario.objects.filter(importacion=registro).delete()
    registro.delete()
    return JsonResponse({
        "ok": True,
        "mensaje": f"✅ Importación eliminada. {eliminados} movimiento(s) eliminados.",
        "eliminados": eliminados,
    })


@csrf_exempt
@require_http_methods(["POST"])
def revertir_importacion(request, importacion_id):
    """Elimina todos los movimientos de una importación y la marca como revertida."""
    try:
        registro = RegistroImportacion.objects.get(pk=importacion_id)
    except RegistroImportacion.DoesNotExist:
        return JsonResponse({"error": "Importación no encontrada"}, status=404)

    eliminados = MovimientoDiario.objects.filter(importacion=registro).delete()[0]
    registro.estado = 'revertido'
    registro.save(update_fields=['estado'])

    return JsonResponse({
        "mensaje": f"✅ Importación revertida. {eliminados} movimientos eliminados.",
        "eliminados": eliminados,
    })


# ─────────────────────────────────────────────
# Panel de Revisión Manual
# ─────────────────────────────────────────────

@require_http_methods(["GET"])
def revision_pendientes(request):
    """
    Retorna movimientos que requieren revisión manual:
    - Sin clasificar
    - Posibles transferencias internas no vinculadas
    - Posibles duplicados
    """
    sin_clasificar = MovimientoDiario.objects.filter(
        categoria_normalizada='sin_clasificar'
    ).order_by('-fecha')[:50]

    # Movimientos USD sin tipo de cambio definido
    sin_tc = MovimientoDiario.objects.filter(
        tc_pendiente=True
    ).order_by('-fecha')[:50]

    posibles_transferencias = sugerir_emparejamientos()[:20]

    # Posibles duplicados: mismo monto y fecha, más de una vez
    from django.db.models import Count
    from django.db.models.functions import TruncDate
    posibles_dup = (
        MovimientoDiario.objects
        .values('fecha', 'monto', 'medio_pago')
        .annotate(n=Count('id'))
        .filter(n__gt=1)
        .order_by('-fecha')[:20]
    )

    return JsonResponse({
        "sin_clasificar": [
            {
                "id": str(m.pk),
                "fecha": str(m.fecha),
                "descripcion": m.descripcion,
                "monto": float(m.monto),
                "tipo": m.tipo,
                "cuenta": str(m.cuenta_financiera) if m.cuenta_financiera else "—",
                "moneda": m.moneda,
            }
            for m in sin_clasificar
        ],
        "sin_tipo_cambio": [
            {
                "id": str(m.pk),
                "fecha": str(m.fecha),
                "descripcion": m.descripcion,
                "monto_orig": float(m.monto_moneda_orig) if m.monto_moneda_orig else None,
                "moneda": m.moneda,
                "tipo_banco": m.clasificacion_razon,
            }
            for m in sin_tc
        ],
        "posibles_transferencias": posibles_transferencias,
        "posibles_duplicados": [
            {
                "fecha": str(d['fecha']),
                "monto": float(d['monto']),
                "cantidad": d['n'],
            }
            for d in posibles_dup
        ],
        "totales": {
            "sin_clasificar": MovimientoDiario.objects.filter(categoria_normalizada='sin_clasificar').count(),
            "sin_tipo_cambio": MovimientoDiario.objects.filter(tc_pendiente=True).count(),
            "transferencias_sin_vincular": MovimientoDiario.objects.filter(
                categoria_normalizada__in=['transferencia_interna', 'conversion_divisa'],
                movimiento_relacionado__isnull=True
            ).count(),
        }
    })


@csrf_exempt
@require_http_methods(["PATCH"])
def clasificar_movimiento_view(request, mov_id):
    """Permite editar manualmente la clasificación de un movimiento."""
    try:
        mov = MovimientoDiario.objects.get(pk=mov_id)
    except MovimientoDiario.DoesNotExist:
        return JsonResponse({"error": "Movimiento no encontrado"}, status=404)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    campos_editables = [
        'tipo', 'categoria_normalizada', 'es_transferencia_interna',
        'tercero', 'pais_tercero', 'notas',
    ]
    campos_validos = {
        'tipo': {v for v, _ in MovimientoDiario.TIPOS},
        'categoria_normalizada': {v for v, _ in MovimientoDiario.CATEGORIAS_NORM},
    }
    for campo in campos_editables:
        if campo not in body:
            continue
        valor = body[campo]
        if campo in campos_validos and valor not in campos_validos[campo]:
            return JsonResponse({"error": f"Valor inválido para {campo}"}, status=400)
        setattr(mov, campo, valor)

    if mov.es_transferencia_interna and mov.categoria_normalizada == 'sin_clasificar':
        mov.categoria_normalizada = 'transferencia_interna'

    # Vincular movimiento relacionado
    rel_id = body.get("movimiento_relacionado_id")
    if rel_id:
        try:
            rel = MovimientoDiario.objects.get(pk=rel_id)
            mov.movimiento_relacionado = rel
            rel.movimiento_relacionado = mov
            rel.es_transferencia_interna = True
            rel.save(update_fields=['movimiento_relacionado', 'es_transferencia_interna'])
        except MovimientoDiario.DoesNotExist:
            pass
    elif "movimiento_relacionado_id" in body and rel_id is None:
        mov.movimiento_relacionado = None

    mov.clasificacion_razon = "Clasificado manualmente"
    mov.clasificacion_confianza = "alta"
    mov.save()

    return JsonResponse({"ok": True, "mensaje": "Clasificación actualizada"})


@require_http_methods(["GET"])
def tipos_para_selector(request):
    tipos = [{"value": k, "label": v} for k, v in MovimientoDiario.TIPOS]
    categorias = [{"value": k, "label": v} for k, v in MovimientoDiario.CATEGORIAS_NORM]
    return JsonResponse({"tipos": tipos, "categorias": categorias})

# ──────────────────────────────────────────────────────────────────────────────
# TIPO DE CAMBIO
# ──────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET", "POST"])
def tipo_cambio(request):
    """
    GET  /api/tipo-cambio/?moneda=USD
         Retorna el tipo de cambio vigente para la moneda dada.
         Usa el último tipo_cambio registrado en movimientos reales,
         con fallback a un valor conservador si no hay datos.

    POST /api/tipo-cambio/
         Body: {"moneda": "USD", "tipo_cambio": 950.50, "movimiento_id": "<uuid>"}
         Actualiza el tipo_cambio de un movimiento específico.
         Útil para corregir un TC mal registrado en la importación.
    """
    from .models import MovimientoDiario
    from .utils import _get_tipo_cambio_vigente
    from decimal import Decimal, InvalidOperation

    if request.method == "GET":
        moneda = request.GET.get("moneda", "USD").upper()
        tc = _get_tipo_cambio_vigente(moneda)

        # ¿Es estimado o tiene respaldo real?
        tiene_real = MovimientoDiario.objects.filter(
            moneda=moneda, tipo_cambio__isnull=False
        ).exists()

        ultimo_mov = (MovimientoDiario.objects
                      .filter(moneda=moneda, tipo_cambio__isnull=False)
                      .order_by('-fecha')
                      .values('fecha', 'tipo_cambio')
                      .first())

        return JsonResponse({
            "moneda":        moneda,
            "tipo_cambio":   float(tc),
            "es_estimado":   not tiene_real,
            "ultima_fecha":  str(ultimo_mov['fecha']) if ultimo_mov else None,
            "aviso": (
                "Tipo de cambio estimado. Registra un movimiento en USD con tipo de cambio "
                "para que el sistema use el valor real de tu empresa."
                if not tiene_real else None
            ),
        })

    # POST: actualizar TC de un movimiento puntual
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    mov_id = body.get("movimiento_id")
    nuevo_tc = body.get("tipo_cambio")

    if not mov_id or not nuevo_tc:
        return JsonResponse({"error": "Se requiere movimiento_id y tipo_cambio"}, status=400)

    try:
        mov = MovimientoDiario.objects.get(pk=mov_id)
    except MovimientoDiario.DoesNotExist:
        return JsonResponse({"error": "Movimiento no encontrado"}, status=404)

    try:
        tc_decimal = Decimal(str(nuevo_tc))
        if tc_decimal <= 0:
            raise ValueError
    except (InvalidOperation, ValueError):
        return JsonResponse({"error": "Tipo de cambio inválido"}, status=400)

    # Recalcular monto en CLP con el nuevo TC
    if mov.monto_moneda_orig:
        mov.monto = mov.monto_moneda_orig * tc_decimal
    mov.tipo_cambio = tc_decimal
    mov.tc_pendiente = False  # TC ya fue ingresado manualmente
    mov.save(update_fields=['tipo_cambio', 'monto', 'tc_pendiente'])

    return JsonResponse({
        "ok":          True,
        "movimiento_id": str(mov.id),
        "tipo_cambio": float(tc_decimal),
        "monto_clp":   float(mov.monto),
        "mensaje":     "Tipo de cambio actualizado. El monto en CLP fue recalculado.",
    })
