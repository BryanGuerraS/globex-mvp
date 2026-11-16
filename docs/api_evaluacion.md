# Evaluar a Globix por API (bancos de preguntas)

`POST /api/eval/caso` corre **un caso** de un banco en una sesión nueva de Globix, con el mismo flujo,
reglas y herramientas que WhatsApp. Devuelve la respuesta íntegra y los registros que pide el juez
(JUEZ GLOBEX 2): acciones, tiempos y total de la cotización, más los **datos que recopiló Globix** y el
**resumen del caso**. Usa la key de pago de Cerebras del equipo (`gpt-oss-120b`): quien llama no necesita
una key de LLM. **Nada se envía a WhatsApp.**

`GET /api/eval/resumen?corrida_id=...` agrega una corrida: tiempo de respuesta (p50/p95), latencia del
LLM, derivaciones y cotizaciones.

## Qué necesitas

| Dato | Header | De dónde sale |
| --- | --- | --- |
| URL del backend | — | Te la pasa el equipo (Render) |
| Clave de evaluación | `X-API-Key` | Te la pasa el equipo. Solo sirve para `/api/eval/*` |

## Petición

Un mensaje (bancos de FAQ y de cotizaciones):

```json
{"banco_id": "FAQ_132", "corrida_id": "CORRIDA_01", "id": "G006",
 "pregunta": "Para la dirección de Globex en Miami, ¿qué pongo en State y ZIP code?"}
```

Varios turnos en la misma sesión (funcionalidad "Recopilación progresiva de datos y resumen del caso"):

```json
{"banco_id": "RECOPILACION", "corrida_id": "CORRIDA_01", "id": "REC-01",
 "mensajes": ["Quiero traer unas zapatillas Nike de 120 dólares",
              "Pesan 1.5 kg",
              "Perdón, en realidad cuestan 140 dólares"]}
```

- `corrida_id` e `id`: 1 a 30 letras, números, `-` o `_`.
- Usa `pregunta` **o** `mensajes` (1 a 6 turnos, cada uno de hasta 2 000 caracteres). Los turnos se envían
  uno tras otro en la misma conversación; para "tocar" un botón, envía su título (`Cotizar envío`).
- Cada llamada es una sesión nueva, sin historial de otros casos, aunque repitas el mismo `id`
  (sirve para las repeticiones).

## Respuesta (resumida)

```json
{
  "banco_id": "RECOPILACION", "corrida_id": "CORRIDA_01", "id": "REC-01", "ejecutado": true,
  "pregunta": null, "mensajes": ["...", "...", "..."], "duracion_ms": 3100.0,
  "respuesta_bot": "📄 Te envío adjunto tu cotización ... TOTAL ESTIMADO: USD 172.30 ...",
  "turnos": [
    {"mensaje": "Quiero traer unas zapatillas Nike de 120 dólares",
     "respuesta_bot": "¿Cuánto pesa aproximadamente en kg? 📦", "tipo_respuesta": "pide_dato"},
    {"mensaje": "Pesan 1.5 kg", "respuesta_bot": "...", "tipo_respuesta": "cotizacion"},
    {"mensaje": "Perdón, en realidad cuestan 140 dólares", "respuesta_bot": "...", "tipo_respuesta": "cotizacion"}
  ],
  "error_ejecucion": null, "tipo_respuesta": "cotizacion",
  "datos_recopilados": {
    "productos": [{"id": "P1", "producto": "zapatillas Nike", "tienda": "", "precio": 140.0, "cantidad": 1,
                   "peso": 1.5, "tax_tienda_usd": null, "sin_tax": null, "tax_estado": "desconocido",
                   "tipo_precio": "base", "origen_peso": "cliente"}],
    "peso_total_kg": null, "pendientes": [], "cotizacion_aceptada": true, "error_cotizacion": null,
    "nombre_cliente": null
  },
  "resumen_caso": {
    "publicado": false,
    "texto": "*Motivo:* Sin derivación (vista previa ...)\n*Necesidad:* Continuar con la cotización de zapatillas Nike\n...",
    "campos_faltantes": []
  },
  "registros_acciones": {
    "traza_completa": true,
    "herramientas": [{"nombre": "calcular_cotizacion", "argumentos": "...", "resultado": "...", "estado": "ok"}],
    "bot_pausado": false, "motivo_derivacion": null,
    "resumen_en_consola": {"publicado": false, "texto": null}
  },
  "registros_tiempo": [{"latencia_llm_ms": 480.0, "latencia_procesamiento_ms": 1100.0,
                        "espera_limite_ms": 0, "llamadas_llm": 1}],
  "cotizacion": {"emitida": true, "total_proforma": 172.3, "moneda": "USD"},
  "control_versiones": {"proveedor_chatbot": "Cerebras", "modelo_chatbot": "gpt-oss-120b", "commit_chatbot": "..."}
}
```

