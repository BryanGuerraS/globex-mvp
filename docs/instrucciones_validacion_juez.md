# Validación del LLM juez con un revisor humano

**Objetivo:** comprobar que el juez automático (`evaluacion/juez_llm.py`) califica las conversaciones de Globix igual que una persona. Si el acuerdo es suficiente (κ ≥ 0.6 en *atención correcta*), el juez puede usarse para evaluar el set reservado completo. Es la evidencia de "LLM juez validado" que pide la plantilla del E5.

**Tiempo estimado:** 45 a 60 minutos (40 conversaciones cortas).

## Antes de empezar

- Lee la rúbrica: [`rubrica_calidad.md`](rubrica_calidad.md). Tenla abierta mientras revisas.
- **No abras** `hoja_juez.csv` ni `clave.csv` de la misma carpeta: tienen las respuestas del juez y el origen de cada conversación. Verlas antes invalida la prueba.
- Algunas conversaciones tienen errores a propósito y otras no. No sabes cuáles: califica cada una por lo que ves.

## Pasos

1. Abre en Excel `evaluacion/reportes/revision_humana/validacion_juez/hoja_humano.csv`.
   - Selecciona la columna *conversacion*, ponle un ancho grande y activa **Ajustar texto** para leer la conversación completa.
2. Para cada fila (V001 a V040), escribe en las columnas **C1 a C6**:
   - **S** si cumple, **N** si no cumple, **NA** solo en *C5_derivacion* cuando la conversación no llega a decidir si derivar.
   - No dejes celdas vacías. Si dudas, pon **N** y explica en *comentario*.
3. En *comentario*, cuando pongas una N, escribe en pocas palabras qué falló (por ejemplo: "repite la pregunta del precio").
4. Trabaja solo, sin consultar a nadie ni al juez. Puedes hacerlo en varias sesiones.
5. Guarda con el **mismo nombre**, como *CSV UTF-8 (delimitado por comas)*. Si Excel pregunta si conservar el formato, elige **Sí**.
6. Avísame "listo". Calculo el acuerdo con:

```bash
python evaluacion/revision_humana.py kappa --a evaluacion/reportes/revision_humana/validacion_juez/hoja_humano.csv --b evaluacion/reportes/revision_humana/validacion_juez/hoja_juez.csv --clave evaluacion/reportes/revision_humana/validacion_juez/clave.csv --salida evaluacion/reportes/revision_humana/validacion_juez
```

## Cómo se interpreta

| κ en *atención correcta* | Qué significa | Qué hacemos |
| --- | --- | --- |
| ≥ 0.8 | Casi perfecto | El juez queda validado |
| 0.6 a 0.8 | Sustancial | El juez queda validado; se revisan los criterios con menos acuerdo |
| < 0.6 | Insuficiente | Se revisan los desacuerdos, se ajusta la rúbrica o el juez y se repite con otras conversaciones |

En los desacuerdos no se asume que el juez está mal: se revisa cada uno y se decide quién tiene razón. Lo que tú decidas queda como referencia.

## Qué contiene la hoja

- 30 conversaciones reales de Globix del set de desarrollo (corrida del 06/11), incluidas todas las que el juez marcó como incorrectas.
- 10 conversaciones con un error sembrado (peso cambiado, plazo inventado, descuento prometido, menú en vez de responder, dato pedido dos veces o derivación innecesaria).
- Orden aleatorio e ids nuevos (V001…). La hoja se genera con `python evaluacion/hoja_validacion_juez.py`.

**Revisor:** Bryan Guerra. Como es una sola persona, se reporta el acuerdo humano–juez, no el acuerdo entre dos humanos.
