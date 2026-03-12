# Scripts legacy

Utilidades de línea de comandos anteriores a la web app. Ya no forman parte del servidor Flask.

| Script | Propósito |
|---|---|
| `convert_to_csv.py` | Migración única: convierte `lista_iptv.m3u` → `channels.csv` |
| `generate_m3u.py` | Genera un M3U desde `channels.csv` (flujo CSV legacy) |
| `editor.py` | Editor de canales con interfaz Tkinter (GUI de escritorio) |
| `_list_groups.py` | Imprime los grupos únicos de un M3U por stdout |

> La aplicación web (`app.py`) **no depende de ninguno de estos scripts**.
> El único fichero M3U que importa es `lista_iptv.m3u` en el directorio raíz (o `IPTV_DATA_DIR`).
