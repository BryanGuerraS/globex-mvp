"""Motor de cálculo determinístico de cotizaciones para Globex Courier.

Fórmulas basadas en la calculadora oficial y normativa aduanera SUNAT.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Dict

_CENTAVO = Decimal("0.01")


def _dec(valor) -> Decimal:
    """Convierte sin arrastrar el error binario del float (1.005 -> Decimal('1.005'))."""
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def _centavos(valor: Decimal) -> Decimal:
    """Redondeo comercial a 2 decimales (9.045 -> 9.05)."""
    return valor.quantize(_CENTAVO, rounding=ROUND_HALF_UP)


class GlobexPricingEngine:
    """Las cuentas se hacen en Decimal; el resultado se devuelve en float (JSON, SQLite)."""

    FLETE_POR_KG: float = 9.0  # USD 9 por kilo
    TRAMITE_ADUANERO: float = 9.0  # USD 9 tarifa fija de trámite
    TASA_IMPUESTO_SUNAT: float = 0.2271957  # ~22.72 % (simulador web de Globex)
    UMBRAL_EXONERACION_SUNAT: float = 200.0  # Hasta USD 200 no pagan tributos
    PESO_MINIMO_KG: float = 1.0  # Bajo 1 kg se cobra 1 kg; desde ahí, proporcional
    LIMITE_COTIZACION_AUTOMATICA: float = 1200.0  # Por encima, cotiza un asesor

    @classmethod
    def requiere_asesor(cls, valor_producto: float) -> bool:
        """True si el valor supera el límite del cálculo automático."""
        return _dec(valor_producto) > _dec(cls.LIMITE_COTIZACION_AUTOMATICA)

    @classmethod
    def calcular(cls, valor_producto: float, peso_kg: float) -> Dict[str, float]:
        """Calcula el desglose financiero exacto de la importación."""
        valor, peso = _dec(valor_producto), _dec(peso_kg)
        if valor < 0 or peso <= 0:
            raise ValueError(
                "El valor del producto y el peso deben ser mayores a cero."
            )

        # 1. Costo de flete y envío (con peso mínimo facturable)
        peso_facturable = max(peso, _dec(cls.PESO_MINIMO_KG))
        costo_flete = _centavos(peso_facturable * _dec(cls.FLETE_POR_KG))
        costo_envio = _centavos(costo_flete + _dec(cls.TRAMITE_ADUANERO))

        # 2. Tributos e impuestos de importación (sobre CIF = valor + envío)
        aplica_impuesto = valor > _dec(cls.UMBRAL_EXONERACION_SUNAT)
        tributos = (
            _centavos((valor + costo_envio) * _dec(cls.TASA_IMPUESTO_SUNAT))
            if aplica_impuesto
            else Decimal("0")
        )

        # 3. Costo total de la operación
        costo_total = _centavos(valor + costo_envio + tributos)

        return {
            "valor_producto": valor_producto,
            "peso_kg": peso_kg,
            "peso_facturable_kg": float(peso_facturable),
            "costo_flete": float(costo_flete),
            "costo_envio": float(costo_envio),
            "tributos_aprox": float(tributos),
            "costo_total": float(costo_total),
            "aplica_impuesto": aplica_impuesto,
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
            f"• *Costo del Producto:* USD {calculo['valor_producto']:,.2f}\n"
            f"• *Flete aéreo:* USD {flete:,.2f} ({detalle_peso})\n"
            f"• *Trámite aduanero:* USD {tramite:,.2f}\n"
        )

        if calculo["aplica_impuesto"]:
            msg += (
                f"• *Tributos SUNAT aprox.:* USD {calculo['tributos_aprox']:,.2f} (aplica por superar USD 200)\n"
                f"────────────────────────\n"
                f"💰 *TOTAL ESTIMADO:* USD {calculo['costo_total']:,.2f}\n\n"
            )
        else:
            msg += (
                f"• *Tributos SUNAT:* USD 0.00 (exonerado hasta USD 200)\n"
                f"────────────────────────\n"
                f"💰 *TOTAL ESTIMADO:* USD {calculo['costo_total']:,.2f}\n\n"
            )

        msg += (
            f"⚠️ *Nota importante:* Este cálculo es referencial y automático. "
            f"Un asesor de Globex revisará tu orden para confirmar los montos finales antes de procesar la compra."
        )
        return msg