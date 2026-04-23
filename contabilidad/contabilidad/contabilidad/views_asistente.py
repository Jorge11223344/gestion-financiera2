"""
Asistente Contable de Balance — Vista Django.
Llama a la API de Anthropic usando la ANTHROPIC_API_KEY del archivo .env.

Para configurar:
1. Crea el archivo .env en la raíz del proyecto (copia de .env.example)
2. Agrega la línea: ANTHROPIC_API_KEY=sk-ant-api03-TU-KEY-AQUI
3. Obtén tu key en: console.anthropic.com → API Keys
"""
import json
import os
import urllib.request
import urllib.error
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import ConfiguracionEmpresa


SYSTEM_PROMPT_CONTADOR = """Eres un contador público certificado con 20 años de experiencia especializado en empresas importadoras chilenas. Tu rol es asistir al usuario a completar correctamente su balance general y comprender cada cuenta contable.

## Tu especialidad incluye:
- Contabilidad IFRS para PyMEs (norma chilena)
- Importaciones: DUS, gastos de internación, derechos aduaneros, IVA importación
- Plan de cuentas chileno (Decreto Ley 824 y normativa del SII)
- Tributación: IVA, PPM, renta, impuesto adicional artículo 59
- Remuneraciones: liquidaciones, cotizaciones previsionales, finiquitos
- Costeo de inventario: FIFO, promedio ponderado
- Reconciliación bancaria

## Cómo responder:
1. Cuando el usuario mencione una cuenta o transacción, SIEMPRE explica:
   - En qué parte del balance va (Activo / Pasivo / Patrimonio / Resultado)
   - Si es un CARGO (débito) o ABONO (crédito)
   - El asiento contable completo (partida doble)
   - Implicancias tributarias si aplica
   - Errores comunes a evitar

2. Para importaciones específicamente:
   - Explica el tratamiento del IVA de importación (crédito fiscal vs. costo)
   - Diferencias de cambio (tipo de cambio del día del DUS vs. pago)
   - Gastos de internación: flete, seguro, derechos aduaneros (se suman al costo del inventario)
   - Tratamiento del IVA retenido en fletes internacionales

3. Usa terminología chilena:
   - "cargo" en vez de "débito", "abono" en vez de "crédito" cuando hables con el usuario
   - Cita el código de cuenta del plan estándar chileno cuando sea relevante
   - Menciona formularios del SII cuando aplique (F29, F22, etc.)

4. Formato de respuesta:
   - Sé directo y práctico
   - Usa asientos contables con formato: Cuenta | Cargo | Abono
   - Resalta con ⚠️ los errores frecuentes
   - Usa ✅ para confirmar cuando algo está correcto
   - Máximo 3 párrafos de explicación, luego el asiento

5. Si el usuario está armando el balance, guíalo sección por sección:
   ACTIVO → PASIVO → PATRIMONIO
   Siempre verificando que el balance cuadre (Activo = Pasivo + Patrimonio)

Responde siempre en español, tono profesional pero cercano."""


def get_api_key():
    """Lee la API key desde variables de entorno (cargadas desde .env por django)."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    return key.strip()


@csrf_exempt
@require_http_methods(["POST"])
def asistente_balance(request):
    """Endpoint principal del asistente contable."""

    # Verificar que existe la API key antes de procesar
    api_key = get_api_key()
    if not api_key:
        return JsonResponse({
            "error": "api_key_missing",
            "mensaje": (
                "Falta configurar la API key de Anthropic. "
                "Pasos: 1) Crea el archivo .env en la carpeta del proyecto. "
                "2) Agrega la línea: ANTHROPIC_API_KEY=sk-ant-api03-TU-KEY. "
                "3) Obtén tu key gratis en console.anthropic.com"
            )
        }, status=503)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "json_invalido", "mensaje": "JSON inválido"}, status=400)

    mensajes = body.get("mensajes", [])
    balance_actual = body.get("balance_actual", {})

    if not mensajes:
        return JsonResponse({"error": "sin_mensajes", "mensaje": "No hay mensajes"}, status=400)

    # Enriquecer con datos de la empresa
    config = ConfiguracionEmpresa.get()
    contexto_empresa = f"\n\nEmpresa: {config.nombre}"
    if config.giro:
        contexto_empresa += f"\nGiro: {config.giro}"
    if config.rut:
        contexto_empresa += f"\nRUT: {config.rut}"

    # Agregar contexto del balance si viene con valores
    contexto_balance = ""
    if balance_actual and any(balance_actual.values()):
        total_activo = balance_actual.get("total_activo", 0)
        total_pasivo = balance_actual.get("total_pasivo", 0)
        total_patrimonio = balance_actual.get("total_patrimonio", 0)
        diferencia = total_activo - (total_pasivo + total_patrimonio)
        contexto_balance = f"""

