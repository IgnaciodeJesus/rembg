# Módulos y servidor del fork

Fuente revisada `c9bc20d`, 2026-10-10. Este repositorio es una herramienta de
terceros adaptada localmente; no uno de los cuatro SaaS. Su interfaz web está
en [página propia](pages/interface.md). No se descargaron pesos ni se ejecutó cámara.

| Módulo | Responsabilidad y referencia |
|---|---|
| `rembg/commands/s_command.py` | CLI `s_command` y fábrica HTTP/Gradio `create_server_app`; middleware de entrada y endpoints. |
| `rembg/server_ui.py` | `UploadOnlyInterface.preprocess_data`: origen/caché de FileData antes de copiar/decodificar. |
| `rembg/server_security.py` | Límites, validación, resolución de URL y control de recursos; consultar símbolos del mapa. |
| `rembg/server_processing.py` | Validación de imagen/opciones, una tarea activa y caché de una sesión compartidas por API/UI. |
| `rembg/bg.py` | Procesamiento de imagen del núcleo, independiente de admisión HTTP. |
| `rembg/session_factory.py` y `rembg/sessions/` | Selección/carga de sesiones ONNX: costes de memoria, pesos y backend propios. |
| `tests/test_server_*.py` | Fixtures sintéticos de API/UI y límites; no ejecutar automáticamente descarga/modelos reales. |

[source-map.json](source-map.json) cubre seis módulos del servidor/núcleo y
registra funciones y rangos físicos inclusivos,
sin importar módulos ni ejecutar contenido. Los controles y límites operativos
están en [SECURITY.md](../SECURITY.md); no se duplican aquí como certificación.

## Revisión de salud y seguridad

Se contrastaron documentación, código de construcción, límites y workflows de
publicación. No hay instalación/servicio público demostrado por la presencia de
código. Los workflows de PyPI, Docker y el instalador Windows declaran publicación
desde tags `v*.*.*`; la propuesta documental no crea tags ni distribuye paquetes.
El workflow Docker de la fuente tiene un error de indentación en `with:`
([workflow Docker](../.github/workflows/publish_docker.yml), línea 18). GitHub registró el fallo de
validación sin jobs tanto en la [fuente `c9bc20d`](https://github.com/IgnaciodeJesus/rembg/actions/runs/37175922632)
como en la [rama documental](https://github.com/IgnaciodeJesus/rembg/actions/runs/38042332841); la
condición de tags no acredita que el workflow sea ejecutable. Queda pendiente
corregirlo en un trabajo separado. El workflow de lint se activa con push/PR, instala
dependencias CPU/CLI y ejecuta comprobaciones estáticas y pruebas del servidor con
fixtures sintéticos, llamadas simuladas y un grafo ONNX de ejemplo; este trabajo
documental no lo modificó ni ejecutó localmente. El uso HTTP exige que el consumidor establezca
autenticación/TLS/cuotas; el núcleo de inferencia no aporta identidad multiusuario.

Pendiente de aceptación: ejecutar UI e inferencia con imagen sintética y modelo
autorizado en entorno aislado; medir memoria/deadline y confirmar accesibilidad.
