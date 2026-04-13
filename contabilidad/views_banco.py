"""
Vistas para importación de cartola bancaria.
Flujo:
  1. POST /api/banco/preview  → sube archivo, devuelve preview sin guardar
  2. POST /api/banco/confirmar → guarda los movimientos seleccionados
  3. GET  /api/banco/historial → importaciones anteriores
"""

import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from .models import MovimientoDiario
from .importador_banco import (
    parsear_excel, parsear_csv, convertir_a_movimientos, ResultadoImportacion
)


@csrf_exempt
@require_http_methods(["POST"])
def preview_cartola(request):
    """
    Recibe el archivo Excel/CSV, lo parsea y devuelve preview
    sin guardar nada en la base de datos.
    """
    if "archivo" not in request.FILES:
        return JsonResponse({"error": "No se recibió ningún archivo"}, status=400)

    archivo = request.FILES["archivo"]
    nombre = archivo.name.lower()
    contenido = archivo.read()

    # Parsear según extensión
    if nombre.endswith((".xlsx", ".xls")):
        resultado = parsear_excel(contenido, nombre)
    elif nombre.endswith(".csv"):
        resultado = parsear_csv(contenido)
    else:
        return JsonResponse(
            {"error": "Formato no soportado. Usa .xlsx o .csv"},
            status=400
        )

    if resultado.errores:
        return JsonResponse({
            "error": resultado.errores[0],
            "todos_errores": resultado.errores,
        }, status=422)

    # Convertir a formato de movimientos
    movimientos_propuestos = convertir_a_movimientos(resultado)

    # Detectar posibles duplicados (misma fecha + monto + tipo ya existe)
    for mov in movimientos_propuestos:
        existe = MovimientoDiario.objects.filter(
            fecha=mov["fecha"],
            monto=mov["monto"],
            medio_pago="transferencia",
        ).exists()
        mov["posible_duplicado"] = existe
        mov["fecha"] = str(mov["fecha"])
        mov["monto"] = int(mov["monto"])

    # Estadísticas del preview
    total_ingresos = sum(m["monto"] for m in movimientos_propuestos if m["tipo"] in [
        "ingreso_banco", "ingreso_caja", "otro_ingreso"
    ])
    total_egresos = sum(m["monto"] for m in movimientos_propuestos if m["tipo"] not in [
        "ingreso_banco", "ingreso_caja", "otro_ingreso"
    ])
    duplicados = sum(1 for m in movimientos_propuestos if m["posible_duplicado"])

    return JsonResponse({
        "banco_detectado": resultado.banco_detectado,
        "total_filas_archivo": resultado.total_filas_archivo,
        "total_filas_validas": resultado.total_filas_validas,
        "advertencias": resultado.advertencias,
        "movimientos": movimientos_propuestos,
        "estadisticas": {
            "total_ingresos": total_ingresos,
            "total_egresos": total_egresos,
            "resultado": total_ingresos - total_egresos,
            "posibles_duplicados": duplicados,
        }
    })


@csrf_exempt
@require_http_methods(["POST"])
def confirmar_importacion(request):
    """
    Recibe la lista de movimientos confirmados por el usuario y los guarda.
    El frontend puede excluir algunos (duplicados o incorrectos).
    """
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    movimientos = body.get("movimientos", [])
    if not movimientos:
        return JsonResponse({"error": "No hay movimientos para importar"}, status=400)

    creados = 0
    errores = []

    for mov in movimientos:
        if not mov.get("incluir", True):
            continue  # el usuario lo excluyó

        try:
            from decimal import Decimal
            MovimientoDiario.objects.create(
                fecha=mov["fecha"],
                tipo=mov["tipo"],
                descripcion=mov["descripcion"][:250],
                monto=Decimal(str(mov["monto"])),
                medio_pago=mov.get("medio_pago", "transferencia"),
                notas=mov.get("notas", ""),
            )
            creados += 1
        except Exception as e:
            errores.append(f"Fila {mov.get('descripcion','?')}: {str(e)}")

    return JsonResponse({
        "mensaje": f"✅ {creados} movimientos importados correctamente",
        "creados": creados,
        "errores": errores,
    }, status=201)


@require_http_methods(["GET"])
def tipos_para_selector(_request):
    """Devuelve los tipos de movimiento para el selector del preview."""
    tipos = [{"value": k, "label": v} for k, v in MovimientoDiario.TIPOS]
    return JsonResponse({"tipos": tipos})
