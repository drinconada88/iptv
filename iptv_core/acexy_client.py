"""Low-level HTTP client for Acexy / AceStream.

All functions use a module-level logger so callers don't need to pass one in.
"""
import base64
import http.client
import logging
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


# ── Health check ──────────────────────────────────────────────────────────────

# Errors that are definitively fatal — no point retrying.
_HARD_NETWORK_ERRORS = ("connection refused", "no route to host", "name or service not known", "nodename nor servname")
_HARD_HTTP_ERRORS = frozenset(range(400, 500)) - {429}  # 4xx except rate-limit


def test_url(url: str, timeout: int = 5, retries: int = 3, retry_delay: float = 3.0) -> dict:
    """Connectivity check with retries for transient failures.

    AceStream initialises P2P on demand: the first request often hits while the
    engine is still starting and returns a timeout or 5xx.  Retrying after a
    short pause catches those false negatives.

    Soft errors (timeout, 5xx, generic URLError) are retried up to `retries`
    times.  Hard errors (connection refused, DNS failure, 4xx) return immediately.

    Returns {status, latency_ms, detail}.
    """
    last_result: dict = {"status": "offline", "latency_ms": 0, "detail": "no attempt"}

    for attempt in range(max(1, retries)):
        if attempt > 0:
            time.sleep(retry_delay)

        t0 = time.time()
        try:
            req = urllib.request.Request(url, method="GET")
            req.add_header("User-Agent", "VLC/3.0")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                ms = int((time.time() - t0) * 1000)
                return {"status": "online", "latency_ms": ms, "detail": str(r.status)}
        except urllib.error.HTTPError as e:
            ms = int((time.time() - t0) * 1000)
            if e.code in (301, 302, 206):
                return {"status": "online", "latency_ms": ms, "detail": f"HTTP {e.code}"}
            last_result = {"status": "error", "latency_ms": ms, "detail": f"HTTP {e.code}"}
            if e.code in _HARD_HTTP_ERRORS:
                break  # definitive, no retry
        except urllib.error.URLError as e:
            ms = int((time.time() - t0) * 1000)
            reason = str(e.reason)
            if "timed out" in reason.lower():
                last_result = {"status": "timeout", "latency_ms": ms, "detail": "timeout"}
            else:
                last_result = {"status": "offline", "latency_ms": ms, "detail": reason[:80]}
                if any(x in reason.lower() for x in _HARD_NETWORK_ERRORS):
                    break  # server unreachable, no retry
        except Exception as e:
            ms = int((time.time() - t0) * 1000)
            last_result = {"status": "offline", "latency_ms": ms, "detail": str(e)[:80]}

    return last_result


# ── Streaming ─────────────────────────────────────────────────────────────────

def acexy_connect(url: str, timeout: int = 60, read_timeout: int = 60):
    """Open a streaming connection to Acexy with retries and redirect-fix.

    AceStream redirects to 127.0.0.1 (its local machine). We substitute that
    with the Acexy remote host so Flask can proxy the bytes.
    Returns (HTTPResponse, HTTPConnection) or (None, None) on failure.
    """
    original_host = urllib.parse.urlparse(url).hostname
    current_url = url
    deadline = time.time() + timeout

    while time.time() < deadline:
        p = urllib.parse.urlparse(current_url)
        host = p.hostname
        port = p.port or 80
        path = (p.path or "/") + (f"?{p.query}" if p.query else "")

        conn = http.client.HTTPConnection(host, port, timeout=read_timeout)
        try:
            conn.request("GET", path, headers={"User-Agent": "VLC/3.0"})
            r = conn.getresponse()
        except Exception as e:
            conn.close()
            logger.warning("acexy_connect error %s: %s", current_url, e)
            time.sleep(2)
            continue

        if r.status in (200, 206):
            return r, conn

        if r.status in (301, 302, 307, 308):
            location = r.getheader("Location", "")
            r.read()
            conn.close()
            if not location:
                return None, None
            pl = urllib.parse.urlparse(location)
            if pl.hostname in ("127.0.0.1", "localhost", "0.0.0.0"):
                location = urllib.parse.urlunparse(
                    pl._replace(netloc=f"{original_host}:{pl.port or 80}")
                )
            current_url = location
            time.sleep(0.5)
            continue

        body = r.read(256).decode("utf-8", errors="replace").strip()
        conn.close()
        logger.info("acexy_connect %s → %s (%s), reintentando…", current_url, r.status, body[:80])
        time.sleep(2)

    return None, None


def stream_generator(response, conn, idx: int, peer: str):
    """Generator that yields raw MPEG-TS chunks, keeping the connection alive."""
    try:
        while True:
            try:
                chunk = response.read(65536)
            except (socket.timeout, TimeoutError):
                continue
            except Exception as e:
                logger.warning("stream read error idx=%s peer=%s: %s", idx, peer[-8:], e)
                break
            if not chunk:
                break
            yield chunk
    finally:
        try:
            response.close()
            conn.close()
        except Exception:
            pass


