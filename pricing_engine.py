"""Motor de cálculo determinístico de cotizaciones para Globex Courier.

Fórmulas basadas en la calculadora oficial y normativa aduanera SUNAT.
"""

from typing import Dict


class GlobexPricingEngine:
    FLETE_POR_KG: float = 9.0  # $9 por kilo
    TRAMITE_ADUANERO: float = 9.0  # $9 tarifa fija de trámite
    TASA_IMPUESTO_SUNAT: float = 0.2271957  # ~22.72% (Ad-Valorem 4% + IGV/IPM 18%)
    UMBRAL_EXONERACION_SUNAT: float = 200.0  # Menores a $200 no pagan tributos
    PESO_MINIMO_KG: float = 1.0  # Bajo 1 kg se cobra 1 kg; desde ahí, proporcional
    LIMITE_COTIZACION_AUTOMATICA: float = 1200.0  # Por encima, cotiza un asesor

    @classmethod
    def requiere_asesor(cls, valor_producto: float) -> bool:
        """True si el valor supera el límite del cálculo automático."""
        return valor_producto > cls.LIMITE_COTIZACION_AUTOMATICA

    @classmethod
    def calcular(cls, valor_producto: float, peso_kg: float) -> Dict[str, float]:
        """Calcula el desglose financiero exacto de la importación."""
        if valor_producto < 0 or peso_kg <= 0:
            raise ValueError(
                "El valor del producto y el peso deben ser mayores a cero."
            )

        # 1. Costo de flete y envío (con peso mínimo facturable)
        peso_facturable = max(peso_kg, cls.PESO_MINIMO_KG)
        costo_flete = round(peso_facturable * cls.FLETE_POR_KG, 2)
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
            "peso_facturable_kg": peso_facturable,
            "costo_flete": costo_flete,
            "costo_envio": costo_envio,
            "tributos_aprox": tributos,
            "costo_total": costo_total,
            "aplica_impuesto": valor_producto > cls.UMBRAL_EXONERACION_SUNAT,
        }

    @classmethod
    def formatear_mensaje_whatsapp(cls, calculo: Dict[str, float]) -> str:
        """Genera el mensaje con formato ejecutivo y disclaimer para WhatsApp."""
        peso = calculo["peso_kg"]
        peso_facturable = calculo.get("peso_facturable_kg", peso)
        detalle_peso = (
            f"{peso} kg"
            if peso_facturable == peso
            else f"{peso} kg, se cobra el mínimo de {peso_facturable:g} kg"
        )
        flete = calculo.get("costo_flete", round(peso_facturable * cls.FLETE_POR_KG, 2))
        tramite = round(calculo["costo_envio"] - flete, 2)
        msg = (
            f"📦 *COTIZACIÓN ESTIMADA GLOBEX*\n"
            f"────────────────────────\n"
            f"• *Costo del Producto:* ${calculo['valor_producto']:,.2f} USD\n"
            f"• *Flete aéreo:* ${flete:,.2f} USD ({detalle_peso})\n"
            f"• *Trámite aduanero:* ${tramite:,.2f} USD\n"
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