"""Generador oficial de Proformas y Cotizaciones en PDF para Globex Courier."""

from datetime import datetime
import os
from typing import Dict
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# Carpeta donde se guardarán los PDFs generados
PDF_DIR = "cotizaciones_pdf"
os.makedirs(PDF_DIR, exist_ok=True)


def generar_pdf_cotizacion(chat_id: str, nombre_cliente: str, calculo: Dict[str, float]) -> str:
    """Genera un archivo PDF corporativo con el desglose oficial de Globex y devuelve la ruta."""
    numero_limpio = chat_id.replace("@c.us", "")
    fecha_hoy = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_archivo = f"Proforma_Globex_{numero_limpio}_{fecha_hoy}.pdf"
    ruta_completa = os.path.join(PDF_DIR, nombre_archivo)

    doc = SimpleDocTemplate(
        ruta_completa,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    elementos = []

    # 1. Cabecera Corporativa
    titulo_style = ParagraphStyle(
        'TituloGlobex',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        textColor=colors.HexColor("#1A2B4C"),
        spaceAfter=4
    )
    subtitulo_style = ParagraphStyle(
        'SubtituloGlobex',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.HexColor("#555555")
    )

    elementos.append(Paragraph("📦 GLOBEX COURIER PERÚ", titulo_style))
    elementos.append(Paragraph("Importaciones y Envíos de USA a Perú | Miami - Lima", subtitulo_style))
    elementos.append(Spacer(1, 15))

    # 2. Datos del Documento y Cliente
    codigo_proforma = f"GX-{datetime.now().strftime('%y%m')}-{numero_limpio[-4:]}"
    fecha_emision = datetime.now().strftime("%d/%m/%Y %H:%M")

    datos_cliente = [
        [
            Paragraph(f"<b>N° Proforma:</b> {codigo_proforma}", styles['Normal']),
            Paragraph(f"<b>Fecha:</b> {fecha_emision}", styles['Normal'])
        ],
        [
            Paragraph(f"<b>Cliente:</b> {nombre_cliente}", styles['Normal']),
            Paragraph(f"<b>Teléfono:</b> +{numero_limpio}", styles['Normal'])
        ],
        [
            Paragraph("<b>Ruta:</b> Miami (Doral) ➔ Lima, Perú", styles['Normal']),
            Paragraph("<b>Modalidad:</b> Courier Aéreo Estándar", styles['Normal'])
        ]
    ]

    t_cliente = Table(datos_cliente, colWidths=[270, 270])
    t_cliente.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F4F6F9")),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#D1D5DB")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elementos.append(t_cliente)
    elementos.append(Spacer(1, 20))

    # 3. Tabla de Desglose Financiero y Aduanero
    val_prod = calculo.get("valor_producto", 0.0)
    peso = calculo.get("peso_kg", 0.0)
    flete = round(peso * 9.0, 2)
    tramite = 9.0
    tributos = calculo.get("tributos_aprox", 0.0)
    total = calculo.get("costo_total", 0.0)

    tabla_cotizacion = [
        ["CONCEPTO", "DETALLE / TASA", "IMPORTE (USD)"],
        ["Valor Declarado del Producto (FOB)", f"Mercancía declarada ({peso} kg)", f"$ {val_prod:,.2f}"],
        ["Flete Aéreo Internacional", f"{peso} kg × $9.00 USD/kg", f"$ {flete:,.2f}"],
        ["Trámite y Manejo Documentario", "Tarifa fija de almacén y guía", f"$ {tramite:,.2f}"],
    ]

    if calculo.get("aplica_impuesto", False):
        tabla_cotizacion.append([
            "Tributos de Importación SUNAT",
            "Aplica ~22.72% CIF (Valor > $200 USD)",
            f"$ {tributos:,.2f}"
        ])
    else:
        tabla_cotizacion.append([
            "Tributos de Importación SUNAT",
            "Exonerado por Ley (Valor ≤ $200 USD)",
            "$ 0.00"
        ])

    tabla_cotizacion.append([
        "TOTAL ESTIMADO DE LA OPERACIÓN",
        "Producto + Flete + Trámite + Impuestos",
        f"$ {total:,.2f}"
    ])

    t_calculo = Table(tabla_cotizacion, colWidths=[240, 180, 120])
    t_calculo.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1A2B4C")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -2), 0.5, colors.HexColor("#D1D5DB")),
        ('LINEBELOW', (0, -1), (-1, -1), 2, colors.HexColor("#1A2B4C")),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#EBF3FB")),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elementos.append(t_calculo)
    elementos.append(Spacer(1, 25))

    # 4. Términos Legales y Condiciones (Disclaimer del Manual)
    disclaimer_style = ParagraphStyle(
        'DisclaimerGlobex',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        textColor=colors.HexColor("#6B7280"),
        leading=11
    )
    disclaimer_text = (
        "<b>TÉRMINOS Y CONDICIONES DEL SERVICIO:</b><br/>"
        "1. Esta proforma es un cálculo preliminar referencial y no constituye una liquidación definitiva ni factura comercial.<br/>"
        "2. El peso facturable final será ratificado con el pesaje oficial en balanza a la llegada al almacén de Miami.<br/>"
        "3. Mercancías con baterías, cosméticos o restricciones sanitarias están sujetas a validación previa por el asesor asignado.<br/>"
        "4. Vigencia de esta cotización referencial: 48 horas a partir de su emisión."
    )
    elementos.append(Paragraph(disclaimer_text, disclaimer_style))

    doc.build(elementos)
    return ruta_completa