# ── HLS proxy ─────────────────────────────────────────────────────────────────

def acexy_http_fetch(url: str, timeout: int = 20, max_wait: int = 35) -> dict:
    """Robust GET for Acexy/AceStream with redirect-fix and retries.

    Returns {data: bytes, headers: dict, final_url: str}.
    Raises RuntimeError on unrecoverable failure.
    """
    original_host = urllib.parse.urlparse(url).hostname
    current_url = url
    deadline = time.time() + max_wait

    while time.time() < deadline:
        p = urllib.parse.urlparse(current_url)
        host = p.hostname
        port = p.port or 80
        path = (p.path or "/") + (f"?{p.query}" if p.query else "")
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            conn.request("GET", path, headers={"User-Agent": "VLC/3.0"})
            r = conn.getresponse()
        except Exception as e:
            conn.close()
            logger.warning("acexy_http_fetch error %s: %s", current_url, e)
            time.sleep(1.5)
            continue

        if r.status in (200, 206):
            data = r.read()
            headers = dict(r.getheaders())
            r.close()
            conn.close()
            return {"data": data, "headers": headers, "final_url": current_url}

        if r.status in (301, 302, 307, 308):
            location = r.getheader("Location", "")
            r.read()
            conn.close()
            if not location:
                break
            next_url = urllib.parse.urljoin(current_url, location)
            pl = urllib.parse.urlparse(next_url)
            if pl.hostname in ("127.0.0.1", "localhost", "0.0.0.0"):
                next_url = urllib.parse.urlunparse(
                    pl._replace(netloc=f"{original_host}:{pl.port or 80}")
                )
            current_url = next_url
            time.sleep(0.3)
            continue

        if r.status in (500, 502, 503, 504):
            body = r.read(180).decode("utf-8", errors="replace").strip()
            conn.close()
            logger.info("acexy_http_fetch %s -> %s (%s), retry...", current_url, r.status, body[:80])
            time.sleep(1.5)
            continue

        body = r.read(180).decode("utf-8", errors="replace").strip()
        conn.close()
        raise RuntimeError(f"HTTP {r.status}: {body[:120]}")

    raise RuntimeError("timeout fetching resource from Acexy/AceStream")


def rewrite_m3u8(content: str, base_url: str) -> str:
    """Rewrite all URLs in an M3U8 manifest to route through /api/hls/seg."""
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
            continue

        if stripped.startswith("#"):
            def repl_uri(m):
                raw = m.group(1)
                abs_url = urllib.parse.urljoin(base_url, raw)
                enc = base64.urlsafe_b64encode(abs_url.encode()).decode()
                return f'URI="/api/hls/seg?u={enc}"'

            lines.append(re.sub(r'URI="([^"]+)"', repl_uri, line))
            continue

        abs_url = urllib.parse.urljoin(base_url, stripped)
        enc = base64.urlsafe_b64encode(abs_url.encode()).decode()
        lines.append(f"/api/hls/seg?u={enc}")

    return "\n".join(lines)


# ── Debug ─────────────────────────────────────────────────────────────────────

def debug_stream_steps(start_url: str, max_steps: int = 6) -> list:
    """Walk redirect chain step by step for diagnostics. Returns log entries."""
    original_host = urllib.parse.urlparse(start_url).hostname
    log = []
    url = start_url

    for step in range(max_steps):
        p = urllib.parse.urlparse(url)
        host = p.hostname
        port = p.port or 80
        path = (p.path or "/") + (f"?{p.query}" if p.query else "")
        entry = {"step": step, "url": url, "host": host, "port": port}

        try:
            conn = http.client.HTTPConnection(host, port, timeout=10)
            conn.request("GET", path, headers={"User-Agent": "VLC/3.0"})
            r = conn.getresponse()
            entry["status"] = r.status
            entry["reason"] = r.reason
            entry["headers"] = dict(r.getheaders())
            location = r.getheader("Location", "")
            entry["location"] = location

            if r.status in (200, 206):
                first = r.read(128)
                entry["first_bytes"] = first.hex()
                entry["first_text"] = first[:64].decode("latin-1", errors="replace")
                r.close()
                conn.close()
                log.append(entry)
                break

            r.read()
            conn.close()
            log.append(entry)

            if r.status in (301, 302, 307, 308) and location:
                pl = urllib.parse.urlparse(location)
                if pl.hostname in ("127.0.0.1", "localhost", "0.0.0.0"):
                    location = urllib.parse.urlunparse(
                        pl._replace(netloc=f"{original_host}:{pl.port or 80}")
                    )
                    entry["location_fixed"] = location
                url = location
                time.sleep(0.3)
                continue
            break

        except Exception as e:
            entry["exception"] = str(e)
            log.append(entry)
            break

    return log
