# Pre-registro · Evaluación de Globix v0 y v1 con el lote nuevo de 60 casos

Fijado el 12/11/2026, **antes de ejecutar ningún bot sobre el lote y sin abrir sus casos**. Cualquier cambio posterior a este documento se registra al final, con fecha y motivo, y no reemplaza lo fijado aquí.

## Lote

| Dato | Valor |
| --- | --- |
| Archivo | `Globex_Lote_Nuevo_60_Casos_Reales.txt` (preparado por Juan Carlos, 12/11/2026) |
| SHA-256 | `717d4a2f9d5ca09171e4af994dacfdbdb9cdbf36905e0eb27ae06d1d745c4171` (coincide con su manifiesto) |
| Casos | 60 reales de 60 leads distintos; ninguno está en el banco v3 (comprobado por lead_key y por ID) |
| Periodo | 20/01/2025 a 02/09/2026; 46 casos de julio a septiembre de 2026 |
| Referencia | 54 "Listo" y 6 "Validación parcial" (GX-N-006 a 009: total de tributos; GX-N-046: alcance; GX-N-056: orientar o transferir) |
| Etiquetas | cotiza 15 (todas con valor y peso), faq 16, pide_datos 9, deriva 8, seguimiento 7, restringido 3, viajero 2 |
| Ubicación | `evaluacion/reservado/lote_nuevo_60/` (fuera de git). No se usa para ajustar el prompt, la base de conocimiento ni las reglas |

## Qué se compara

| Opción | Código |
| --- | --- |
| Globix v0 | Bot del commit `9acff1f` (idéntico en `92859b0`), el evaluado en el banco v3 |
| Globix v1 | Bot del commit `acbd1d6` (congelado el 13/11/2026) |
| Baseline de reglas sin LLM | `evaluacion/baseline_reglas.py`, mismas herramientas de evaluación |

Las tres opciones se corren con las **mismas herramientas de evaluación** (conversor, checks, juez y comparación), del commit que agrega `evaluacion/correr_lote_nuevo.py` (el siguiente a `acbd1d6`; su hash queda en `0_versiones.txt` de la corrida). `evaluacion/evaluar.py` es idéntico en `92859b0` y en `acbd1d6`; para la v0 se ejecuta desde un worktree en `92859b0` para que importe el bot de la v0.

Comando: `python evaluacion/correr_lote_nuevo.py --repeticiones 3` (verifica la huella del lote y los commits antes de llamar al LLM).

## Reglas de medición

1. **Checks automáticos, sobre los 60 casos** (incluidos los 6 de validación parcial). Los checks verifican el tipo de respuesta, si cotiza, si deriva y si el precio y el peso coinciden con lo que dijo el cliente; no verifican el total de tributos, que es lo que queda abierto en esos casos.
2. **Juez (atención correcta, rúbrica C1–C5), sobre los 54 casos "Listo"** con veredicto en todas las opciones. Los 6 casos parciales se reportan aparte y no entran en la métrica principal.
3. **Exactitud de precio y peso (K2), sobre los 15 casos de cotización.** En GX-N-006 el peso viene en libras; vale la conversión a kg de la referencia (Duda: si por esa conversión).
4. **Repeticiones:** Globix v0 ×3 y v1 ×3 (el LLM no admite semilla); baseline ×1 (es determinista). El juez califica cada corrida. Se informa promedio, mínimo y máximo, y el IC 95 % de Clopper-Pearson de cada corrida.
5. **Diferencias:** v1 − v0 y cada versión − reglas, con IC 95 % por bootstrap de casos (5 000 remuestreos, semilla 17). Sin variantes en el lote, cada caso es su propio grupo.
6. **Contrapeso:** cotizaciones indebidas (cotizar cuando no correspondía) y derivaciones innecesarias, por opción.
7. **Una sola ejecución por opción** con estas reglas. No se modifican casos, referencias, rúbrica ni prompt después de ver respuestas. Si hay un error técnico (por ejemplo, cuota de Groq), se repite la corrida completa afectada y se informa.

## Criterio de decisión

- La v1 reemplaza a la v0 si mejora la atención correcta y no aumenta las cotizaciones indebidas.
- Si no mejora, se informa igual y se mantiene la v0; el resultado del banco v3 sigue siendo el oficial del v0.
- Los resultados del lote nuevo se publican por separado de los del banco v3.

## Limitaciones conocidas

- El juez aún no está validado contra un revisor humano (κ humano–juez pendiente); sus resultados se rotulan así hasta entonces.
- El lote es una selección estratificada, no una muestra representativa de los 7 037 leads: sus porcentajes no estiman prevalencias.
- Con 60 casos, los intervalos son anchos (alrededor de ±12 puntos para una proporción cercana a 50 %).

## Registro de cambios

| Fecha | Cambio | Motivo |
| --- | --- | --- |
| 12/11/2026 | Documento inicial | Antes de ejecutar |
| 13/11/2026 | El límite de cotización automática pasa de USD 1 200 a USD 2 000 (valor declarado del producto) en la rúbrica y el prompt del juez | Decisión del usuario, alineada con la base de conocimiento del equipo del 12/11. Se fija antes de ejecutar y se aplica igual a v0, v1 y reglas. La v0 (commit 92859b0) conserva USD 1 200 en su código: en el lote nuevo derivará productos de USD 1 200 a 2 000 que la regla vigente permite cotizar, y se informará así. |
| 13/11/2026 | La fórmula de cotización pasa a la del Excel de Globex (hoja COURIER): TAX de tienda 7 % de referencia (0 en Amazon/eBay o si el precio lo incluye), tributos 24 % sobre producto + TAX si suma USD 200 o más, y tope de USD 2 000 sobre producto + TAX. El envío dentro de EE. UU. queda fuera del alcance. Se actualizan la rúbrica y el prompt del juez | Decisión del usuario. Se fija antes de ejecutar y la rúbrica se aplica igual a v0, v1 y reglas. La v0 (commit 92859b0) conserva 22.72 % sobre CIF: el juez no recalcula montos (solo revisa producto, precio y peso), pero si una respuesta cita la tasa o el total puede diferir; se informará así. |
| 13/11/2026 | Se confirma el desaduanaje de USD 9 (el USD 7 de la hoja COURIER era una prueba) y se agrega precio = unitario × cantidad, como la celda H7 del Excel; la rúbrica y el prompt del juez lo mencionan | Decisión del usuario, antes de ejecutar; se aplica igual a v0, v1 y reglas. La v0 no recibe cantidad: con varias unidades a precio unitario cotiza una o pide el precio de nuevo. |
| 13/11/2026 | Se congela la v1 en `acbd1d6` y se agregan `evaluacion/correr_lote_nuevo.py` (corre todo y verifica huella y commits) y `evaluacion/comparar_lote_nuevo.py` (reglas 1 a 6 de este documento: checks sobre 60, juez sobre los Listo con veredicto en todas las corridas, K2, mín.–máx., bootstrap de casos con 5 000 remuestreos y semilla 17, contrapeso) | Antes de ejecutar y sin abrir los casos; el lote solo se convirtió para comprobar que entran 60 casos (54 Listo y 6 de validación parcial, marcados). El baseline de reglas usa el código del commit de la v1 (FAQ, guardrail y motor vigentes), igual que en el banco v3, donde usaba el del commit evaluado. |
