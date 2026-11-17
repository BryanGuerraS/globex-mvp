"""Motor de cálculo determinístico de cotizaciones para Globex Courier.

Fórmula del Excel de cotización de Globex (hoja COURIER, adoptada el 13/11/2026):
  precio        = precio unitario × cantidad
  TAX de tienda = 7 % del precio si no se conoce (0 si el precio ya lo incluye, en cualquier tienda)
  boleta        = precio + TAX de tienda (el envío dentro de EE. UU. queda fuera del alcance)
  tributos      = 24 % de la boleta si la boleta es de USD 200 o más
  total         = boleta + flete + trámite aduanero + tributos
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional

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

        tax_tienda: TAX de la tienda en USD si se conoce (0 si el precio ya lo incluye o la
        tienda no lo cobra); None = 7 % de referencia.
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

    @classmethod
    def _lineas(cls, productos: List[Dict]) -> List[Dict]:
        """Valida cada producto y calcula su precio, TAX y precio total (en Decimal)."""
        if not productos:
            raise ValueError("La cotización necesita al menos un producto.")
        lineas = []
        for p in productos:
            unitario = _dec(p["precio_unitario"])
            cantidad = p.get("cantidad") or 1
            if unitario <= 0:
                raise ValueError("El precio de cada producto debe ser mayor a cero.")
            if int(cantidad) != cantidad or cantidad < 1:
                raise ValueError("La cantidad debe ser un entero mayor o igual a 1.")
            tax_dado = p.get("tax")
            if tax_dado is not None and _dec(tax_dado) < 0:
                raise ValueError("El TAX de la tienda no puede ser negativo.")
            if p.get("peso_kg") is not None and _dec(p["peso_kg"]) <= 0:
                raise ValueError("El peso de cada producto debe ser mayor a cero.")
            valor = unitario * int(cantidad)
            tax = cls._tax(valor, tax_dado)
            lineas.append({"p": p, "cantidad": int(cantidad), "valor": valor, "tax": tax, "total": valor + tax})
        return lineas

    @classmethod
    def requiere_asesor_pedido(cls, productos: List[Dict]) -> bool:
        """True si la suma de los precios totales (producto + TAX) supera el límite automático."""
        return sum(l["total"] for l in cls._lineas(productos)) > _dec(cls.LIMITE_COTIZACION_AUTOMATICA)

    @classmethod
    def calcular_pedido(cls, productos: List[Dict], peso_total_kg: Optional[float] = None) -> Dict:
        """Cotización de uno o varios productos, de una o varias tiendas (reglas del 14/11/2026).

        productos: [{"producto", "tienda", "precio_unitario", "cantidad", "peso_kg", "tax"}];
        tax None = 7 % de referencia (el precio no incluye TAX), 0 = incluido en el precio.
        peso_total_kg: si el cliente dio un solo peso para todo; si no, la suma de los pesos.

        Todo el pedido va en una guía: flete sobre el peso total (mínimo 1 kg), un solo trámite
        aduanero y tributos del 24 % sobre la suma de los precios totales si llega a USD 200.
        """
        lineas = cls._lineas(productos)
        if peso_total_kg is not None:
            peso = _dec(peso_total_kg)
        elif all(l["p"].get("peso_kg") is not None for l in lineas):
            peso = sum(_dec(l["p"]["peso_kg"]) for l in lineas)
        else:
            raise ValueError("Falta el peso de algún producto.")
        if peso <= 0:
            raise ValueError("El peso debe ser mayor a cero.")

        valor = sum(l["valor"] for l in lineas)
        tax = sum(l["tax"] for l in lineas)
        boleta = valor + tax
        peso_facturable = max(peso, _dec(cls.PESO_MINIMO_KG))
        costo_flete = _centavos(peso_facturable * _dec(cls.FLETE_POR_KG))
        costo_envio = _centavos(costo_flete + _dec(cls.TRAMITE_ADUANERO))
        aplica_impuesto = boleta >= _dec(cls.UMBRAL_EXONERACION_SUNAT)
        tributos = _centavos(boleta * _dec(cls.TASA_IMPUESTO_SUNAT)) if aplica_impuesto else Decimal("0")
        costo_total = _centavos(boleta + costo_envio + tributos)

        uno = lineas[0] if len(lineas) == 1 else None
        return {
            # Campos de siempre (para un producto coinciden con calcular())
            "valor_producto": float(valor) if not uno or uno["cantidad"] > 1 else uno["p"]["precio_unitario"],
            "precio_unitario": uno["p"]["precio_unitario"] if uno else None,
            "cantidad": uno["cantidad"] if uno else sum(l["cantidad"] for l in lineas),
            "tax_tienda": float(tax),
            "tax_estimado": any(l["p"].get("tax") is None for l in lineas) if uno else None,
            "boleta": float(boleta),
            "peso_kg": float(peso) if peso_total_kg is None or uno is None else peso_total_kg,
            "peso_facturable_kg": float(peso_facturable),
            "costo_flete": float(costo_flete),
            "costo_envio": float(costo_envio),
            "tributos_aprox": float(tributos),
            "costo_total": float(costo_total),
            "aplica_impuesto": aplica_impuesto,
            # Detalle por producto (pedidos de varios productos)
            "productos": [{
                "producto": l["p"].get("producto") or f"Producto {i}",
                "tienda": l["p"].get("tienda") or "",
                "precio_unitario": float(_dec(l["p"]["precio_unitario"])),
                "cantidad": l["cantidad"],
                "peso_kg": float(_dec(l["p"]["peso_kg"])) if l["p"].get("peso_kg") is not None else None,
                "valor": float(l["valor"]),
                "tax": float(l["tax"]),
                "tax_estimado": l["p"].get("tax") is None,
                "total": float(l["total"]),
            } for i, l in enumerate(lineas, 1)],
        }

    @staticmethod
    def detalle_tax(calculo: Dict[str, float]) -> str:
        """Aclaración del TAX: estimado 7 %, no aplica, o ninguna si lo indicó el cliente."""
        if calculo.get("tax_estimado", True):
            return "estimado 7 %"
        return "" if calculo.get("tax_tienda") else "incluido en el precio"


    @classmethod
    def formatear_mensaje_whatsapp(cls, calculo: Dict[str, float]) -> str:
        """Genera el mensaje con formato ejecutivo y disclaimer para WhatsApp."""
        if len(calculo.get("productos") or []) > 1:
            return cls.formatear_pedido_whatsapp(calculo)
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

    @staticmethod
    def linea_producto(p: Dict) -> str:
        """'2 × USD 20.00 + TAX USD 2.80 (estimado 7 %) · 1 kg' para un producto del pedido."""
        precio = (f"{p['cantidad']} × USD {p['precio_unitario']:,.2f}" if p["cantidad"] > 1
                  else f"USD {p['valor']:,.2f}")
        if p["tax_estimado"]:
            tax = f" + TAX USD {p['tax']:,.2f} (estimado 7 %)"
        elif p["tax"]:
            tax = f" + TAX USD {p['tax']:,.2f}"
        else:
            tax = " · TAX incluido"
        peso = f" · {p['peso_kg']:g} kg" if p.get("peso_kg") is not None else ""
        return precio + tax + peso

    @classmethod
    def formatear_pedido_whatsapp(cls, calculo: Dict) -> str:
        """Cotización de varios productos (formato aprobado por el usuario el 14/11/2026)."""
        lineas = ["📦 *COTIZACIÓN ESTIMADA GLOBEX*", "────────────────────────"]
        for i, p in enumerate(calculo["productos"], 1):
            nombre = p["producto"] + (f" ({p['tienda']})" if p.get("tienda") else "")
            lineas += [f"*{i}. {nombre}* · {cls.linea_producto(p)}", f"   USD {p['total']:,.2f}"]
        peso, peso_fact = calculo["peso_kg"], calculo["peso_facturable_kg"]
        detalle_peso = f"{peso:g} kg" if peso_fact == peso else f"{peso:g} kg, se cobra el mínimo de {peso_fact:g} kg"
        tramite = round(calculo["costo_envio"] - calculo["costo_flete"], 2)
        lineas += [
            "────────────────────────",
            f"• *Productos con TAX:* USD {calculo['boleta']:,.2f}",
            f"• *Flete aéreo:* USD {calculo['costo_flete']:,.2f} ({detalle_peso})",
            f"• *Desaduanaje:* USD {tramite:,.2f}",
            (f"• *Tributos SUNAT aprox.:* USD {calculo['tributos_aprox']:,.2f} (24 % de productos + TAX)"
             if calculo["aplica_impuesto"] else
             "• *Tributos SUNAT:* USD 0.00 (exonerado: productos con TAX menor a USD 200)"),
            "────────────────────────",
            f"💰 *TOTAL ESTIMADO:* USD {calculo['costo_total']:,.2f}",
            "",
        ]
        estimados = [p["producto"] for p in calculo["productos"] if p["tax_estimado"]]
        if estimados:
            lineas.append(f"Estimado: el TAX de {', '.join(estimados)} (7 %). Los pesos se confirman en Miami.")
        else:
            lineas.append("Los pesos se confirman en Miami.")
        lineas.append(
            "⚠️ *Nota importante:* Este cálculo es referencial y automático. "
            "Un asesor de Globex revisará tu orden para confirmar los montos finales antes de procesar la compra."
        )
        return "\n".join(lineas)
