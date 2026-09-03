# Tech Lab

Laboratorio de innovación tecnológica que corre entero en un computador, sin nube y sin
llaves de pago. Está construido alrededor de tres cosas que un operador de trade marketing
y gestión humana hace todos los días a mano:

| Módulo | Qué reemplaza | Cómo lo hace |
|---|---|---|
| **Auditoría de góndola** | El mercaderista contando caras y agotados a ojo y anotándolos en un formulario | Dos detectores de objetos sobre la foto del estante |
| **Documentos** | La digitación de formatos de vinculación, cédulas y certificados | OCR local + extracción de campos |
| **Radar tecnológico** | La revisión manual de qué salió en IA esta semana y si sirve | Barrido de fuentes + clasificación contra los frentes del negocio |
| **Bitácora y POC** | La documentación que nunca se escribe | Cada corrida queda registrada y la ficha del POC se genera de ahí |
| **Tablero** | El consolidado en Excel | Indicadores por punto de venta y ahorro estimado |

## Arrancar

```bash
./arrancar.sh
```

Abre http://localhost:8080. La primera vez tarda unos 20 segundos cargando los pesos de
visión; después cada foto tarda entre 2 y 10 segundos según el tamaño.

Instalación desde cero:

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requisitos.txt
```

Los pesos se descargan solos la primera vez a `modelos/`.

## El modo con IA es opcional

Todo funciona sin llave. Si existe `GOOGLE_API_KEY` en el entorno, tres cosas mejoran:

- **Documentos**: el modelo ordena los campos en vez de las reglas de texto.
- **Radar**: la clasificación deja de ser conteo de palabras y pasa a ser criterio.
- **Ficha de POC**: la redacta el modelo a partir de las corridas, en vez de una plantilla.

La llave gratuita se saca en https://aistudio.google.com/apikey y se pasa así:

```bash
GOOGLE_API_KEY=... ./arrancar.sh
```

Si la llave falla o se acaba la cuota, cada módulo cae al modo local **sin romper la
pantalla**: eso es a propósito, una demostración no se puede caer por la nube.

## Cómo funciona la auditoría de góndola

El problema no es detectar un objeto, es detectar cien objetos pequeños, repetidos y
pegados entre sí. Tres decisiones lo resuelven:

**1. Dos modelos, no uno.** `shelf-yolov8` está entrenado sobre góndolas reales
(SKU-110K) y distingue el producto del espacio vacío, que es justo lo que interesa para
detectar agotados. `yolov8s-worldv2` es de vocabulario abierto: se le dicen las clases por
texto (`bottle`, `box`, `package`…) sin reentrenar nada, y rescata empaques que el primero
pierde, como las bolsas grandes o las tomas en ángulo. Las salidas de ambos se fusionan y
se limpian con NMS.

**2. Recorrido por mosaicos.** Un producto ocupa el 1% de la foto. Pasar la imagen entera
por la red a 1280 px pierde las filas del fondo. Se recorre en mosaicos solapados y las
cajas se devuelven a coordenadas de la foto original antes de fusionarlas.

**3. Limpieza geométrica.** Se descartan las cajas que envuelven a varias pequeñas (el
modelo a veces marca un bloque entero de productos iguales como uno solo) y las que son
más de diez veces la mediana de área, porque un facing no puede ser media góndola.

Para el *share of shelf* hay que saber cuáles caras son de la marca auditada. En lugar de
pedir que se marquen las cien a mano, se marca **una** y el resto se encuentra por
similitud de histograma de color en HSV: las caras de una misma referencia son fotos casi
idénticas del mismo empaque, y el HSV aguanta el cambio de brillo entre la balda de arriba
y la de abajo. El umbral de parecido es ajustable en la interfaz.

## Límites conocidos

Están medidos, no supuestos:

- **Fotos en ángulo**: si el estante se fotografía en perspectiva (el pasillo alejándose),
  el agrupamiento por baldas falla, porque agrupa por altura en la imagen y en perspectiva
  la altura ya no corresponde a la balda. Las fotos de frente funcionan bien.
- **Estantes con empaques blandos idénticos** (bolsas de pasta apiladas, por ejemplo)
  tienen menor recall: se detecta del orden de dos tercios de las caras.
- **El conteo no está validado** contra un conteo humano sobre fotos de la operación. Sin
  esa medición, los números sirven para comparar entre auditorías, no como cifra absoluta.
- El modo local del radar clasifica por coincidencia de términos y se equivoca seguido.
  Con llave el resultado es otro.

## Estructura

```
app.py                 API y servicio web (FastAPI)
techlab/vision.py      detección: ensamble, mosaicos, NMS, baldas
techlab/auditoria.py   indicadores: share of shelf, agotados, planograma, similitud
techlab/documentos.py  OCR local, plantillas, extracción y validaciones colombianas
techlab/radar.py       fuentes, recolección y clasificación por frentes de negocio
techlab/bitacora.py    persistencia en SQLite de corridas y POCs
techlab/ficha.py       generación de la ficha del POC
techlab/render.py      dibujo de resultados sobre la foto
web/                   interfaz (HTML, CSS y JavaScript sin dependencias)
data/muestras/         fotos y documentos de prueba
```

Sin framework de frontend, sin base de datos externa, sin contenedores: se copia la
carpeta y corre.
