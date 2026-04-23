"""
Clasificador automático de movimientos financieros.

Transforma el texto raw del banco en categorías normalizadas del sistema.
Retorna confianza y razón para auditoría y revisión manual.
"""

from __future__ import annotations
import re


# ─────────────────────────────────────────────
# Reglas por tipo de transacción Global66
# ─────────────────────────────────────────────

_REGLAS_TIPO_GLOBAL66 = {
    # Neutros — transferencias internas
    "conversión de divisas":    ("conversion_divisa",     True,  "alta"),
    "conversion de divisas":    ("conversion_divisa",     True,  "alta"),
    "envío a cuenta bancaria":  ("transferencia_interna", True,  "alta"),
    "envio a cuenta bancaria":  ("transferencia_interna", True,  "alta"),
    # Financieros
    "intereses abonados":       ("interes_ganado",        False, "alta"),
    "comisión envío":           ("comision_bancaria",     False, "alta"),
    "comision envio":           ("comision_bancaria",     False, "alta"),
}

# Palabras clave para clasificar "Envío a [nombre]"
_ENVIO_LOGISTICA = [
    "segucargo", "flete", "cargo", "logistic", "courier", "despacho",
    "transporte", "envio", "shipping", "freight",
]
_ENVIO_IMPORTACION = [
    "import", "export", "zhuozhou", "co ltd", "co. ltd", "trading",
    "international", "internacional", "forwarder", "aduana",
]
_PALABRAS_EMPRESA = [
    "spa", "ltda", "s.a.", "s.a ", "eirl", "s.r.l", "inc", "corp",
    "company", "cia", "cía",
]

# Palabras clave para clasificar "Recibido de [nombre]"
_RECIBIDO_APORTE = [
    "munoz", "muñoz", "acuna", "acuña", "jorge", "ivan", "socio",
    "dueño", "dueno", "propietario",
]
_PROPIOS = ["jimacomex", "arenita"]

# Reglas para Banco de Chile (por descripción)
_REGLAS_BCH_DESC = [
    (["remuneracion", "remuneración", "sueldo", "salario", "liquidacion",
      "honorario", "pago personal"],           "remuneracion_norm",  False, "alta"),
    (["sii", "impuesto", "iva mensual", "tesoreria", "tesorería",
      "patente", "contribucion"],              "pago_impuesto",      False, "alta"),
    (["cuota prestamo", "cuota crédito", "dividendo hipotecario",
      "leasing", "credito hipotecario"],        "pago_prestamo_norm", False, "alta"),
    (["comision", "comisión", "mantencion", "mantención",
      "cargo banco", "costo cuenta"],           "comision_bancaria",  False, "alta"),
    (["abonos debito", "abonos débito", "abono tarjeta",
      "recaudacion", "recaudación"],            "venta",              False, "alta"),
]


def _contiene_empresa(texto: str) -> bool:
    t = texto.lower()
    return any(p in t for p in _PALABRAS_EMPRESA)


def _es_nombre_persona(texto: str) -> bool:
    """Heurística simple: si no contiene indicadores de empresa, es persona."""
    return not _contiene_empresa(texto)


