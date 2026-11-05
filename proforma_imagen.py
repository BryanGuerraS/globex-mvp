"""Proforma referencial como imagen PNG para enviarla por WhatsApp.

Todos los montos vienen del motor (`GlobexPricingEngine.calcular`); aquí no se
recalcula nada. Usa Bitstream Vera, la fuente que trae `reportlab` (ya es
dependencia del proyecto), así funciona igual en Windows y en Render sin
instalar fuentes y con tildes y ñ.
"""

import io
import os
from datetime import datetime
from typing import Dict, Optional

from PIL import Image, ImageDraw, ImageFont
import reportlab

_FUENTES = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
_LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo_globex.png")

ANCHO = 1080
MARGEN = 72
MORADO = (46, 26, 71)         # #2E1A47, morado del logo de Globex
MORADO_SUAVE = (243, 239, 250)
NARANJA = (255, 105, 0)       # #FF6900, naranja del logo
TEXTO = (24, 24, 27)
TEXTO_SUAVE = (113, 113, 122)
BORDE = (228, 228, 231)
BLANCO = (255, 255, 255)
VERDE = (21, 128, 61)

NOTA = (
    "Cálculo referencial y automático. Un asesor de Globex revisará tu orden para confirmar "
    "los montos finales antes de procesar la compra. El peso final se confirma con el pesaje "
    "en el almacén de Miami."
)


