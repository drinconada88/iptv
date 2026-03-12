# IPTV Manager

Gestor web de listas M3U con canales AceStream. Permite editar, filtrar, reordenar, probar streams y publicar un endpoint `live.m3u` compartible.

---

## Features

- Interfaz web moderna (dark mode) con tabla, filtros, orden y busqueda instantanea.
- Edicion completa de canales: nombre, grupo, estado, calidad, fuente, peer, tvg-id, logo, notas.
- Cambio rapido de estado por fila (`MAIN`, `BACKUP`, `TEST`, `DISABLED`) desde la burbuja.
- Edicion en bloque: seleccionar filas y aplicar estado/grupo/eliminar.
- Reordenacion drag and drop con persistencia en backend.
- Sync web de NEW ERA con deteccion de duplicados por peer hash.
- Test de streams manual por canal (`CHECK` -> `ONLINE/OFFLINE`) con bloqueo de concurrencia para no saturar Acexy.
- Comprobación diaria automática a las `05:00` (barrido completo, tipo cron).
- Comprobación manual por canal, por grupo o de todos los canales.
- Cabecera con contadores de salud: `Online`, `Offline`, `No probados`.
- Reproductor integrado y descarga M3U por canal.
- Endpoint dinamico `live.m3u` para compartir con clientes IPTV.
- UI responsive para movil.

---

## Estructura

```text
iptv/
|- app.py                     # Entrypoint mínimo: from app import create_app
|- app/
|  |- __init__.py             # create_app + middlewares
|  |- config.py               # Carga de settings/env
|  |- api/                    # Capa HTTP (blueprints Flask)
|  |  |- channels.py
|  |  |- streaming.py
|  |  |- health.py
|  |  |- config.py
|  |  |- sync.py
|  |  |- backups.py
|  |  `- auth.py
|  |- services/               # Casos de uso (negocio)
|  |- domain/                 # Lógica/modelos puros
|  |- integrations/           # IO externo (Acexy, scrapers)
|  |- persistence/            # Config/backup store
|  `- web/                    # Carpeta reservada para templates/static
|
|- iptv_core/                 # Implementación legacy compatible (transición)
|
|- scripts/                   # Utilidades de línea de comandos (legacy, no usan Flask)
|  |- editor.py               # Editor de canales con GUI Tkinter
|  |- convert_to_csv.py       # Migración única M3U → CSV
|  |- generate_m3u.py         # Generador M3U desde CSV
|  `- _list_groups.py         # Imprime grupos del M3U por stdout
|
|- import_from_web.py         # Sync/scraping NEW ERA (usado por /api/sync)
|- requirements.txt
|- lista_iptv.m3u             # ← ÚNICO fichero M3U. Todo lo demás se deriva de él.
|
|- backups/                   # Snapshots automáticos (generados en runtime, no en git)
`- tmp/                       # Ficheros temporales de descarga (no en git)
`- templates/                 # UI actual (index/login)
```

### Ficheros M3U: una sola fuente de verdad

| Fichero | Rol |
|---|---|
| `lista_iptv.m3u` | Única copia maestra. La app lee y escribe aquí. |
| `backups/lista_iptv_YYYYMMDD_HHMMSS.m3u` | Snapshot automático creado antes de cada "Guardar". |
| `tmp/_export_tmp.m3u` | Temporal de descarga. Se regenera en cada export. |
| `/live.m3u` | Generado en memoria al vuelo. Nunca se escribe a disco. |

---

## Requisitos

- Python 3.10+
- AceStream/Acexy disponible (local o remoto)

---

## Instalacion rapida

```bash
git clone https://github.com/drinconada88/iptv.git
cd iptv
pip install -r requirements.txt
python app.py
```

Abrir `http://localhost:5000`.

---

## Despliegue Unraid + Dockge (flujo simple)

Si usas este `compose` con `IPTV_DATA_DIR=/data` y volumen host `.../iptv-manager/data:/data`, puedes actualizar siempre asi:

1. Borrar contenido de `appdata/iptv-manager`.
2. Copiar el repo local completo tal cual dentro de `appdata/iptv-manager`.
3. En Dockge pulsar `Actualizar` (rebuild) y luego `Iniciar`.

En el arranque, si faltan en `/data`, la app inicializa automaticamente:

- `lista_iptv.m3u`
- `config.json`
- `health_cache.json`

desde la raiz del proyecto (`/app`) hacia el volumen persistente (`/data`), sin sobreescribir ficheros ya existentes.

---

## Configuracion

La app guarda configuracion en `config.json` con estos campos:

- `ace_host`
- `ace_port`
- `ace_path` (normalmente `/ace/getstream?id=`)
- `nas_path` (opcional)
- `jellyfin_mode` (boolean)
- `auto_check_enabled` (boolean)
- `auto_check_minutes` (float, intervalo entre ciclos)
- `auto_check_batch_size` (tamano de lote por ciclo)
- `auto_check_timeout_sec` (timeout por check)
- `sync_sources` (lista de fuentes web para `/api/sync`)

> Nota: la UI ahora usa revisión diaria (05:00) y comprobación manual masiva.

### Sync multi-fuente

`/api/sync` ejecuta todas las fuentes habilitadas en `sync_sources` (ordenadas por `priority`), deduplica por `peer_full` y añade solo canales nuevos.

Cada fuente admite:

