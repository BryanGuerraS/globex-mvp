# Conversar con Globix por API

`POST /api/chat` permite que otra IA (o un script) le haga preguntas a Globix sin WhatsApp. Es el mismo bot: mismo prompt, mismas herramientas, mismo motor de cotización y mismos filtros. Las respuestas vuelven en JSON y **nada se envía a WhatsApp**.

## Qué necesitas

| Dato | Header | De dónde sale |
| --- | --- | --- |
| URL del backend | — | Te la pasa el equipo (Render) |
| Clave de la API de chat | `X-API-Key` | Te la pasa el equipo. Solo sirve para `/api/chat`; no da acceso al dashboard |
| Tu key de Groq | `X-Groq-Key` | La tuya (console.groq.com). Globix corre con ella: el consumo va a tu cuota, no a la nuestra. No se guarda ni se registra |

## Petición

```json
{"sesion_id": "prueba-01", "mensaje": "Quiero traer una laptop de 650 dólares que pesa 2.5 kg"}
```

- `sesion_id`: 1 a 40 letras, números, `-` o `_`. La misma sesión continúa la conversación (Globix recuerda las últimas 12 h). Usa una nueva para empezar de cero.
- `mensaje`: hasta 1000 caracteres. Para "tocar" un botón, envía su título tal cual (por ejemplo `Cotizar envío` o `Hablar con asesor`).

## Respuesta

```json
{
  "sesion_id": "prueba-01",
  "bot_activo": true,
  "tipo_respuesta": "cotizacion",
  "respuestas": [
    {"tipo": "cotizacion", "texto": "📄 Te envío adjunto tu cotización *referencial*.\n\n📦 *COTIZACIÓN ESTIMADA GLOBEX* ...", "opciones": []},
    {"tipo": "botones", "texto": "Total estimado: *USD 893.92*. ¿Qué deseas hacer ahora? 😊",
     "opciones": ["Hablar con asesor", "Cotizar otro", "¿Cómo compro?"]}
  ]
}
```

- `respuestas`: los mensajes que Globix habría enviado, en orden. `tipo` es `texto`, `cotizacion` (en WhatsApp va como imagen; aquí, su desglose en texto), `botones` o `lista`; `opciones` son los títulos de los botones o de la lista.
- `tipo_respuesta`: cómo se registró el turno (`cotizacion`, `faq`, `derivacion`, `guardrail`, `menu`, `fuera_de_alcance`, ...).
- `bot_activo: false`: la conversación pasó a un asesor (pidió una persona, mercancía restringida, compra de más de USD 2 000...). Desde ahí Globix ya no responde en esa sesión, igual que en WhatsApp; usa otra `sesion_id`.

## Errores

| Código | Motivo |
| --- | --- |
| 401 | Falta o no coincide `X-API-Key`, o falta `X-Groq-Key` |
| 422 | `sesion_id` o `mensaje` inválidos |
| 429 | Más de 30 mensajes por minuto (entre todos los que usan la API) |
| 503 | La API de chat no está activada en el servidor |

Si tu key de Groq no es válida o se queda sin cuota, Globix responde con su mensaje de error de siempre ("tuve un problema…").

## Ejemplos

```bash
curl -s -X POST "$BACKEND_URL/api/chat" -H "Content-Type: application/json" -H "X-API-Key: $CHAT_API_KEY" -H "X-Groq-Key: $GROQ_API_KEY" -d '{"sesion_id": "prueba-01", "mensaje": "Hola"}'
```

```python
import os, requests

URL = os.environ["BACKEND_URL"] + "/api/chat"
HEADERS = {"X-API-Key": os.environ["CHAT_API_KEY"], "X-Groq-Key": os.environ["GROQ_API_KEY"]}

def preguntar(sesion_id: str, mensaje: str) -> dict:
    r = requests.post(URL, headers=HEADERS, json={"sesion_id": sesion_id, "mensaje": mensaje}, timeout=90)
    r.raise_for_status()
    return r.json()

for m in ["Hola", "Cotizar envío", "Unas zapatillas de 90 dólares, 1 kg"]:
    for resp in preguntar("prueba-02", m)["respuestas"]:
        print(resp["tipo"], "→", resp["texto"], resp["opciones"] or "")
```

## Tener en cuenta

- El servidor está en el plan gratuito de Render: la primera petición después de un rato puede tardar hasta un minuto en despertar. Usa un `timeout` amplio.
- Las conversaciones quedan en la base del servidor con el prefijo `PRUEBA-`, fuera de la bandeja de los asesores y de los KPI. Se pierden en cada despliegue.
- No envíes datos personales reales en las pruebas.