def _fuente(tamano: int, negrita: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(os.path.join(_FUENTES, "VeraBd.ttf" if negrita else "Vera.ttf"), tamano)


def _usd(valor: float) -> str:
    return f"US$ {valor:,.2f}"


def _kg(valor: float) -> str:
    return f"{valor:g} kg"


def _envolver(draw: ImageDraw.ImageDraw, texto: str, fuente, ancho_max: int):
    lineas, actual = [], ""
    for palabra in texto.split():
        prueba = f"{actual} {palabra}".strip()
        if draw.textlength(prueba, font=fuente) <= ancho_max:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def codigo_proforma(chat_id: str, ahora: Optional[datetime] = None) -> str:
    ahora = ahora or datetime.now()
    sufijo = "".join(c for c in str(chat_id) if c.isalnum())[-4:].upper()
    return f"GX-{ahora.strftime('%y%m')}-{sufijo}"


def generar_imagen_proforma(
    calculo: Dict,
    producto: Optional[str] = None,
    nombre_cliente: Optional[str] = None,
    chat_id: str = "",
    ahora: Optional[datetime] = None,
    peso_estimado: bool = False,
) -> bytes:
    """Devuelve la proforma como PNG (bytes)."""
    ahora = ahora or datetime.now()
    valor = float(calculo["valor_producto"])
    peso = float(calculo["peso_kg"])
    peso_fact = float(calculo.get("peso_facturable_kg", peso))
    flete = float(calculo.get("costo_flete", round(peso_fact * 9.0, 2)))
    envio = float(calculo["costo_envio"])
    tramite = round(envio - flete, 2)
    tributos = float(calculo.get("tributos_aprox", 0.0))
    total = float(calculo["costo_total"])

    filas = [
        ("Valor del producto", "Precio declarado", _usd(valor)),
        ("Flete aéreo", f"{_kg(peso_fact)} × US$ 9.00/kg"
         + (f" (mínimo 1 kg; peso {_kg(peso)})" if peso_fact != peso else ""), _usd(flete)),
        ("Trámite aduanero", "Tarifa fija", _usd(tramite)),
        ("Tributos SUNAT",
         "Aprox. 22.72 % del valor CIF" if calculo.get("aplica_impuesto") else "Exonerado: valor hasta US$ 200",
         _usd(tributos)),
    ]

    f_marca, f_sub = _fuente(44, negrita=True), _fuente(24)
    f_etiqueta, f_texto, f_detalle = _fuente(21), _fuente(30), _fuente(22)
    f_texto_neg = _fuente(30, negrita=True)
    f_total_et, f_total = _fuente(28, negrita=True), _fuente(58, negrita=True)
    f_nota = _fuente(20)

    medidor = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    nota_lineas = _envolver(medidor, NOTA, f_nota, ANCHO - 2 * MARGEN)
    alto = 1230 + 34 * len(nota_lineas)

    img = Image.new("RGB", (ANCHO, alto), BLANCO)
    d = ImageDraw.Draw(img)
    x0, x1 = MARGEN, ANCHO - MARGEN

    # Cabecera de marca: logo oficial a la izquierda, título a la derecha, franja naranja
    if os.path.exists(_LOGO):
        logo = Image.open(_LOGO).convert("RGBA")
        alto_logo = 132
        logo = logo.resize((round(logo.width * alto_logo / logo.height), alto_logo), Image.LANCZOS)
        img.paste(logo, (x0, 26), logo)
    else:
        d.text((x0, 64), "GLOBEX COURIER", font=f_marca, fill=MORADO)
    d.text((x1, 62), "PROFORMA", font=f_marca, fill=MORADO, anchor="ra")
    d.text((x1, 118), "Referencial · EE. UU. a Perú", font=f_sub, fill=TEXTO_SUAVE, anchor="ra")
    d.rectangle([0, 182, ANCHO, 190], fill=NARANJA)

    # Datos del documento
    y = 232
    d.text((x0, y), "N° DE PROFORMA", font=f_etiqueta, fill=TEXTO_SUAVE)
    d.text((x1, y), "FECHA DE EMISIÓN", font=f_etiqueta, fill=TEXTO_SUAVE, anchor="ra")
    y += 34
    d.text((x0, y), codigo_proforma(chat_id, ahora), font=f_texto, fill=TEXTO)
    d.text((x1, y), ahora.strftime("%d/%m/%Y %H:%M"), font=f_texto, fill=TEXTO, anchor="ra")
    y += 62
    d.text((x0, y), "CLIENTE", font=f_etiqueta, fill=TEXTO_SUAVE)
    d.text((x1, y), "VIGENCIA", font=f_etiqueta, fill=TEXTO_SUAVE, anchor="ra")
    y += 34
    d.text((x0, y), nombre_cliente or "—", font=f_texto, fill=TEXTO)
    d.text((x1, y), "24 horas", font=f_texto, fill=TEXTO, anchor="ra")

    # Producto
    y += 74
    d.rounded_rectangle([x0, y, x1, y + 120], radius=18, fill=(250, 250, 250), outline=BORDE, width=2)
    d.text((x0 + 32, y + 22), "PRODUCTO", font=f_etiqueta, fill=TEXTO_SUAVE)
    nombre_producto = (producto or "Producto declarado").strip()
    peso_txt = f"~{_kg(peso)} (estimado)" if peso_estimado else _kg(peso)
    ancho_producto = (x1 - 32) - (x0 + 32) - d.textlength(peso_txt, font=f_texto) - 40
    while d.textlength(nombre_producto, font=f_texto_neg) > ancho_producto and len(nombre_producto) > 4:
        nombre_producto = nombre_producto[:-2].rstrip() + "…"
    d.text((x0 + 32, y + 56), nombre_producto, font=f_texto_neg, fill=TEXTO)
    d.text((x1 - 32, y + 56), peso_txt, font=f_texto, fill=TEXTO, anchor="ra")

    # Desglose
    y += 164
    for concepto, detalle, monto in filas:
        d.text((x0, y), concepto, font=f_texto, fill=TEXTO)
        d.text((x1, y), monto, font=f_texto, fill=TEXTO, anchor="ra")
        d.text((x0, y + 42), detalle, font=f_detalle, fill=TEXTO_SUAVE)
        y += 98
        d.line([x0, y - 18, x1, y - 18], fill=BORDE, width=2)

    # Total
    y += 10
    d.rounded_rectangle([x0, y, x1, y + 140], radius=22, fill=MORADO_SUAVE)
    d.text((x0 + 36, y + 70), "TOTAL ESTIMADO", font=f_total_et, fill=MORADO, anchor="lm")
    d.text((x1 - 36, y + 70), _usd(total), font=f_total, fill=MORADO, anchor="rm")

    # Nota
    y += 186
    for linea in nota_lineas:
        d.text((x0, y), linea, font=f_nota, fill=TEXTO_SUAVE)
        y += 34

    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
