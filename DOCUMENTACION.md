# Documentación de rembg

**Revisión de continuidad: 24 de octubre de 2026 (America/Lima).**

[Inicio](README.md) · [Instrucciones para Claude](CLAUDE.md)

## Estado y siguiente trabajo

Fork de herramienta de imágenes. El catálogo visual está en PR 4; preservar atribuciones y distinguir el servidor/interfaz del fork de la documentación upstream. La revisión documental no acredita despliegues externos.

Punto de partida observado: rama `main`, commit `59c892db8477`. La tabla siguiente conserva el estado anterior a los commits de esta transición documental.

## Guías del proyecto

- [docs/server.md](docs/server.md)
- [USAGE.md](USAGE.md)
- [SECURITY.md](SECURITY.md)

## Trabajo conservado

Las rutas de worktrees son locales, relativas a la raíz del propietario; no se versionan como carpetas dentro de GitHub. Un commit publicado en una rama no implica integración en main, despliegue o aceptación.

| Ubicación | Rama / commit observado | Conservación remota | Cambios locales previos |
| --- | --- | --- | --- |
| `.` | `main` / `59c892db8477` | Integrado en origin/main | 0 entradas |
| `worktrees/visual-catalog-20261012` | `docs/visual-catalog-20261012` / `af70ab47e946` | Publicado en otra rama | 0 entradas |

## GitHub

[Repositorio](https://github.com/IgnaciodeJesus/rembg) · [Cambios abiertos](https://github.com/IgnaciodeJesus/rembg/pulls)

- [PR 4: Documentar el diseño por página con capturas originales](https://github.com/IgnaciodeJesus/rembg/pull/4) — borrador.

## Continuar con Claude

1. Leer este índice y las reglas AGENTS.md que existan en el proyecto y sus padres.
2. Comprobar `git status`, rama y worktree antes de editar. Continuar el trabajo en la ubicación indicada; no asumir que main contiene el último avance.
3. Consultar las guías y evidencia de esa misma rama. Conservar cambios previos y separar las pruebas actuales de resultados históricos.
4. Al cerrar una sesión, actualizar el estado, las pruebas ejecutadas, pendientes y referencia GitHub. No registrar secretos ni datos de usuarios.

La documentación prepara la continuidad; no cambia servicios, proveedores, cuentas, tareas programadas ni configuración global. Los archivos privados y evidencias completas permanecen fuera de Git.
