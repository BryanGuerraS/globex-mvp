"""Catálogo de referencia de pesos y especificaciones para Globex Courier.

Permite recuperar el peso aproximado con caja (packaging) de los productos más
importados para evitar fricción con el cliente.
"""

from typing import Dict, Optional

# Base de conocimiento curada de artículos frecuentes de importación USA -> Perú
PRODUCT_CATALOG = {
    # Celulares (peso con caja, cable y empaque de envío)
    "iphone 15 pro max": {
        "peso_kg": 0.45,
        "categoria": "Celulares",
        "descripcion": "iPhone 15 Pro Max con caja original",
    },
    "iphone 15 pro": {
        "peso_kg": 0.40,
        "categoria": "Celulares",
        "descripcion": "iPhone 15 Pro con caja original",
    },
    "iphone 15": {
        "peso_kg": 0.38,
        "categoria": "Celulares",
        "descripcion": "iPhone 15 con caja original",
    },
    "iphone 14 pro max": {
        "peso_kg": 0.48,
        "categoria": "Celulares",
        "descripcion": "iPhone 14 Pro Max con caja",
    },
    "samsung galaxy s24 ultra": {
        "peso_kg": 0.45,
        "categoria": "Celulares",
        "descripcion": "Samsung S24 Ultra con empaque",
    },
    # Laptops (peso laptop + cargador + caja de embalaje)
    "macbook air m2": {
        "peso_kg": 2.10,
        "categoria": "Laptops",
        "descripcion": "MacBook Air 13'' con cargador y caja",
    },
    "macbook pro 14": {
        "peso_kg": 2.50,
        "categoria": "Laptops",
        "descripcion": "MacBook Pro 14'' con cargador y caja",
    },
    "macbook pro 16": {
        "peso_kg": 3.20,
        "categoria": "Laptops",
        "descripcion": "MacBook Pro 16'' con cargador y caja",
    },
    "laptop gamer": {
        "peso_kg": 4.00,
        "categoria": "Laptops",
        "descripcion": "Laptop Gamer promedio con cargador pesado y caja",
    },
    # Consolas y Gadgets
    "playstation 5": {
        "peso_kg": 6.50,
        "categoria": "Consolas",
        "descripcion": "Consola PS5 con caja y mando",
    },
    "nintendo switch oled": {
        "peso_kg": 1.50,
        "categoria": "Consolas",
        "descripcion": "Nintendo Switch OLED con caja completa",
    },
    "ipad pro 11": {
        "peso_kg": 1.10,
        "categoria": "Tablets",
        "descripcion": "iPad Pro 11'' con cargador y caja",
    },
    "airpods pro": {
        "peso_kg": 0.25,
        "categoria": "Audio",
        "descripcion": "AirPods con estuche y caja",
    },
}


def buscar_peso_producto(nombre_consulta: str) -> Optional[Dict]:
    """Busca en el catálogo el producto más cercano por coincidencia de texto."""
    consulta = nombre_consulta.lower().strip()

    # 1. Búsqueda directa o parcial
    for clave, datos in PRODUCT_CATALOG.items():
        if clave in consulta or consulta in clave:
            return {"encontrado": True, "producto": clave, **datos}

    # 2. Búsqueda por palabras clave genéricas
    if "iphone" in consulta:
        return {
            "encontrado": True,
            "producto": "iPhone genérico",
            "peso_kg": 0.42,
            "descripcion": "iPhone promedio con empaque",
        }
    if "macbook" in consulta:
        return {
            "encontrado": True,
            "producto": "MacBook genérica",
            "peso_kg": 2.30,
            "descripcion": "MacBook promedio con caja",
        }
    if "laptop" in consulta:
        return {
            "encontrado": True,
            "producto": "Laptop estándar",
            "peso_kg": 2.80,
            "descripcion": "Laptop estándar con empaque",
        }

    return None