def clasificar_movimiento(
    descripcion: str,
    tipo_banco: str = "",
    es_cargo: bool = False,
    institucion: str = "",
    moneda: str = "CLP",
) -> dict:
    """
    Clasifica un movimiento bancario en categoría normalizada.

    Retorna:
        categoria_normalizada: str
        es_transferencia_interna: bool
        confianza: 'alta' | 'media' | 'baja'
        razon: str
        tercero: str  (nombre del tercero si se detecta)
    """
    desc = descripcion.lower().strip()
    tipo_b = tipo_banco.lower().strip()
    tercero = ""

    inst = institucion.lower()

    # ── 1. Reglas por tipo_banco (Global66) ──────────────────────────
    if tipo_b in _REGLAS_TIPO_GLOBAL66:
        cat, interna, conf = _REGLAS_TIPO_GLOBAL66[tipo_b]
        return {
            "categoria_normalizada": cat,
            "es_transferencia_interna": interna,
            "confianza": conf,
            "razon": f"Tipo de transacción Global66: '{tipo_banco}'",
            "tercero": "",
        }

    # ── 2. "Envío a [nombre]" Global66 ───────────────────────────────
    m = re.match(r'^env[íi]o a (.+?)(?:\s*:.*)?$', tipo_b)
    if not m:
        m = re.match(r'^env[íi]o a (.+)', desc)
    if m:
        nombre_dest = m.group(1).strip()
        tercero = nombre_dest.title()
        d = nombre_dest.lower()
        if any(p in d for p in _ENVIO_IMPORTACION):
            return {"categoria_normalizada": "pago_importacion", "es_transferencia_interna": False,
                    "confianza": "alta", "razon": "Envío a proveedor de importación", "tercero": tercero}
        if any(p in d for p in _ENVIO_LOGISTICA):
            return {"categoria_normalizada": "gasto_logistica", "es_transferencia_interna": False,
                    "confianza": "alta", "razon": "Envío a empresa logística/flete", "tercero": tercero}
        if _es_nombre_persona(nombre_dest):
            return {"categoria_normalizada": "remuneracion_norm", "es_transferencia_interna": False,
                    "confianza": "media", "razon": "Envío a persona natural → posible remuneración", "tercero": tercero}
        if _contiene_empresa(nombre_dest):
            return {"categoria_normalizada": "pago_proveedor", "es_transferencia_interna": False,
                    "confianza": "media", "razon": "Envío a empresa → pago proveedor", "tercero": tercero}

    # ── 3. "Recibido de [nombre]" Global66 ───────────────────────────
    m = re.match(r'^recibido de (.+?)(?:\s*:.*)?$', tipo_b)
    if not m:
        m = re.match(r'^recibido de (.+)', desc)
    if m:
        nombre_orig = m.group(1).strip()
        tercero = nombre_orig.title()
        d = nombre_orig.lower()
        if any(p in d for p in _PROPIOS):
            return {"categoria_normalizada": "transferencia_interna", "es_transferencia_interna": True,
                    "confianza": "alta", "razon": "Recibido desde cuenta/empresa propia", "tercero": tercero}
        if any(p in d for p in _RECIBIDO_APORTE) or _es_nombre_persona(nombre_orig):
            return {"categoria_normalizada": "aporte_socio", "es_transferencia_interna": False,
                    "confianza": "media", "razon": "Recibido de persona natural → posible aporte socio", "tercero": tercero}
        if _contiene_empresa(nombre_orig):
            return {"categoria_normalizada": "venta", "es_transferencia_interna": False,
                    "confianza": "media", "razon": "Recibido de empresa → posible cobro/venta", "tercero": tercero}

    # ── 4. "Compra en [comercio]" Global66 ───────────────────────────
    m = re.match(r'^compra en (.+)', tipo_b) or re.match(r'^compra en (.+)', desc)
    if m:
        tercero = m.group(1).strip().title()
        return {"categoria_normalizada": "gasto_operacional", "es_transferencia_interna": False,
                "confianza": "alta", "razon": "Compra con tarjeta en comercio", "tercero": tercero}

    # ── 5. Reglas por descripción (Banco de Chile y genérico) ─────────
    for palabras, cat, interna, conf in _REGLAS_BCH_DESC:
        if any(p in desc for p in palabras):
            return {"categoria_normalizada": cat, "es_transferencia_interna": interna,
                    "confianza": conf, "razon": f"Descripción contiene palabra clave: '{palabras[0]}'",
                    "tercero": ""}

    # Banco de Chile: TRASPASO A/DE
    if "traspaso a:" in desc or "traspaso a :" in desc:
        nombre_dest = desc.split(":", 1)[-1].strip().title() if ":" in desc else ""
        tercero = nombre_dest
        return {"categoria_normalizada": "transferencia_interna", "es_transferencia_interna": True,
                "confianza": "media", "razon": "Traspaso saliente → posible transferencia interna",
                "tercero": tercero}

    if "traspaso de:" in desc or "traspaso de :" in desc:
        nombre_orig = desc.split(":", 1)[-1].strip().title() if ":" in desc else ""
        tercero = nombre_orig
        return {"categoria_normalizada": "aporte_socio" if _es_nombre_persona(nombre_orig) else "ingreso_banco",
                "es_transferencia_interna": False,
                "confianza": "media", "razon": "Traspaso recibido", "tercero": tercero}

    # Banco de Chile: PAGO con abonos
    if "pago:" in desc and ("abono" in desc or "debito" in desc or "crédito" in desc):
        return {"categoria_normalizada": "venta", "es_transferencia_interna": False,
                "confianza": "alta", "razon": "Liquidación de pagos con tarjeta (ventas)", "tercero": ""}

    # ── 6. Fallback por dirección del dinero ──────────────────────────
    cat = "egreso_banco" if es_cargo else "ingreso_banco"
    # Mapear a categorías normalizadas
    cat_norm = "gasto_operacional" if es_cargo else "venta"
    return {"categoria_normalizada": "sin_clasificar", "es_transferencia_interna": False,
            "confianza": "baja", "razon": "No se encontró regla de clasificación",
            "tercero": tercero}


def clasificar_lote(movimientos: list, institucion: str = "", moneda: str = "CLP") -> list:
    """
    Clasifica una lista de movimientos en lote.
    Cada elemento debe tener: descripcion, tipo_banco, es_cargo
    Retorna la misma lista con campos de clasificación añadidos.
    """
    resultado = []
    for mov in movimientos:
        clasificacion = clasificar_movimiento(
            descripcion=mov.get("descripcion", ""),
            tipo_banco=mov.get("tipo_banco", ""),
            es_cargo=mov.get("es_cargo", False),
            institucion=institucion,
            moneda=moneda,
        )
        mov_clasificado = {**mov, **clasificacion}
        resultado.append(mov_clasificado)
    return resultado