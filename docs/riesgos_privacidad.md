# Riesgos, privacidad y sesgos · Globix

## 1. Privacidad (Ley N.° 29733, Ley de Protección de Datos Personales, y su reglamento)

| Principio | Cómo lo aplica Globix |
| :-- | :-- |
| Finalidad | Los datos se usan solo para atender la consulta comercial, cotizar y derivar al asesor de Globex |
| Proporcionalidad y minimización | Se identifica al cliente con el ID de usuario de Meta; el teléfono se guarda solo como respaldo de envío y no se muestra; el nombre se pide una sola vez y solo al derivar |
| Seguridad | Webhook con firma `X-Hub-Signature-256`; todas las APIs con clave y falla cerrada; secretos fuera del código (`.env`); PDF con identificador hasheado en vez del teléfono |
| Calidad | Los datos del pedido se validan contra lo que escribió el cliente antes de usarlos |
| Flujo transfronterizo | Los mensajes pasan por Meta (WhatsApp) y Groq (LLM), proveedores fuera del Perú: Globex debe informarlo en su política de privacidad y obtener el consentimiento del cliente |
| Derechos ARCO | Acceso, rectificación, cancelación y oposición se atienden por el asesor; la consola permite borrar los datos del sistema |
| Datos de evaluación | Los bancos con consultas reales se usan solo para evaluar y no se publican en el repositorio; los chats de prueba de las APIs no salen a WhatsApp ni entran en las métricas |

**Pendiente para producción:** política de privacidad publicada, registro del banco de datos personales ante la Autoridad Nacional de Protección de Datos Personales, base de datos persistente con copia de seguridad y plazo de retención definido.

## 2. Sesgos

| Sesgo | Efecto posible | Mitigación |
| :-- | :-- | :-- |
| Redacción del cliente (faltas de ortografía, jerga, mensajes partidos) | No entender la consulta | Búsqueda tolerante a faltas (trigramas), agrupación de mensajes de 5 s, texto sin tildes en el control de mercancía |
| Productos poco comunes | Sin peso de referencia o mal clasificados | Se pide el peso al cliente; el control de mercancía revisa palabras completas y negaciones |
| Clientes que escriben en otro idioma o por audio | Atención más pobre | Aviso de que se atiende por texto y registro para el asesor |
| El juez es un LLM | Calificaciones con sesgo propio | Modelo de otra familia, temperatura 0, rúbrica explícita del equipo y validación con errores sembrados |
| Conjuntos de evaluación escritos por el equipo | Sobrestimar el desempeño | Comparación con bancos de consultas reales y con un baseline de reglas |

## 3. Riesgos con disparador y mitigación

| Riesgo | Disparador (cuándo actuar) | Mitigación |
| :-- | :-- | :-- |
| Cotización incorrecta | Total distinto del esperado en la evaluación o corrección del asesor en la consola | El LLM no calcula: motor determinista con 60 casos verificados; el asesor valida antes de enviar la proforma formal |
| Cotizar mercancía prohibida o sobre el máximo | Cualquier cotización emitida a un pedido no cotizable | Control de mercancía antes del LLM y antes del motor; 0 casos en la evaluación final |
| Respuesta inventada o fuera de alcance | Bloqueos de la revisión de salida o reporte de error del asesor | Respuestas frecuentes enviadas tal cual; revisión en código de toda respuesta libre (enlaces, código, montos no dichos, longitud) |
| No derivar cuando corresponde | Reclamo o pedido de asesor sin derivación | Reglas deterministas para reclamos, compra asistida, tope y máximos, además de la decisión del LLM |
| Caída o cuota agotada del proveedor | Errores 429 o 5xx en los registros | Keys de respaldo con pausa por cuota; mensaje de recuperación y derivación tras dos errores |
| Pérdida de datos | Despliegue o reinicio de Render | Aceptado en la fase de pruebas; base persistente en el backlog |
| Fuga de secretos | Una key aparece en un commit, log o chat | `.env` en `.gitignore`; rotar la key de inmediato |
