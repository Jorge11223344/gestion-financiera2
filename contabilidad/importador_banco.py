"""
Importador de cartolas bancarias.
Soporta:
  - Global66                  → CSV separador punto y coma (;), columna "Tipo" nativa
  - Banco de Chile / Edwards  → Excel (.xlsx / .xls)
  - CSV genérico              → fallback para Santander, BCI y otros

El banco se detecta automáticamente por el contenido y nombre del archivo.
Global66 tiene parser especializado que usa la columna "Tipo" del CSV para
clasificar movimientos con mayor precisión.
"""

import csv
import io
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ─────────────────────────────────────────────
# Estructuras de datos
# ─────────────────────────────────────────────

@dataclass
class FilaCartola:
    fecha: date
    descripcion: str
    cargo: Decimal
    abono: Decimal
    saldo: Optional[Decimal]
    documento: str = ""
    tipo_banco: str = ""    # columna "Tipo" nativa del banco (útil en Global66)
    fila_origen: int = 0


@dataclass
class ResultadoImportacion:
    filas: List[FilaCartola] = field(default_factory=list)
    errores: List[str] = field(default_factory=list)
    advertencias: List[str] = field(default_factory=list)
    banco_detectado: str = "Desconocido"
    total_filas_archivo: int = 0
    total_filas_validas: int = 0


# ─────────────────────────────────────────────
# Utilidades de parseo
# ─────────────────────────────────────────────

def parse_fecha(valor) -> Optional[date]:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    s = str(valor).strip().split(" ")[0].split("T")[0]
    for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y",
                "%Y-%m-%d", "%Y/%m/%d", "%d %b %Y"]:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_monto(valor) -> Decimal:
    if valor is None or str(valor).strip() in ("", "-", "--", "N/A"):
        return Decimal("0")
    if isinstance(valor, (int, float)):
        return Decimal(str(abs(valor)))
    s = str(valor).strip().replace("$", "").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        partes = s.split(",")
        s = s.replace(",", ".") if len(partes) == 2 and len(partes[1]) <= 2 else s.replace(",", "")
    elif "." in s:
        partes = s.split(".")
        if len(partes) > 2 or (len(partes) == 2 and len(partes[1]) == 3):
            s = s.replace(".", "")
    s = s.replace("(", "-").replace(")", "")
    try:
        return abs(Decimal(s))
    except InvalidOperation:
        return Decimal("0")


