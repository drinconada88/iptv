# IPTV Manager

Gestor web de listas M3U con canales AceStream. Permite editar, filtrar, reordenar, probar streams y publicar un endpoint `live.m3u` compartible.

---

## Features

- Interfaz web moderna (dark mode) con tabla, filtros, orden y busqueda instantanea.
- Edicion completa de canales: nombre, grupo, estado, calidad, fuente, peer, tvg-id, logo, notas.
- Edicion en bloque: seleccionar filas y aplicar estado/grupo/eliminar.
- Reordenacion drag and drop con persistencia en backend.
- Sync web de NEW ERA con deteccion de duplicados por peer hash.
- Test de streams (individual y por lotes).
- Reproductor integrado y descarga M3U por canal.
- Endpoint dinamico `live.m3u` para compartir con clientes IPTV.
- UI responsive para movil.

---

## Estructura

```text
iptv/
|- app.py                 # Backend Flask (API + parser + live.m3u)
|- import_from_web.py     # Sync/scraping NEW ERA
|- requirements.txt
|- lista_iptv.m3u         # Fuente principal
`- templates/
   `- index.html          # UI SPA (HTML/CSS/JS)
```

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

## Configuracion

La app guarda configuracion en `config.json` con estos campos:

- `ace_host`
- `ace_port`
- `ace_path` (normalmente `/ace/getstream?id=`)
- `nas_path` (opcional)
- `jellyfin_mode` (boolean)

Tambien puedes usar la variable de entorno `IPTV_DATA_DIR` para guardar `lista_iptv.m3u` y `config.json` en otra ruta (ej. Docker o NAS).

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
| `GET` | `/live.m3u` | M3U dinamico compartible |

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
- No ves cambios despues de editar:
  - El endpoint en vivo se actualiza al instante, pero para persistir tras reinicio hay que pulsar `Guardar M3U`.
- En despliegue remoto:
  - Asegurar reverse proxy para Flask y (si aplica) para `/ace/...`.

---

Built for self-hosted IPTV workflows.