## Balance en construcción (estado actual):
- Total Activo: ${total_activo:,.0f}
- Total Pasivo: ${total_pasivo:,.0f}
- Total Patrimonio: ${total_patrimonio:,.0f}
- Diferencia: ${diferencia:,.0f} {"← ⚠️ NO CUADRA" if abs(diferencia) > 1 else "← ✅ CUADRA"}"""

    system_completo = SYSTEM_PROMPT_CONTADOR + contexto_empresa + contexto_balance

    # Construir payload para la API de Anthropic
    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1000,
        "system": system_completo,
        "messages": mensajes[-20:],  # Máximo 20 mensajes de historial para controlar costos
    }

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            texto = data["content"][0]["text"]
            # Calcular tokens usados para informar al usuario
            tokens_entrada = data.get("usage", {}).get("input_tokens", 0)
            tokens_salida = data.get("usage", {}).get("output_tokens", 0)
            costo_usd = (tokens_entrada * 0.000003) + (tokens_salida * 0.000015)
            return JsonResponse({
                "ok": True,
                "respuesta": texto,
                "tokens": tokens_entrada + tokens_salida,
                "costo_usd": round(costo_usd, 5),
            })

    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8")
        try:
            error_data = json.loads(cuerpo)
            tipo_error = error_data.get("error", {}).get("type", "")
            mensaje_error = error_data.get("error", {}).get("message", cuerpo)

            if tipo_error == "authentication_error":
                return JsonResponse({
                    "error": "api_key_invalida",
                    "mensaje": "La API key es inválida o fue revocada. Verifica en console.anthropic.com → API Keys."
                }, status=401)

            if tipo_error == "insufficient_credits":
                return JsonResponse({
                    "error": "sin_credito",
                    "mensaje": "No tienes crédito en tu cuenta de Anthropic. Agrega crédito en console.anthropic.com → Billing."
                }, status=402)

            return JsonResponse({
                "error": "api_error",
                "mensaje": f"Error de la API: {mensaje_error}"
            }, status=500)

        except Exception:
            return JsonResponse({
                "error": "api_error",
                "mensaje": f"Error HTTP {e.code}: {cuerpo[:200]}"
            }, status=500)

    except urllib.error.URLError as e:
        return JsonResponse({
            "error": "sin_conexion",
            "mensaje": "No se pudo conectar con la API de Anthropic. Verifica tu conexión a internet."
        }, status=503)

    except Exception as e:
        return JsonResponse({
            "error": "error_inesperado",
            "mensaje": f"Error inesperado: {str(e)}"
        }, status=500)


@require_http_methods(["GET"])
def estado_api(request):
    """
    Verifica si la API key está configurada.
    El frontend lo llama al cargar el módulo para mostrar aviso si falta.
    """
    api_key = get_api_key()
    if not api_key:
        return JsonResponse({
            "configurada": False,
            "mensaje": "API key no configurada. Agrega ANTHROPIC_API_KEY en el archivo .env"
        })
    # Mostrar solo los primeros y últimos caracteres por seguridad
    preview = api_key[:12] + "..." + api_key[-4:] if len(api_key) > 20 else "***"
    return JsonResponse({
        "configurada": True,
        "preview": preview,
        "mensaje": "API key configurada correctamente"
    })


@require_http_methods(["GET"])
def cuentas_balance(request):
    """Estructura del balance con 35 cuentas para importadoras chilenas."""
    estructura = {
        "activo_circulante": [
            {"codigo": "1.1.01", "nombre": "Caja", "grupo": "Disponible", "ayuda": "Dinero en efectivo en caja chica y caja principal"},
            {"codigo": "1.1.02", "nombre": "Banco cuenta corriente", "grupo": "Disponible", "ayuda": "Saldo en cuenta corriente bancaria"},
            {"codigo": "1.1.03", "nombre": "Banco Global66 / divisas", "grupo": "Disponible", "ayuda": "Saldo en cuentas de divisas o fintech"},
            {"codigo": "1.1.04", "nombre": "Clientes (cuentas por cobrar)", "grupo": "Realizable", "ayuda": "Facturas emitidas pendientes de cobro"},
            {"codigo": "1.1.05", "nombre": "Deudores varios", "grupo": "Realizable", "ayuda": "Otros deudores no clasificados como clientes"},
            {"codigo": "1.1.06", "nombre": "IVA crédito fiscal", "grupo": "Realizable", "ayuda": "IVA de compras nacionales pendiente de utilizar"},
            {"codigo": "1.1.07", "nombre": "IVA importación", "grupo": "Realizable", "ayuda": "IVA pagado en aduanas por importaciones"},
            {"codigo": "1.1.08", "nombre": "PPM (pagos provisionales mensuales)", "grupo": "Realizable", "ayuda": "Pagos provisionales art. 84 LIR acumulados en el año"},
            {"codigo": "1.1.09", "nombre": "Inventario / Mercadería", "grupo": "Realizable", "ayuda": "Stock de productos para la venta, incluye costo de internación"},
            {"codigo": "1.1.10", "nombre": "Mercadería en tránsito", "grupo": "Realizable", "ayuda": "Importaciones con DUS abierto, aún no internadas al país"},
            {"codigo": "1.1.11", "nombre": "Anticipo a proveedores del exterior", "grupo": "Realizable", "ayuda": "Pagos anticipados a exportadores extranjeros (en USD/EUR)"},
            {"codigo": "1.1.12", "nombre": "Gastos anticipados", "grupo": "Realizable", "ayuda": "Seguros, arriendos u otros pagados por adelantado"},
        ],
        "activo_fijo": [
            {"codigo": "1.2.01", "nombre": "Muebles y equipos de oficina", "grupo": "Activo Fijo", "ayuda": "Escritorios, computadores, impresoras, sillas"},
            {"codigo": "1.2.02", "nombre": "Vehículos", "grupo": "Activo Fijo", "ayuda": "Camiones, furgones, automóviles de la empresa"},
            {"codigo": "1.2.03", "nombre": "Maquinaria y equipo", "grupo": "Activo Fijo", "ayuda": "Equipos productivos, de bodega o de distribución"},
            {"codigo": "1.2.04", "nombre": "Depreciación acumulada", "grupo": "Activo Fijo", "ayuda": "Valor negativo que reduce el activo fijo (cuenta complementaria)"},
        ],
        "activo_otros": [
            {"codigo": "1.3.01", "nombre": "Depósitos en garantía", "grupo": "Otros Activos", "ayuda": "Garantías entregadas por arriendo u otros contratos vigentes"},
            {"codigo": "1.3.02", "nombre": "Intangibles (software, marcas)", "grupo": "Otros Activos", "ayuda": "Activos no físicos con valor económico demostrable"},
        ],
        "pasivo_circulante": [
            {"codigo": "2.1.01", "nombre": "Proveedores nacionales", "grupo": "Cuentas por Pagar", "ayuda": "Facturas de proveedores locales pendientes de pago"},
            {"codigo": "2.1.02", "nombre": "Proveedores del exterior", "grupo": "Cuentas por Pagar", "ayuda": "Cuentas por pagar a exportadores extranjeros en USD o EUR"},
            {"codigo": "2.1.03", "nombre": "IVA débito fiscal", "grupo": "Tributario", "ayuda": "IVA cobrado en ventas, pendiente de declarar al SII en F29"},
            {"codigo": "2.1.04", "nombre": "IVA por pagar neto", "grupo": "Tributario", "ayuda": "Diferencia entre IVA débito y crédito fiscal del mes"},
            {"codigo": "2.1.05", "nombre": "PPM por pagar", "grupo": "Tributario", "ayuda": "Pago provisional mensual del mes en curso a enterar al SII"},
            {"codigo": "2.1.06", "nombre": "Impuesto adicional art. 59 (retención)", "grupo": "Tributario", "ayuda": "Retención 15% o 35% sobre remesas al exterior por servicios"},
            {"codigo": "2.1.07", "nombre": "Remuneraciones por pagar", "grupo": "Remuneraciones", "ayuda": "Sueldos y salarios del mes devengados aún no pagados"},
            {"codigo": "2.1.08", "nombre": "Cotizaciones previsionales por pagar", "grupo": "Remuneraciones", "ayuda": "AFP, Isapre/Fonasa, seguro cesantía del mes pendientes"},
            {"codigo": "2.1.09", "nombre": "Préstamos bancarios corto plazo", "grupo": "Financiero", "ayuda": "Créditos bancarios con vencimiento menor a 12 meses"},
            {"codigo": "2.1.10", "nombre": "Línea de crédito utilizada", "grupo": "Financiero", "ayuda": "Monto girado de la línea de crédito bancaria vigente"},
            {"codigo": "2.1.11", "nombre": "Gastos acumulados por pagar", "grupo": "Otros", "ayuda": "Gastos devengados no pagados: luz, agua, internet, servicios"},
        ],
        "pasivo_largo_plazo": [
            {"codigo": "2.2.01", "nombre": "Préstamos bancarios largo plazo", "grupo": "Financiero LP", "ayuda": "Créditos con vencimiento mayor a 12 meses"},
            {"codigo": "2.2.02", "nombre": "Leasing financiero", "grupo": "Financiero LP", "ayuda": "Obligaciones de arrendamiento financiero (IFRS 16)"},
        ],
        "patrimonio": [
            {"codigo": "3.1.01", "nombre": "Capital pagado", "grupo": "Patrimonio", "ayuda": "Aporte efectivamente enterado por los socios o accionistas"},
            {"codigo": "3.1.02", "nombre": "Utilidades retenidas años anteriores", "grupo": "Patrimonio", "ayuda": "Ganancias acumuladas de ejercicios anteriores no distribuidas"},
            {"codigo": "3.1.03", "nombre": "Pérdidas acumuladas", "grupo": "Patrimonio", "ayuda": "Pérdidas de ejercicios anteriores (se ingresa como valor negativo)"},
            {"codigo": "3.1.04", "nombre": "Resultado del ejercicio", "grupo": "Patrimonio", "ayuda": "Utilidad o pérdida del año en curso (viene del Estado de Resultados)"},
        ],
    }
    return JsonResponse({"estructura": estructura})
