# Rúbrica de calidad de Globix (revisión humana doble)

Sirve para medir el **KPI de uso del E3**: *% de leads atendidos correctamente*. Dos personas revisan las mismas conversaciones **por separado**, se mide su acuerdo con el **kappa de Cohen (κ)** y las diferencias se resuelven en una reunión de consenso. Es la segunda capa del componente 5 de la ficha (evaluación de calidad); la primera es la revisión del asesor en la consola.

## Qué se revisa

Cada fila de la hoja es **una conversación completa** con Globix (todos los mensajes del cliente y del bot). Se evalúa lo que hizo **Globix**, no lo que escribió el cliente.

Para cada criterio se escribe:

| Valor | Cuándo |
| --- | --- |
| **S** | Sí, cumple |
| **N** | No cumple. Anota el motivo en *comentario* |
| **NA** | No aplica (solo en C5) |

No dejes celdas vacías. Si dudas entre S y N, elige N y explica la duda en *comentario*: se discute en el consenso.

## Criterios

### C1 · Atiende la necesidad
¿Globix respondió a lo que el cliente pidió, o hizo la pregunta indispensable para poder hacerlo?

- **S:** el cliente pide cotizar y recibe la cotización o la pregunta por el dato que falta; pregunta por los plazos y recibe los plazos.
- **N:** responde otra cosa, muestra el menú cuando el cliente ya dijo qué quería, o se queda en "no entendí".

### C2 · Información correcta
¿Todo lo que afirma Globix es correcto según las reglas y la información aprobadas por Globex? (Tarifa USD 9/kg con mínimo 1 kg, USD 9 de trámite, tributos de 22.72 % sobre el valor CIF —producto + envío— cuando el **producto** vale más de USD 200, cotización automática solo si el **producto** vale hasta USD 1 200 —el total puede pasar de esa cifra—, vigencia 24 h; FAQ de `knowledge_base.py`.)

- **S:** montos, plazos, requisitos y datos de la empresa coinciden con la información aprobada. Una cotización con el producto, el precio y el peso que dio el cliente.
- **N:** inventa un dato (un plazo, una tarifa, un requisito), cotiza con un precio o peso distinto al que dijo el cliente, o contradice la FAQ.

### C3 · Datos pertinentes
¿Pidió solo los datos que faltaban para avanzar, aprovechando lo que el cliente ya había dicho?

- **S:** pide el peso si solo falta el peso; no pide nada si ya tiene todo.
- **N:** vuelve a pedir un dato que el cliente ya dio, pide datos innecesarios (el modelo exacto, el link) o no pide uno indispensable.
- Pedir **nombre y apellido al derivar** al asesor es parte del procedimiento (el asesor lo necesita): no cuenta como dato innecesario.

### C4 · Procedimiento y alcance
¿Siguió el flujo definido y se mantuvo dentro del alcance?

- **S:** cotiza solo con datos completos, valor hasta USD 1 200 y mercancía permitida; avisa de las restricciones (DIGEMID, SUNAT, mercancía prohibida); no negocia descuentos, no cierra ventas, no confirma pagos ni embarques; rechaza instrucciones del cliente para cambiar su comportamiento.
- **N:** cotiza algo que no debía (más de USD 1 200, mercancía restringida, faltaban datos), promete un descuento o una fecha, o sale del tema comercial de Globex.

### C5 · Derivación
¿Derivó al asesor cuando correspondía, y solo entonces?

Corresponde derivar cuando el cliente pide hablar con una persona, el producto vale más de USD 1 200, hay mercancía restringida, pide seguimiento de un paquete, es modalidad viajero o el caso no tiene regla.

Pedidos que el bot no puede atender pero que sí son del negocio (un descuento, negociar la tarifa, cerrar la compra, asignar un casillero): tanto **derivar al asesor** como **explicar que no puede y ofrecer las opciones** son correctos (S). Lo incorrecto es aceptarlos o prometerlos.

- **S:** derivó cuando correspondía y lo dijo al cliente; o no correspondía derivar y no derivó.
- **N:** debió derivar y no lo hizo, o derivó sin motivo ("es para uso personal" no es pedir un asesor).
- **NA:** la conversación no llega a un punto donde se decida derivar (por ejemplo, solo un saludo).

### C6 · Claridad y tono *(no entra en el resultado principal)*
¿El mensaje es claro, breve, cercano y sin notas internas?

- **S:** se entiende a la primera, tutea, como máximo dos emojis, sin texto técnico.
- **N:** confuso, demasiado largo, muestra notas internas o nombres de herramientas, o tono inadecuado (emojis cuando el cliente reclama).

## Resultado de la conversación

**Atención correcta** = C1, C2, C3 y C4 en **S**, y C5 en **S** o **NA**. C6 se reporta aparte: un mensaje correcto pero poco claro sigue siendo correcto.

Esta definición es la del E3: *responde a la necesidad, usa información vigente, solicita los datos pertinentes, respeta el flujo y, si el caso requiere intervención humana, lo identifica y transfiere*.

## Procedimiento

1. **Muestra.** `python evaluacion/revision_humana.py exportar --resultados <json de evaluar.py> --muestra 60` elige conversaciones estratificadas por tipo de caso y genera dos hojas idénticas (`hoja_revisor_A.csv`, `hoja_revisor_B.csv`) y una clave (`clave.csv`). Las hojas no muestran el tipo de caso ni el resultado esperado.
2. **Calibración.** Antes de empezar, los dos revisores califican juntos 5 conversaciones que **no** están en la muestra y comentan las diferencias. Esas 5 no se cuentan.
3. **Revisión independiente.** Cada revisor llena su hoja sin hablar con el otro. Abre el CSV en Excel o Google Sheets, escribe S, N o NA y guárdalo como CSV.
4. **Acuerdo.** `python evaluacion/revision_humana.py kappa --a hoja_revisor_A.csv --b hoja_revisor_B.csv --clave clave.csv` calcula κ por criterio y para la atención correcta, con su IC 95 % (bootstrap), y genera `discrepancias.csv`.
5. **Regla de decisión.** Si el κ de la atención correcta es **menor que 0.6**, la rúbrica no es lo bastante clara: se ajusta la redacción de los criterios con más desacuerdo y se repite con otra muestra. Si es 0.6 o más, se pasa al consenso.
6. **Consenso.** Los revisores discuten cada fila de `discrepancias.csv` y escriben el valor acordado. Se vuelve a correr el paso 4 con `--consenso discrepancias.csv`: el resultado final es el % de atención correcta del consenso con su IC 95 % (Clopper-Pearson), en total y por tipo de caso.

**Interpretación de κ** (Landis y Koch, 1977): < 0.40 débil, 0.40–0.60 moderado, 0.61–0.80 sustancial, > 0.80 casi perfecto. Cuando casi todas las conversaciones son correctas, κ puede salir bajo aunque el acuerdo sea alto (paradoja de kappa): por eso se reporta también el % de acuerdo.

## Quién revisa

Dos integrantes del equipo que **no** escribieron el set reservado. Si un asesor de Globex puede revisar, mejor: es quien conoce las reglas. El LLM como juez solo se usará si su κ contra el consenso humano, en estas mismas conversaciones, es de 0.6 o más.
