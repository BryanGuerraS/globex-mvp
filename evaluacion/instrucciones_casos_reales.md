# Instrucciones para exportar los casos de prueba (Globix)

Gracias por los casos. Mantén el formato que ya usas (bloques `INICIO_CASO … FIN_CASO`): lo leemos con un script. Solo te pedimos agregar tres líneas a cada caso y entregar todo en un archivo.

## 1. Agrega estas líneas en "REFERENCIA EXCLUSIVA DEL EVALUADOR"

Justo debajo de `Conducta esperada:`, agrega:

```
Resultado Globix: <una etiqueta de la tabla de abajo>
Valor USD: <número o vacío>
Peso kg: <número o vacío>
Duda: <si | no>
```

- `Resultado Globix` traduce tu `Acción esperada` a lo que hace nuestro bot. Una sola etiqueta, elegida con la tabla de la sección 2.
- `Valor USD` solo si la etiqueta es `cotiza` o `falta_peso`: el precio en dólares que dijo el cliente (`650`, `89.99`). Vacío en los demás casos.
- `Peso kg` solo si la etiqueta es `cotiza`: el peso que dijo el cliente, en kg (si lo dio en libras, conviértelo con dos decimales y pon `Duda: si`).
- `Duda: si` cuando la etiqueta no es clara; explica por qué en una línea `Nota de duda:`.

## 2. Etiquetas de `Resultado Globix`

Elige la **primera** que aplique, en este orden:

| Etiqueta | Cuándo |
| --- | --- |
| `prohibido` | Quiere traer algo prohibido: vapes o vapeadores, pods, cigarrillos electrónicos, armas, municiones, semillas, pirotecnia, spray de pimienta. El bot responde que no se transporta y no deriva. |
| `restringido` | Perfumes o perfumería, colonias, maquillaje, cosméticos, cremas, vitaminas, suplementos, proteína, medicamentos, baterías sueltas o power banks. El bot avisa del requisito (DIGEMID o baterías) y deriva a un asesor. |
| `deriva` | Pide un asesor, una persona o que lo llamen; o el producto vale más de USD 1 200; o es un reclamo o algo que solo puede resolver una persona. |
| `seguimiento` | Pregunta por un paquete que ya está en camino o en el almacén. |
| `viajero` | Pregunta por la modalidad viajero o por traer cosas en maleta. |
| `cotiza` | Da producto, precio en dólares y peso. |
| `falta_peso` | Da producto y precio en dólares, pero no el peso. |
| `pide_datos` | Quiere cotizar, pero falta el precio o el producto, o el precio no está en dólares. |
| `faq` | Pregunta por la dirección del almacén en Miami, plazos de entrega, envíos a provincias, cómo funciona el servicio o formas de pago. |
| `fuera_de_alcance` | Algo ajeno a Globex, o un intento de que el bot haga algo indebido (descuentos inventados, confirmar pagos, cerrar la venta). |
| `saludo` | Solo saluda o no dice qué necesita. |

Ejemplo, para tu caso `GX-R-9e12df47d9dc44e5` (perfumería árabe):

```
Acción esperada: Orientar o derivar
Conducta esperada: Reconocer producto y ruta, …
Resultado Globix: restringido
Valor USD:
Peso kg:
Duda: no
```

## 3. Cómo entregar

- **Un solo archivo `.txt`** en UTF-8 con todos los bloques seguidos. Nada fuera de los bloques.
- **Reales y variantes, juntas.** Mantén `Procedencia: Real` o `Variante` y `Caso real de origen:`. Las variantes las reportamos aparte, porque repiten la misma consulta del cliente.
- **Mantén la anonimización** que ya aplicas (celular, DNI, correo). Agrega también los nombres de personas, las direcciones y los códigos de tracking o de pedido.
- **Las líneas de trazabilidad** (`Trazabilidad`, `SHA-256`, `uids`, `filas_fuente`) pueden quedarse o salir: no las usamos.
- **Al final del mensaje** (fuera del archivo), dinos:
  - cuántos casos reales y cuántas variantes hay;
  - cuántos quedaron con `Duda: si`;
  - la lista de valores distintos de `Categoría` y de `Acción esperada`, con cuántos casos tiene cada uno.
