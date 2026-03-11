# 📺 IPTV Manager

> Gestor web de listas M3U con canales AceStream. Edita, organiza y sincroniza tu lista directamente desde el navegador.

---

## ✨ Features

- 🌐 **Interfaz web moderna** — tema oscuro Catppuccin Mocha, layout tipo Dispatcharr/m3u-editor
- 📋 **Tabla de canales** — ordenable por cualquier columna, búsqueda instantánea con highlight
- 🗂️ **Sidebar de grupos** — filtra por categoría con un click (DAZN, LA LIGA, FORMULA 1, UFC…)
- ✏️ **Edición completa** — modal con todos los campos: nombre, grupo, calidad, fuente, peer hash, estado, logo, notas
- ➕ **Crear canales** — formulario con autocompletado de grupos existentes, soporte para grupos nuevos
- 🔄 **Sync web** — scraping automático de [NEW ERA](https://ipfs.io/ipns/k2k4r8oqlcjxsritt5mczkcn4mmvcmymbqw7113fz2flkrerfwfps004/) con detección de duplicados por peer hash
- 📊 **Badges en tiempo real** — contadores MAIN / BACKUP / TEST / DISABLED siempre actualizados
- 💾 **Guardar M3U** — escribe directamente el fichero fuente en formato limpio y estructurado
- 📥 **Exportar** — descarga una copia limpia sin tocar el fichero original
- ⌨️ **Atajos de teclado** — `Ctrl+S` guarda, `Ctrl+F` foca el buscador, `Esc` cierra modales

---

## 🏗️ Arquitectura

```
iptv/
├── app.py                 # Backend Flask — API REST + parser M3U
├── import_from_web.py     # Scraper web NEW ERA (CLI + modo --json para la API)
├── editor.py              # (legacy) Tkinter desktop app
├── convert_to_csv.py      # (legacy) Migración M3U → CSV
├── generate_m3u.py        # (legacy) Generador CSV → M3U
├── requirements.txt       # Dependencias Python
├── lista_iptv.m3u         # Fichero fuente (fuente de verdad)
└── templates/
    └── index.html         # SPA — HTML + CSS (Catppuccin) + Vanilla JS
```

### Stack

| Capa | Tecnología |
|---|---|
| Backend | Python 3.12 + Flask 3.x |
| Frontend | HTML5 + CSS custom (sin frameworks) + Vanilla JS |
| Datos | M3U plano (fuente única de verdad) |
| Streams | AceStream via HTTP proxy local |

---

## 🚀 Instalación y uso

### Requisitos

- Python 3.10+
- Servidor AceStream corriendo en red local

### Setup

```bash
# Clonar el repo
git clone https://github.com/drinconada88/iptv.git
cd iptv

# Instalar dependencias
pip install -r requirements.txt

# Arrancar
python app.py
```

Abre el navegador en **http://localhost:5000**

---

## 🗂️ Formato M3U

El fichero se guarda con una estructura limpia y legible:

```m3u
####################################################
# CATEGORÍA: DAZN
####################################################

# ────────── Canal: DAZN 1 ──────────
# TVG-ID : DAZN 1
# Logo   : https://...

# Fuente: NEW ERA  |  Calidad: FHD  |  Peer: ad6d  |  Estado: MAIN
#EXTINF:-1 tvg-id="DAZN 1" tvg-logo="..." group-title="DAZN",DAZN 1 | FHD | NEW ERA | ad6d
http://192.168.1.169:8081/ace/getstream?id=...

# Fuente: ELCANO  |  Calidad:   |  Peer: 8e62  |  Estado: BACKUP
#EXTINF:-1 tvg-id="DAZN 1" tvg-logo="" group-title="DAZN",DAZN 1 | ELCANO | 8e62
http://192.168.1.169:8081/ace/getstream?id=...
```

### Estados disponibles

| Estado | Significado |
|---|---|
| `MAIN` | Fuente principal activa |
| `BACKUP` | Fuente de respaldo |
| `TEST` | En pruebas |
| `DISABLED` | Desactivado (URL comentada en el M3U) |

---

## 🔄 Sync web NEW ERA

El botón **Sync web** (o CLI `python import_from_web.py`) descarga la lista pública de [NEW ERA](https://ipfs.io/ipns/k2k4r8oqlcjxsritt5mczkcn4mmvcmymbqw7113fz2flkrerfwfps004/), detecta canales que no estén ya en tu lista (comparando por **peer hash completo**) y los añade como `BACKUP`.

```bash
# Ver qué añadiría sin guardar nada
python import_from_web.py --dry-run

# Añadir directamente al M3U
python import_from_web.py
```

---

## 🛠️ API REST

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/channels` | Lista todos los canales |
| `GET` | `/api/stats` | Stats + conteo por grupo y estado |
| `POST` | `/api/channel/new` | Crear canal nuevo |
| `PUT` | `/api/channel/<id>` | Actualizar canal |
| `DELETE` | `/api/channel/<id>` | Eliminar canal |
| `POST` | `/api/channel/<id>/duplicate` | Duplicar como BACKUP |
| `POST` | `/api/save` | Guardar M3U al disco |
| `GET` | `/api/export` | Descargar M3U como fichero |
| `POST` | `/api/sync` | Sincronizar con web NEW ERA |
| `POST` | `/api/load` | Cargar otro fichero M3U |

---

## ⌨️ Atajos de teclado

| Atajo | Acción |
|---|---|
| `Ctrl + S` | Guardar M3U |
| `Ctrl + F` | Foco en buscador |
| `Esc` | Cerrar modal |

---

## 📝 Grupos de canales

Los grupos actuales en la lista:

`1RFEF` · `BUNDESLIGA` · `COPA DEL REY` · `DAZN` · `DEPORTES` · `EUROSPORT` · `EVENTOS` · `FORMULA 1` · `FUTBOL INT` · `HYPERMOTION` · `LA LIGA` · `LIGA DE CAMPEONES` · `LIGA ENDESA` · `MOTOR` · `MOVISTAR` · `MOVISTAR DEPORTES` · `NBA` · `OTROS` · `SPORT TV` · `TDT` · `TENNIS` · `UFC`

---

## 🔮 Roadmap

- [ ] Drag & drop para reordenar canales
- [ ] Edición en bloque (cambiar estado/grupo a múltiples canales)
- [ ] Historial de cambios / undo
- [ ] Soporte para múltiples ficheros M3U
- [ ] Programar sync automático (cron)
- [ ] Test de stream desde la interfaz (ping AceStream)

---

<p align="center">Built with 🖤 for self-hosted IPTV</p>
