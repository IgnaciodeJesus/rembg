# Interfaz de eliminación de fondo

Revisión pasiva 2026-10-10, fuente `c9bc20d`; no servicio Mortymer desplegado ni
prueba de inferencia/modelos. Página Gradio montada en `/`. Ver
[SECURITY](../../SECURITY.md) para límites y escenarios pendientes.

## Secciones y componentes

| Grupo | Elementos | Fuente |
|---|---|---|
| Entrada | Subida File de imagen, validación antes de preprocess/copia y selección de modelo permitido. | `rembg/commands/s_command.py`, construcción de `UploadOnlyInterface`; `rembg/server_ui.py`, `preprocess_data`. |
| Opciones | Alpha matting, foreground/background threshold, erosion size, máscara, postproceso y argumentos. | `rembg/commands/s_command.py`, argumentos de la interfaz, líneas 292–311. |
| Resultado | Imagen PIL devuelta como salida; caché controlada por Gradio. | `rembg/commands/s_command.py`, líneas 281–288 y 313. |
| Ejecución | Submit/controles generados por Gradio, una tarea activa, cola máxima cuatro. | `rembg/commands/s_command.py`, líneas 314–327; `rembg/server_processing.py`, `ImageProcessor.process`. |
| Estilos y efectos | Tema/layout/estados de carga provistos por Gradio; no se define CSS de marca propio en esta construcción. | `rembg/commands/s_command.py`, `gr.Interface`/`gr.mount_gradio_app`; depende de la versión Gradio instalada. |

El [mapa local](../source-map.json) conserva rangos inclusivos de cada función y
hashes. No atribuir un rango del CSS de Gradio a fuentes que este fork no posee.
La API HTTP se documenta separadamente en [servidor](../server.md).

## Comportamiento y límites

La interfaz acepta sólo archivos pertenecientes al upload administrado. Rechaza
URLs, rutas ajenas y enlaces simbólicos antes de la construcción del modelo.
La visualización, accesibilidad y eliminación de fondo no se ejecutaron en esta
pasada: los modelos necesarios no se descargaron y no se usaron imágenes privadas.
La seguridad del fork tiene evidencia histórica con modelos simulados y un
grafo ONNX mínimo; no acredita calidad del recorte ni compatibilidad GPU.

Pendientes de una futura exposición: autenticación/proxy, límites de tráfico,
cuotas de disco/memoria y deadline de inferencia que pueda interrumpirse. Este
diagnóstico no activa el servidor ni cambia su configuración.