| Campo | Para qué sirve |
| --- | --- |
| `respuesta_bot` | Lo que Globix respondió al **último** mensaje (la cotización va en texto; en WhatsApp es imagen). Es la entrada del juez |
| `turnos` | Cada mensaje con su respuesta y su tipo (`pide_dato`, `cotizacion`, `faq`, `guardrail`, `derivacion`, `bot_pausado`, `nombre`…). `nombre` = el cliente respondió con su nombre después de que Globix derivó y se lo pidió |
| `datos_recopilados` | El **borrador del pedido** que Globix guarda en cada chat, **aunque todavía no haya cotizado** (ver abajo). Es el mismo dato que usa el resumen del asesor |
| `resumen_caso` | El resumen que ve el asesor. `publicado: true` si el caso se derivó (está en la consola); si no, es una vista previa. `campos_faltantes`: cuáles de los cuatro campos del E3 faltan (`motivo`, `necesidad`, `datos`, `pendientes`); `[]` = completo |
| `registros_acciones` | Herramientas usadas y su resultado, si el bot quedó pausado (derivación), el motivo y el resumen publicado. Insumo de "transferencia efectiva" del juez |
| `registros_tiempo` | Una fila por turno. No incluye los 5 s de agrupación de mensajes de WhatsApp |
| `cotizacion.total_proforma` | TOTAL de la última proforma, para el indicador de cotizaciones correctas (al centavo) |
| `error_ejecucion` | Si no hubo respuesta, el motivo (SIN_RESPUESTA para el juez) |

### `datos_recopilados` (borrador del pedido)

Globix lo actualiza cuando el cliente da datos de un producto aunque falte alguno (antes de pedir lo que
falta) y cada vez que intenta cotizar. Solo guarda datos que aparecen en los mensajes del cliente o en el
catálogo de pesos: nada supuesto.

| Campo | Significado |
| --- | --- |
| `productos[].id` | Línea del pedido (`P1`, `P2`…), en el orden en que el cliente los dio |
| `producto`, `tienda`, `cantidad` | Lo que dijo el cliente (`cantidad` = 1 si no la dijo) |
| `origen_precio` | `cliente` (lo dijo tal cual), `derivado` (total que dijo el cliente − su TAX) o `null` |
| `precio` | Precio unitario en USD; `null` si aún no lo dio |
| `peso` | Peso de esa línea en kg; `null` si no lo dio o si dio un peso total del pedido |
| `origen_peso` | `cliente`, `catalogo` (peso referencial de Globix), `peso_total` o `null` |
| `tax_estado` | `confirmado` (dio el monto, se suma), `cero_confirmado` (dijo TAX 0), `incluido_desglosado` (el precio final ya incluye un TAX cuyo monto dijo; `tax_tienda_usd` trae ese monto), `incluido_sin_desglose` (el precio ya lo incluye o la tienda no lo cobra) o `desconocido` (se estima el 7 %) |
| `tipo_precio` | `base` (se suma el TAX) o `final` (ya lo incluye) |
| `tax_tienda_usd`, `sin_tax` | Los mismos datos en el formato anterior (compatibilidad) |
| `peso_total_kg` | Peso único del pedido, si el cliente lo dio así |
| `pendientes` | Lo que falta para cotizar, por línea (`"Laptop Lenovo: peso en kg"`); `[]` si está completo |
| `cotizacion_aceptada` | `true` si el último intento de cotizar pasó la validación; `false` si no se intentó o se rechazó |
| `error_cotizacion` | Motivo del rechazo del último intento (dato no anclado al texto, mercancía restringida…) |

