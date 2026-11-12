"""HTTPS for devices on your network (plan lan-access 3.1): a small certificate authority of GAIFA's own and a
certificate for this machine's names and addresses, made with the `openssl` command.

Browsers let a page use the microphone only on `localhost` or over HTTPS, so voice mode and dictation on a phone
need it. Everything lives in `data/state/lan/tls/` (keys 0600, never in `gaifa backup`): `ca.key`/`ca.crt` (ten
years), `server.key`/`server.crt` (397 days, the most Apple accepts; renewed 30 days before it ends, or when this
machine's names or addresses change). A device trusts `ca.crt` once (`/lan/trust`), or its browser warns once.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SERVER_DAYS = 397
RENEW_DAYS = 30


class CertError(Exception):
    pass


def _run(*args: str, cwd: Path | None = None) -> str:
    try:
        r = subprocess.run(["openssl", *args], capture_output=True, text=True, timeout=60, cwd=cwd)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CertError(f"openssl didn't run ({e})") from e
    if r.returncode != 0:
        raise CertError(f"openssl {args[0]} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


def available() -> bool:
    return shutil.which("openssl") is not None


def _private(path: Path, mode: int = 0o600) -> None:
    with __import__("contextlib").suppress(OSError):
        os.chmod(path, mode)


def sans(names: list[str], ips: list[str]) -> list[str]:
    """The subjectAltName entries, sorted, as openssl writes them back ("DNS:x", "IP Address:y")."""
    out = {f"DNS:{n}" for n in names if n}
    for ip in ips:
        try:
            out.add(f"IP Address:{ipaddress.ip_address(ip.split('%')[0])}")
        except ValueError:
            continue
    return sorted(out)


def _current(crt: Path) -> tuple[list[str], float] | None:
    """The certificate's names and when it ends, or None when there's none (or openssl can't read it)."""
    if not crt.is_file():
        return None
    try:
        text = _run("x509", "-in", str(crt), "-noout", "-enddate", "-ext", "subjectAltName")
    except CertError:
        return None
    end, names = 0.0, []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("notAfter="):
            end = datetime.strptime(line.split("=", 1)[1].replace(" GMT", ""), "%b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc).timestamp()
        elif line.startswith(("DNS:", "IP Address:")):
            parts = [p.strip() for p in line.split(",")]
            names = sans([p[4:] for p in parts if p.startswith("DNS:")], [p[11:] for p in parts if p.startswith("IP Address:")])
    return names, end


def _ca(folder: Path, host: str) -> None:
    if (folder / "ca.crt").is_file() and (folder / "ca.key").is_file():
        return
    _run("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-keyout", "ca.key", "-out", "ca.crt",
         "-days", "3650", "-subj", f"/CN=GAIFA on {host} (local)", "-addext", "basicConstraints=critical,CA:TRUE",
         "-addext", "keyUsage=critical,keyCertSign,cRLSign", cwd=folder)
    _private(folder / "ca.key")


def ensure(state_dir: Path, names: list[str], ips: list[str], host: str, now: float | None = None) -> tuple[Path, Path]:
    """The server certificate and key for these names and addresses: made, renewed or kept as they are."""
    if not available():
        raise CertError("the openssl command isn't installed")
    folder = state_dir / "lan" / "tls"
    folder.mkdir(parents=True, exist_ok=True)
    _private(folder, 0o700)
    _ca(folder, host)
    want = sans(names, ips)
    crt, key = folder / "server.crt", folder / "server.key"
    cur = _current(crt)
    now = time.time() if now is None else now
    if cur and key.is_file() and cur[0] == want and cur[1] - now > RENEW_DAYS * 86400:
        return crt, key
    log.info("making GAIFA's certificate for %s", ", ".join(w.split(":", 1)[1] for w in want))
    alt = ",".join(w.replace("IP Address:", "IP:") for w in want)
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        t = Path(tmp)
        (t / "ext.cnf").write_text(f"subjectAltName={alt}\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n")
        _run("req", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-keyout", str(t / "server.key"),
             "-out", str(t / "server.csr"), "-subj", f"/CN={host}")
        _run("x509", "-req", "-in", str(t / "server.csr"), "-CA", str(folder / "ca.crt"), "-CAkey", str(folder / "ca.key"),
             "-CAcreateserial", "-out", str(t / "server.crt"), "-days", str(SERVER_DAYS), "-extfile", str(t / "ext.cnf"))
        _private(t / "server.key")
        os.replace(t / "server.key", key)
        os.replace(t / "server.crt", crt)
    return crt, key


def ca_file(state_dir: Path) -> Path:
    return state_dir / "lan" / "tls" / "ca.crt"


def fingerprint(state_dir: Path) -> str | None:
    """The authority's SHA-256 fingerprint, to compare on a device before trusting it."""
    p = ca_file(state_dir)
    if not p.is_file():
        return None
    import base64

    pem = p.read_text()
    der = base64.b64decode("".join(line for line in pem.splitlines() if line and not line.startswith("-----")))
    d = hashlib.sha256(der).hexdigest().upper()
    return ":".join(d[i:i + 2] for i in range(0, len(d), 2))