def decodificar(archivo_bytes: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return archivo_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("No se pudo decodificar el archivo")


def es_fila_encabezado(valores: list) -> bool:
    texto = " ".join(str(v).lower() for v in valores if v)
    kw = ["fecha", "descripcion", "descripción", "cargo", "abono", "saldo",
          "tipo", "detalle", "referencia", "monto", "débito", "crédito"]
    return sum(1 for k in kw if k in texto) >= 2


def detectar_columnas(fila: list) -> dict:
    mapa = {}
    for i, celda in enumerate(fila):
        t = str(celda).lower().strip()
        if any(p in t for p in ["fecha", "date"]):
            mapa.setdefault("fecha", i)
        elif t in ["tipo", "tipo transaccion", "tipo transacción", "tipo movimiento"]:
            mapa.setdefault("tipo_banco", i)
        elif any(p in t for p in ["descripcion", "descripción", "detalle", "glosa", "concepto"]):
            mapa.setdefault("descripcion", i)
        elif any(p in t for p in ["cargo", "débito", "debito", "retiro", "egreso"]):
            mapa.setdefault("cargo", i)
        elif any(p in t for p in ["abono", "crédito", "credito", "depósito", "deposito", "ingreso"]):
            mapa.setdefault("abono", i)
        elif any(p in t for p in ["saldo", "balance"]):
            mapa.setdefault("saldo", i)
        elif any(p in t for p in ["referencia", "documento", "n°", "folio", "ref"]):
            mapa.setdefault("documento", i)
    return mapa


def detectar_banco(texto: str, nombre: str = "") -> str:
    t, n = texto.lower(), nombre.lower()
    if "global66" in t or "global66" in n or "global 66" in t:
        return "Global66"
    if "banco de chile" in t or "edwards" in t or "bancochile" in n:
        return "Banco de Chile / Edwards"
    if "santander" in t:
        return "Santander"
    if "bci" in t or "bci" in n:
        return "BCI"
    if "scotiabank" in t:
        return "Scotiabank"
    if "itau" in t or "itaú" in t:
        return "Itaú"
    return "CSV Genérico"


# ─────────────────────────────────────────────
# Clasificador Global66 (usa columna Tipo nativa)
# ─────────────────────────────────────────────

MAPA_GLOBAL66 = {
    "transferencia recibida": "ingreso_banco",
    "abono":                  "ingreso_banco",
    "deposito":               "ingreso_banco",
    "depósito":               "ingreso_banco",
    "conversion de divisas":  "ingreso_banco",
    "conversión de divisas":  "ingreso_banco",
    "transferencia enviada":  "egreso_banco",
    "cargo":                  "egreso_banco",
    "retiro":                 "egreso_banco",
    "comision":               "egreso_banco",
    "comisión":               "egreso_banco",
    "mantencion":             "egreso_banco",
    "mantención":             "egreso_banco",
    "saldo inicial":          None,   # ignorar
    "saldo anterior":         None,
}


def clasificar_global66(tipo_banco: str, descripcion: str, es_cargo: bool) -> Optional[str]:
    tb = tipo_banco.lower().strip()
    desc = descripcion.lower()

    # Para egresos: primero revisar descripción en busca de categorías específicas,
    # ya que "Transferencia enviada" puede ser remuneración, impuesto, etc.
    if es_cargo:
        if any(p in desc for p in ["remuneracion", "remuneración", "sueldo", "salario", "planilla"]):
            return "remuneracion"
        if any(p in desc for p in ["sii", "impuesto", "iva mensual", "renta", "patente", "tesoreria"]):
            return "impuesto"
        if any(p in desc for p in ["cuota prestamo", "cuota crédito", "credito hipotecario", "leasing"]):
            return "pago_prestamo"

    # Luego usar el tipo nativo del banco
    if tb in MAPA_GLOBAL66:
        return MAPA_GLOBAL66[tb]
    for clave, tipo in MAPA_GLOBAL66.items():
        if clave in tb:
            return tipo

    return "egreso_banco" if es_cargo else "ingreso_banco"


# ─────────────────────────────────────────────
# Parser Global66 (especializado)
# ─────────────────────────────────────────────

def parsear_global66(archivo_bytes: bytes, nombre_archivo: str = "") -> ResultadoImportacion:
    resultado = ResultadoImportacion()
    resultado.banco_detectado = "Global66"

    try:
        texto = decodificar(archivo_bytes)
    except ValueError as e:
        resultado.errores.append(str(e))
        return resultado

    reader = csv.reader(io.StringIO(texto), delimiter=";")
    todas_filas = list(reader)
    resultado.total_filas_archivo = len(todas_filas)

    # Buscar encabezado
    mapa_columnas = {}
    fila_enc_idx = None
    for i, fila in enumerate(todas_filas):
        if es_fila_encabezado(fila):
            mapa = detectar_columnas(fila)
            if "fecha" in mapa:
                mapa_columnas = mapa
                fila_enc_idx = i
                break

    if not mapa_columnas:
        resultado.errores.append(
            "No se detectó encabezado en el CSV de Global66. "
            "Exporta desde: Cuenta → Movimientos → Descargar CSV."
        )
        return resultado

    for i, fila in enumerate(todas_filas[fila_enc_idx + 1:], fila_enc_idx + 2):
        if not any(f.strip() for f in fila):
            continue

        fecha = parse_fecha(fila[mapa_columnas["fecha"]] if len(fila) > mapa_columnas.get("fecha", 99) else None)
        if fecha is None:
            continue

        tipo_banco_idx = mapa_columnas.get("tipo_banco")
        tipo_banco = fila[tipo_banco_idx].strip() if tipo_banco_idx is not None and len(fila) > tipo_banco_idx else ""

        desc_idx = mapa_columnas.get("descripcion")
        doc_idx  = mapa_columnas.get("documento")
        desc_raw  = fila[desc_idx].strip() if desc_idx is not None and len(fila) > desc_idx else ""
        referencia = fila[doc_idx].strip() if doc_idx is not None and len(fila) > doc_idx else ""

        if not desc_raw:
            desc_raw = tipo_banco or "Movimiento Global66"

        descripcion = f"{desc_raw} [{referencia}]" if referencia and referencia not in desc_raw else desc_raw

        cargo_idx = mapa_columnas.get("cargo")
        abono_idx = mapa_columnas.get("abono")
        cargo = parse_monto(fila[cargo_idx]) if cargo_idx is not None and len(fila) > cargo_idx else Decimal("0")
        abono = parse_monto(fila[abono_idx]) if abono_idx is not None and len(fila) > abono_idx else Decimal("0")

        saldo_idx = mapa_columnas.get("saldo")
        saldo = parse_monto(fila[saldo_idx]) if saldo_idx is not None and len(fila) > saldo_idx else None

        if cargo == 0 and abono == 0:
            continue

        resultado.filas.append(FilaCartola(
            fecha=fecha,
            descripcion=descripcion[:250],
            cargo=cargo,
            abono=abono,
            saldo=saldo,
            documento=referencia,
            tipo_banco=tipo_banco,
            fila_origen=i,
        ))

    resultado.total_filas_validas = len(resultado.filas)
    return resultado


# ─────────────────────────────────────────────
# Parser Excel (Banco de Chile y otros)
# ─────────────────────────────────────────────

def parsear_excel(archivo_bytes: bytes, nombre_archivo: str = "") -> ResultadoImportacion:
    resultado = ResultadoImportacion()

    # Detectar formato por extensión y magic bytes
    nombre_lower = nombre_archivo.lower()
    es_xls = nombre_lower.endswith(".xls") or archivo_bytes[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'

    todas_filas = []

    if es_xls:
        # Formato antiguo .xls → usar xlrd
        try:
            import xlrd
            wb = xlrd.open_workbook(file_contents=archivo_bytes)
            ws = wb.sheet_by_index(0)
            for row_idx in range(ws.nrows):
                fila = []
                for col_idx in range(ws.ncols):
                    cell = ws.cell(row_idx, col_idx)
                    # Convertir tipos de celda xlrd a valores Python
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        try:
                            dt_tuple = xlrd.xldate_as_tuple(cell.value, wb.datemode)
                            fila.append(datetime(*dt_tuple[:6]).date() if dt_tuple[3:] == (0,0,0) else datetime(*dt_tuple[:6]))
                        except Exception:
                            fila.append(cell.value)
                    elif cell.ctype == xlrd.XL_CELL_NUMBER:
                        # Preservar como número (evita que 1234567.0 se convierta en string)
                        v = cell.value
                        fila.append(int(v) if v == int(v) else v)
                    elif cell.ctype == xlrd.XL_CELL_EMPTY:
                        fila.append(None)
                    else:
                        fila.append(cell.value)
                todas_filas.append(tuple(fila))
        except ImportError:
            resultado.errores.append(
                "Archivo .xls detectado pero falta la librería xlrd. "
                "Ejecuta: pip install xlrd==2.0.1"
            )
            return resultado
        except Exception as e:
            resultado.errores.append(f"No se pudo abrir el archivo .xls: {e}")
            return resultado
    else:
        # Formato moderno .xlsx → usar openpyxl
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(archivo_bytes), data_only=True)
            ws = wb.active
            todas_filas = list(ws.iter_rows(values_only=True))
        except Exception as e:
            resultado.errores.append(f"No se pudo abrir el Excel: {e}")
            return resultado

    resultado.total_filas_archivo = len(todas_filas)

    texto_cab = " ".join(str(c).lower() for fila in todas_filas[:6] for c in fila if c)
    resultado.banco_detectado = detectar_banco(texto_cab, nombre_archivo)

    fila_enc_idx = None
    mapa_columnas = {}
    for i, fila in enumerate(todas_filas):
        if len([v for v in fila if v is not None]) >= 3 and es_fila_encabezado(fila):
            mapa = detectar_columnas(fila)
            if "fecha" in mapa and ("cargo" in mapa or "abono" in mapa):
                fila_enc_idx = i
                mapa_columnas = mapa
                break

    if fila_enc_idx is None:
        resultado.advertencias.append("Encabezado no detectado. Usando detección automática.")
        mapa_columnas, fila_enc_idx = _detectar_columnas_heuristico(todas_filas)

    if not mapa_columnas or "fecha" not in mapa_columnas:
        resultado.errores.append(
            "No se identificaron columnas. Exporta la cartola en formato estándar desde el banco."
        )
        return resultado

    for i, fila in enumerate(todas_filas[fila_enc_idx + 1:], fila_enc_idx + 2):
        if not any(fila):
            continue
        valores = list(fila)
        fecha = parse_fecha(valores[mapa_columnas["fecha"]] if len(valores) > mapa_columnas.get("fecha", 99) else None)
        if fecha is None:
            continue

        desc_idx = mapa_columnas.get("descripcion")
        descripcion = str(valores[desc_idx]).strip() if desc_idx is not None and len(valores) > desc_idx else "Movimiento bancario"
        if not descripcion or descripcion.lower() in ("none", ""):
            descripcion = "Movimiento bancario"

        cargo_idx = mapa_columnas.get("cargo")
        abono_idx = mapa_columnas.get("abono")
        cargo = parse_monto(valores[cargo_idx]) if cargo_idx is not None and len(valores) > cargo_idx else Decimal("0")
        abono = parse_monto(valores[abono_idx]) if abono_idx is not None and len(valores) > abono_idx else Decimal("0")

        saldo_idx = mapa_columnas.get("saldo")
        saldo = parse_monto(valores[saldo_idx]) if saldo_idx is not None and len(valores) > saldo_idx else None

        doc_idx = mapa_columnas.get("documento")
        documento = str(valores[doc_idx]).strip() if doc_idx is not None and len(valores) > doc_idx else ""
        if documento.lower() in ("none", ""):
            documento = ""

        if cargo == 0 and abono == 0:
            continue

        resultado.filas.append(FilaCartola(
            fecha=fecha, descripcion=descripcion,
            cargo=cargo, abono=abono, saldo=saldo,
            documento=documento, fila_origen=i,
        ))

    resultado.total_filas_validas = len(resultado.filas)
    return resultado


# ─────────────────────────────────────────────
# Parser CSV genérico
# ─────────────────────────────────────────────

def parsear_csv(archivo_bytes: bytes, nombre_archivo: str = "") -> ResultadoImportacion:
    """Detecta el banco y enruta al parser correcto."""
    try:
        texto = decodificar(archivo_bytes)
    except ValueError:
        r = ResultadoImportacion()
        r.errores.append("No se pudo leer el archivo CSV.")
        return r

    banco = detectar_banco(texto[:600], nombre_archivo)

    if banco == "Global66":
        return parsear_global66(archivo_bytes, nombre_archivo)

    # CSV genérico
    resultado = ResultadoImportacion()
    resultado.banco_detectado = banco

    try:
        dialect = csv.Sniffer().sniff(texto[:2000], delimiters=",;\t|")
        reader = csv.reader(io.StringIO(texto), dialect)
    except Exception:
        reader = csv.reader(io.StringIO(texto))

    todas_filas = list(reader)
    resultado.total_filas_archivo = len(todas_filas)

    fila_enc_idx = None
    mapa_columnas = {}
    for i, fila in enumerate(todas_filas):
        if es_fila_encabezado(fila):
            mapa = detectar_columnas(fila)
            if "fecha" in mapa:
                fila_enc_idx = i
                mapa_columnas = mapa
                break

    if not mapa_columnas:
        resultado.errores.append("No se detectaron columnas en el CSV.")
        return resultado

    for i, fila in enumerate(todas_filas[fila_enc_idx + 1:], fila_enc_idx + 2):
        if not any(fila):
            continue
        fecha = parse_fecha(fila[mapa_columnas["fecha"]] if len(fila) > mapa_columnas.get("fecha", 99) else None)
        if fecha is None:
            continue
        desc_idx = mapa_columnas.get("descripcion")
        descripcion = fila[desc_idx].strip() if desc_idx is not None and len(fila) > desc_idx else "Movimiento bancario"
        cargo_idx = mapa_columnas.get("cargo")
        abono_idx = mapa_columnas.get("abono")
        cargo = parse_monto(fila[cargo_idx]) if cargo_idx is not None and len(fila) > cargo_idx else Decimal("0")
        abono = parse_monto(fila[abono_idx]) if abono_idx is not None and len(fila) > abono_idx else Decimal("0")
        if cargo == 0 and abono == 0:
            continue
        resultado.filas.append(FilaCartola(
            fecha=fecha, descripcion=descripcion,
            cargo=cargo, abono=abono, saldo=None, fila_origen=i,
        ))

    resultado.total_filas_validas = len(resultado.filas)
    return resultado


def _detectar_columnas_heuristico(todas_filas) -> Tuple[dict, int]:
    for i, fila in enumerate(todas_filas):
        for j, celda in enumerate(fila):
            if parse_fecha(celda) is not None:
                return {"fecha": j, "descripcion": j+2, "cargo": j+3, "abono": j+4, "saldo": j+5}, i
    return {}, 0


# ─────────────────────────────────────────────
# Clasificador genérico
# ─────────────────────────────────────────────

REGLAS_CLASIFICACION = [
    (["abono transferencia", "transferencia recibida", "deposito", "depósito",
      "venta", "factura", "boleta", "cobranza", "pago de cliente",
      "conversion de divisas", "conversión"], "ingreso_banco"),
    (["remuneracion", "remuneración", "sueldo", "salario",
      "liquidacion nomina", "pago personal", "planilla"], "remuneracion"),
    (["sii", "impuesto", "iva mensual", "renta", "patente",
      "contribucion", "contribución", "tesoreria", "tesorería"], "impuesto"),
    (["cuota prestamo", "cuota préstamo", "credito hipotecario",
      "leasing", "dividendo hipotecario"], "pago_prestamo"),
    (["comision", "comisión", "mantencion", "mantención",
      "cargo banco", "costo cuenta", "seguro"], "egreso_banco"),
    (["cheque", "pago cheque"], "egreso_banco"),
]


def clasificar_movimiento(descripcion: str, es_cargo: bool, tipo_banco: str = "") -> Optional[str]:
    if tipo_banco:
        resultado = clasificar_global66(tipo_banco, descripcion, es_cargo)
        if resultado is not None:
            return resultado

    desc = descripcion.lower()
    for palabras, tipo in REGLAS_CLASIFICACION:
        if any(p in desc for p in palabras):
            return tipo

    return "egreso_banco" if es_cargo else "ingreso_banco"


def convertir_a_movimientos(resultado: ResultadoImportacion) -> list:
    movimientos = []
    for fila in resultado.filas:
        es_cargo = fila.cargo > 0
        tipo = clasificar_movimiento(fila.descripcion, es_cargo, fila.tipo_banco)
        if tipo is None:
            continue  # fila ignorada (ej: saldo inicial)

        monto = fila.cargo if es_cargo else fila.abono
        nota_doc  = f" | Doc: {fila.documento}" if fila.documento else ""
        nota_tipo = f" | Tipo: {fila.tipo_banco}" if fila.tipo_banco else ""

        movimientos.append({
            "fecha": fila.fecha,
            "tipo": tipo,
            "descripcion": fila.descripcion[:250],
            "monto": monto,
            "medio_pago": "transferencia",
            "notas": f"Importado desde {resultado.banco_detectado}{nota_tipo}{nota_doc}",
        })
    return movimientos
