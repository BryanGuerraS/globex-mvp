"""Motor de cálculo determinístico de cotizaciones para Globex Courier.

Fórmula del Excel de cotización de Globex (hoja COURIER, adoptada el 13/11/2026):
  precio        = precio unitario × cantidad
  TAX de tienda = 7 % del precio si no se conoce (0 si no aplica, p. ej. Amazon/eBay con almacén Globex)
  boleta        = precio + TAX de tienda (el envío dentro de EE. UU. queda fuera del alcance)
  tributos      = 24 % de la boleta si la boleta es de USD 200 o más
  total         = boleta + flete + trámite aduanero + tributos
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Optional

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
    TRAMITE_ADUANERO: float = 9.0  # USD 9 tarifa fija de desaduanaje (confirmado 13/11; el USD 7 del Excel era una prueba)
    # 24 % de la boleta (producto + TAX), como el Excel de cotización (13/11/2026); antes 22.72 % sobre CIF
    TASA_IMPUESTO_SUNAT: float = 0.24
    UMBRAL_EXONERACION_SUNAT: float = 200.0  # Boleta menor a USD 200: sin tributos (Excel: IF(boleta<200, 0, ...))
    TASA_TAX_TIENDA: float = 0.07  # TAX de referencia si el cliente no conoce el de su compra
    PESO_MINIMO_KG: float = 1.0  # Bajo 1 kg se cobra 1 kg; desde ahí, proporcional
    # Por encima, cotiza un asesor. USD 2 000 desde el 13/11/2026 (decisión del usuario, alineada con la
    # base de conocimiento del equipo); antes USD 1 200. Se aplica a la boleta (producto + TAX de tienda).
    LIMITE_COTIZACION_AUTOMATICA: float = 2000.0

    @classmethod
    def _tax(cls, valor: Decimal, tax_tienda: Optional[float]) -> Decimal:
        """TAX que indicó el cliente (0 si no aplica) o, si es None, el 7 % de referencia."""
        if tax_tienda is None:
            return _centavos(valor * _dec(cls.TASA_TAX_TIENDA))
        return _centavos(_dec(tax_tienda))

    @classmethod
    def requiere_asesor(
        cls, valor_producto: float, tax_tienda: Optional[float] = None, cantidad: int = 1
    ) -> bool:
        """True si la boleta (producto + TAX) supera el límite del cálculo automático."""
        valor = _dec(valor_producto) * _dec(cantidad)
        return valor + cls._tax(valor, tax_tienda) > _dec(cls.LIMITE_COTIZACION_AUTOMATICA)

    @classmethod
    def calcular(
        cls, valor_producto: float, peso_kg: float, tax_tienda: Optional[float] = None, cantidad: int = 1
    ) -> Dict[str, float]:
        """Calcula el desglose de la importación.

        valor_producto: precio de una unidad; cantidad: unidades (el precio es valor × cantidad).
        peso_kg: peso total del envío.

        tax_tienda: TAX de la tienda en USD si se conoce (0 si no aplica: Amazon/eBay con
        almacén Globex o precio con TAX incluido); None = 7 % de referencia.
        """
        unitario, peso = _dec(valor_producto), _dec(peso_kg)
        if unitario < 0 or peso <= 0:
            raise ValueError(
                "El valor del producto y el peso deben ser mayores a cero."
            )
        if int(cantidad) != cantidad or cantidad < 1:
            raise ValueError("La cantidad debe ser un entero mayor o igual a 1.")
        cantidad = int(cantidad)
        valor = unitario * cantidad
        if tax_tienda is not None and _dec(tax_tienda) < 0:
            raise ValueError("El TAX de la tienda no puede ser negativo.")

        # 1. Boleta de la tienda (producto + TAX)
        tax = cls._tax(valor, tax_tienda)
        boleta = valor + tax

        # 2. Costo de flete y envío (con peso mínimo facturable)
        peso_facturable = max(peso, _dec(cls.PESO_MINIMO_KG))
        costo_flete = _centavos(peso_facturable * _dec(cls.FLETE_POR_KG))
        costo_envio = _centavos(costo_flete + _dec(cls.TRAMITE_ADUANERO))

        # 3. Tributos de importación: 24 % de la boleta (sin flete ni trámite)
        aplica_impuesto = boleta >= _dec(cls.UMBRAL_EXONERACION_SUNAT)
        tributos = (
            _centavos(boleta * _dec(cls.TASA_IMPUESTO_SUNAT))
            if aplica_impuesto
            else Decimal("0")
        )

        # 4. Costo total de la operación
        costo_total = _centavos(boleta + costo_envio + tributos)

        return {
            "valor_producto": valor_producto if cantidad == 1 else float(valor),
            "precio_unitario": valor_producto,
            "cantidad": cantidad,
            "tax_tienda": float(tax),
            "tax_estimado": tax_tienda is None,
            "boleta": float(boleta),
            "peso_kg": peso_kg,
            "peso_facturable_kg": float(peso_facturable),
            "costo_flete": float(costo_flete),
            "costo_envio": float(costo_envio),
            "tributos_aprox": float(tributos),
            "costo_total": float(costo_total),
            "aplica_impuesto": aplica_impuesto,
        }

    @staticmethod
    def detalle_tax(calculo: Dict[str, float]) -> str:
        """Aclaración del TAX: estimado 7 %, no aplica, o ninguna si lo indicó el cliente."""
        if calculo.get("tax_estimado", True):
            return "estimado 7 %"
        return "" if calculo.get("tax_tienda") else "no aplica"


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
        detalle_tax = cls.detalle_tax(calculo)
        cantidad = calculo.get("cantidad", 1)
        lineas_cantidad = (
            f"• *Valor unitario:* USD {calculo['precio_unitario']:,.2f}\n"
            f"• *Cantidad:* {cantidad}\n"
            if cantidad > 1 else ""
        )
        msg = (
            f"📦 *COTIZACIÓN ESTIMADA GLOBEX*\n"
            f"────────────────────────\n"
            + lineas_cantidad
            + f"• *{'Total' if cantidad > 1 else 'Costo del Producto'}:* USD {calculo['valor_producto']:,.2f}\n"
            f"• *TAX de la tienda:* USD {calculo.get('tax_tienda', 0):,.2f}"
            + (f" ({detalle_tax})" if detalle_tax else "") + "\n"
            f"• *Flete aéreo:* USD {flete:,.2f} ({detalle_peso})\n"
            f"• *Trámite aduanero:* USD {tramite:,.2f}\n"
        )

        if calculo["aplica_impuesto"]:
            msg += (
                f"• *Tributos SUNAT aprox.:* USD {calculo['tributos_aprox']:,.2f} (24 % de producto + TAX)\n"
                f"────────────────────────\n"
                f"💰 *TOTAL ESTIMADO:* USD {calculo['costo_total']:,.2f}\n\n"
            )
        else:
            msg += (
                f"• *Tributos SUNAT:* USD 0.00 (exonerado: producto + TAX menor a USD 200)\n"
                f"────────────────────────\n"
                f"💰 *TOTAL ESTIMADO:* USD {calculo['costo_total']:,.2f}\n\n"
            )

        msg += (
            f"⚠️ *Nota importante:* Este cálculo es referencial y automático. "
            f"Un asesor de Globex revisará tu orden para confirmar los montos finales antes de procesar la compra."
        )
        return msg