- `id`, `name`, `enabled`
- `parser` (`new_era`, `acestreamid` o `generic`)
- `url`
- `timeout_sec`
- `priority`

Tambien puedes usar la variable de entorno `IPTV_DATA_DIR` para guardar `lista_iptv.m3u`, `config.json` y `health_cache.json` en otra ruta (ej. Docker o NAS).

En Docker, si `IPTV_DATA_DIR` apunta a un volumen y faltan esos ficheros, la app intenta inicializarlos automaticamente desde la raiz del proyecto (`/app`) en el primer arranque. No sobreescribe ficheros ya existentes en el volumen.

### Login basico (sesion)

La UI y las rutas `/api/*` requieren login por sesion.  
`/live.m3u` se mantiene publico para clientes IPTV (Jellyfin, VLC, etc.).

Variables de entorno disponibles:

- `IPTV_AUTH_ENABLED` (`1`/`0`, por defecto `1`)
- `IPTV_ADMIN_USER` (por defecto `admin`)
- `IPTV_ADMIN_PASS` (por defecto `admin`)
- `IPTV_SECRET_KEY` (recomendado definirla en produccion)

---

## Endpoint compartible: `/live.m3u`

`/live.m3u` se genera en vivo desde los canales cargados en memoria.

- Cambios en UI se reflejan al instante en el endpoint vivo.
- `Guardar M3U` persiste esos cambios en disco (`lista_iptv.m3u` y opcional `nas_path`).

### Parametros soportados

| Parametro | Tipo | Ejemplo | Descripcion |
|---|---|---|---|
| `host` | string | `192.168.1.50` | Host/IP del servidor Acexy al que apuntaran los canales del M3U. |
| `port` | string/int | `8081` | Puerto de Acexy. |
| `status` | string | `MAIN` | Filtra por estado (`MAIN`, `BACKUP`, `TEST`). `DISABLED` siempre se excluye. |
| `group` | string | `DAZN` | Filtra por grupo exacto. |

### Reglas de construccion de URL

1. La ruta de stream se toma del config interno `ace_path` (normalmente `/ace/getstream?id=`).
2. El cliente puede sobreescribir solo `host` y `port`.
3. El esquema se decide automaticamente:
   - `https` cuando `port=443`
   - `http` en cualquier otro caso
4. El puerto se omite automaticamente en:
   - `https` + `443`
   - `http` + `80`

### Ejemplos listos para usar

Caso basico:

```text
https://iptv.skylate.com/live.m3u
```

Solo IP y puerto (tu caso):

```text
https://iptv.skylate.com/live.m3u?host=192.168.1.50&port=8081
```

Con filtros:

```text
https://iptv.skylate.com/live.m3u?host=192.168.1.50&port=8081&status=MAIN&group=DAZN
```

### Nota importante para compartir con mas gente

Si publicas el endpoint en internet, evita direcciones privadas (`192.168.x.x`) en la salida final. Usa `host` publico (dominio/IP publica) y un reverse proxy correcto.

---

## API REST (resumen)

| Metodo | Ruta | Descripcion |
|---|---|---|
| `GET` | `/api/channels` | Lista de canales |
| `PUT` | `/api/channel/<id>` | Actualiza canal |
| `DELETE` | `/api/channel/<id>` | Elimina canal |
| `POST` | `/api/channel/new` | Crea canal |
| `POST` | `/api/channel/<id>/duplicate` | Duplica canal como BACKUP |
| `POST` | `/api/reorder` | Guarda orden manual |
| `POST` | `/api/save` | Persiste M3U a disco |
| `GET` | `/api/export` | Export M3U |
| `POST` | `/api/load` | Carga M3U de ruta |
| `POST` | `/api/sync` | Sync NEW ERA |
| `GET` | `/api/stats` | Contadores/estadisticas |
| `GET` | `/api/config` | Lee config |
| `POST` | `/api/config` | Guarda config |
| `GET` | `/api/health` | Estado de salud de canales (cacheado) |
| `GET` | `/live.m3u` | M3U dinamico compartible |
| `GET` | `/login` | Pantalla de acceso |
| `POST` | `/login` | Inicio de sesion |
| `POST` | `/logout` | Cierre de sesion |
| `GET` | `/api/backups` | Lista backups disponibles |
| `POST` | `/api/backups` | Crea backup manual (body: `{"label": "..."}`) |
| `POST` | `/api/backups/<file>/restore` | Restaura un backup (recarga canales en memoria) |
| `DELETE` | `/api/backups/<file>` | Elimina un backup |

---

## Atajos

- `Ctrl + S`: guardar
- `Ctrl + F`: foco buscador
- `Esc`: cerrar modal

---

## Troubleshooting rapido

- `live.m3u` abre pero no reproduce:
  - Revisar que `host/port` apunten a un Acexy accesible.
  - Verificar que el `id` exista y que AceStream este activo.
- Muchos `timeout` o `Started new stream ... clients=0` en Acexy:
  - Reducir `auto_check_minutes` / `auto_check_batch_size` y evitar checks por lote manuales.
  - Mantener una sola instancia de la app para no duplicar auto-checks.
- No ves cambios despues de editar:
  - El endpoint en vivo se actualiza al instante, pero para persistir tras reinicio hay que pulsar `Guardar M3U`.
- En despliegue remoto:
  - Asegurar reverse proxy para Flask y (si aplica) para `/ace/...`.

---

Built for self-hosted IPTV workflows.
