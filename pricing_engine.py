"""Motor de cálculo determinístico de cotizaciones para Globex Courier.

Fórmulas basadas en la calculadora oficial y normativa aduanera SUNAT.
"""

from typing import Dict


class GlobexPricingEngine:
    FLETE_POR_KG: float = 9.0  # $9 por kilo
    TRAMITE_ADUANERO: float = 9.0  # $9 tarifa fija de trámite
    TASA_IMPUESTO_SUNAT: float = 0.2271957  # ~22.72% (Ad-Valorem 4% + IGV/IPM 18%)
    UMBRAL_EXONERACION_SUNAT: float = 200.0  # Menores a $200 no pagan tributos

    @classmethod
    def calcular(cls, valor_producto: float, peso_kg: float) -> Dict[str, float]:
        """Calcula el desglose financiero exacto de la importación."""
        if valor_producto < 0 or peso_kg <= 0:
            raise ValueError(
                "El valor del producto y el peso deben ser mayores a cero."
            )

        # 1. Costo de flete y envío
        costo_flete = round(peso_kg * cls.FLETE_POR_KG, 2)
        costo_envio = round(costo_flete + cls.TRAMITE_ADUANERO, 2)

        # 2. Tributos e impuestos de importación
        if valor_producto <= cls.UMBRAL_EXONERACION_SUNAT:
            tributos = 0.0
        else:
            base_cif = valor_producto + costo_envio
            tributos = round(base_cif * cls.TASA_IMPUESTO_SUNAT, 2)

        # 3. Costo total de la operación
        costo_total = round(valor_producto + costo_envio + tributos, 2)

        return {
            "valor_producto": valor_producto,
            "peso_kg": peso_kg,
            "costo_envio": costo_envio,
            "tributos_aprox": tributos,
            "costo_total": costo_total,
            "aplica_impuesto": valor_producto > cls.UMBRAL_EXONERACION_SUNAT,
        }

    @classmethod
    def formatear_mensaje_whatsapp(cls, calculo: Dict[str, float]) -> str:
        """Genera el mensaje con formato ejecutivo y disclaimer para WhatsApp."""
        msg = (
            f"📦 *COTIZACIÓN ESTIMADA GLOBEX*\n"
            f"────────────────────────\n"
            f"• *Costo del Producto:* ${calculo['valor_producto']:,.2f} USD\n"
            f"• *Costo de Envío:* ${calculo['costo_envio']:,.2f} USD ({calculo['peso_kg']} kg)\n"
        )

        if calculo["aplica_impuesto"]:
            msg += (
                f"• *Tributos SUNAT Aprox:* ${calculo['tributos_aprox']:,.2f} USD (Aplica por superar $200)\n"
                f"────────────────────────\n"
                f"💰 *TOTAL ESTIMADO:* ${calculo['costo_total']:,.2f} USD\n\n"
            )
        else:
            msg += (
                f"• *Tributos SUNAT:* $0.00 USD (Exonerado por ser ≤ $200)\n"
                f"────────────────────────\n"
                f"💰 *TOTAL ESTIMADO:* ${calculo['costo_total']:,.2f} USD\n\n"
            )

        msg += (
            f"⚠️ *Nota importante:* Este cálculo es referencial y automático. "
            f"Un asesor de Globex revisará tu orden para confirmar los montos finales antes de procesar la compra."
        )
        return msg