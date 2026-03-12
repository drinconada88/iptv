## 🚀 MR · Refactor core + Backups en UI + limpieza legacy

### ✨ Resumen
- Se separa la app en capas (`routes/` + `iptv_core/`) y `app.py` queda como entrypoint limpio.
- Se añade gestión de backups versionados de `lista_iptv.m3u` (crear, listar, restaurar, borrar) con API dedicada.
- Se expone en interfaz un modal de backups con acciones y filtro por etiqueta (`manual`, `pre-restore`, etc.).
- Se retiran scripts legacy del root y se mueven a `scripts/`.

### 🔧 Cambios principales
- **Arquitectura:** nuevos módulos en `iptv_core/` (`channel_service`, `health_service`, `backup_service`, `m3u_codec`, etc.) y blueprints en `routes/`.
- **Backups:** snapshot automático antes de guardar + restore seguro con backup previo (`pre-restore`).
- **UI:** nuevo botón/modal de backups, filtro por etiqueta y ajuste de spacing en header.
- **Repo hygiene:** actualización de `.gitignore` para datos runtime (`tmp/`, `backups/`, `health_cache.json`).
- **Docs:** `README.md` actualizado con estructura, endpoints y flujo operativo.

### 🧪 Validación rápida
- [x] La app arranca y carga canales.
- [x] `Guardar M3U` genera backup automático.
- [x] Desde UI se pueden crear/listar/restaurar/eliminar backups.
- [x] Tras restaurar, tabla/estadísticas se refrescan correctamente.

### ⚠️ Nota
- Este MR incluye cambios de datos runtime (`health_cache.json` y `lista_iptv.m3u`) además de código.