## Cómo medir cada funcionalidad con esta API

| Funcionalidad | Qué enviar | Qué mirar |
| --- | --- | --- |
| 1. Atención inicial y FAQ | Banco FAQ (109 activos), `pregunta` | `respuesta_bot` al juez → % CORRECTAS |
| 2. Recopilación de datos y resumen | Casos de varios turnos, `mensajes` | `turnos[].tipo_respuesta` (pidió solo lo que faltaba, recotizó al corregir), `datos_recopilados` contra lo que dijo el cliente (también antes de cotizar: `pendientes`), `resumen_caso.campos_faltantes == []` (K12) |
| 3. Cotización referencial | Banco de 40 cotizaciones, `pregunta` | `cotizacion.total_proforma` contra el total del banco, al centavo |
| 4. Mercancía restringida | Casos de guardrail, `pregunta` | `tipo_respuesta` (`guardrail`) y `registros_acciones.bot_pausado` |
| 5. Derivación | Casos que deben ir al asesor | `registros_acciones.bot_pausado` y `motivo_derivacion`; el juez evalúa la orientación |
| Tiempo de respuesta | Cualquier banco | `GET /api/eval/resumen` (p50/p95) |

## Errores

| Código | Motivo |
| --- | --- |
| 401 | Falta o no coincide `X-API-Key` |
| 422 | `corrida_id` o `id` inválidos, o falta `pregunta`/`mensajes` (máximo 6 turnos) |
| 429 | Más de 60 casos por minuto, o más de 1 500 casos en el día (cuidan el saldo de Cerebras) |
| 503 | La API de evaluación o la key de Cerebras no están configuradas en el servidor |

## Ejemplo: correr un banco y guardar los resultados

```python
import json, os, requests

URL = os.environ["BACKEND_URL"]
HEADERS = {"X-API-Key": os.environ["EVAL_API_KEY"]}

def correr_banco(casos, banco_id, corrida_id, salida="resultados.jsonl"):
    """casos: lista de {"id": ..., "pregunta": ...} o {"id": ..., "mensajes": [...]}."""
    with open(salida, "a", encoding="utf-8") as f:
        for caso in casos:
            r = requests.post(f"{URL}/api/eval/caso", headers=HEADERS, timeout=180,
                              json={"banco_id": banco_id, "corrida_id": corrida_id, **caso})
            r.raise_for_status()
            f.write(json.dumps(r.json(), ensure_ascii=False) + "\n")
    return requests.get(f"{URL}/api/eval/resumen", headers=HEADERS,
                        params={"corrida_id": corrida_id}, timeout=60).json()
```

## Tener en cuenta

- El servidor está en el plan gratuito de Render: la primera petición después de un rato puede tardar
  hasta un minuto en despertar. Usa un `timeout` amplio.
- Los casos quedan en la base del servidor con el prefijo `PRUEBA-EVAL-<corrida>-`, fuera de la bandeja de
  los asesores y de los KPI. Se pierden en cada despliegue: guarda tus resultados en tu lado.
- El costo que muestra `/api/eval/resumen` usa los precios de Groq; con Cerebras es aproximadamente el doble.
- Los 23 ID retirados (G061–G082 y G084) no tienen respuesta aprobada en Globix: no hace falta enviarlos.
- `datos_recopilados.nombre_cliente` se llena cuando el cliente dice su nombre en cualquier mensaje ("me llamo Ana") o lo da después de que Globix se lo pide al derivar.
- Una vez que Globix deriva, no responde más en esa sesión (como en WhatsApp): los turnos siguientes salen
  con `tipo_respuesta: "bot_pausado"`.
