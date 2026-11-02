"""HTTP access with an allow list, a rate limit, and safe link checks.

PoliteFetcher: reads Toolkit pages and files. Hosts are allow-listed, redirects are followed
by hand and each hop is checked against the allow list, and only binary files (PDFs, images)
are cached, so a re-run always sees the current page.
LinkChecker: read-only status checks for links found in activities. http(s) only, no private
or loopback addresses, small responses, nothing cached.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin, urlparse

DEFAULT_ALLOW = (
    "www.collaborativediscussionproject.com",
    "collaborativediscussionproject.com",
    "static.wixstatic.com",
    ".usrfiles.com",
    ".filesusr.com",
)
USER_AGENT = "cdp-migration/0.1 (CMU Heinz student project for Interactivity Foundation)"


class Fetcher(Protocol):
    def get(self, url: str) -> tuple[int, str, bytes]: ...


class DomainNotAllowed(PermissionError):
    pass


def allowed(url: str, allow: tuple[str, ...]) -> bool:
    host = urlparse(url).hostname or ""
    return any(host == a or (a.startswith(".") and host.endswith(a)) for a in allow)


class PoliteFetcher:
    """requests based fetcher: one request per `delay` seconds, allow-listed hosts, binary cache."""

    def __init__(self, cache_dir: str | Path = ".cache/http", delay: float = 1.0,
                 allow: tuple[str, ...] = DEFAULT_ALLOW, timeout: float = 30.0, max_redirects: int = 5):
        import requests  # local import keeps the package importable without network deps

        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.delay, self.allow, self.timeout, self.max_redirects = delay, allow, timeout, max_redirects
        self._last = 0.0

    def _wait(self) -> None:
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def get(self, url: str) -> tuple[int, str, bytes]:
        if not allowed(url, self.allow):
            raise DomainNotAllowed(url)
        key = hashlib.sha256(url.encode()).hexdigest()
        body_p, meta_p = self.cache / key, self.cache / f"{key}.json"
        if body_p.exists() and meta_p.exists():
            meta = json.loads(meta_p.read_text())
            return meta["status"], meta["type"], body_p.read_bytes()
        current = url
        for _ in range(self.max_redirects + 1):
            self._wait()
            r = self.session.get(current, timeout=self.timeout, allow_redirects=False)
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                current = urljoin(current, r.headers["Location"])
                if not allowed(current, self.allow):
                    raise DomainNotAllowed(f"{url} redirects to {current}")
                continue
            break
        else:
            return 310, "", b"too many redirects"
        ctype = r.headers.get("Content-Type", "").split(";")[0]
        if r.status_code == 200 and not ctype.startswith("text/"):
            body_p.write_bytes(r.content)
            meta_p.write_text(json.dumps({"status": r.status_code, "type": ctype, "url": url}))
        return r.status_code, ctype, r.content


def _public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


class LinkChecker:
    """Status of a link without downloading it. Returns (status, content_type, b"")."""

    def __init__(self, timeout: float = 15.0, delay: float = 0.5):
        import requests

        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.timeout, self.delay = timeout, delay

    def get(self, url: str) -> tuple[int | str, str, bytes]:
        u = urlparse(url)
        if u.scheme in ("mailto", "tel"):
            return "not checked", "", b""
        if u.scheme not in ("http", "https") or not u.hostname:
            return "unsupported scheme", "", b""
        if not _public_host(u.hostname):
            return "refused: private address", "", b""
        current = url
        for _ in range(6):
            time.sleep(self.delay)
            r = self.session.head(current, timeout=self.timeout, allow_redirects=False)
            if r.status_code in (403, 405, 501):  # some servers refuse HEAD
                r = self.session.get(current, timeout=self.timeout, allow_redirects=False, stream=True)
                r.close()
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                current = urljoin(current, r.headers["Location"])
                h = urlparse(current)
                if h.scheme not in ("http", "https") or not h.hostname or not _public_host(h.hostname):
                    return "refused: redirect to a private or unsupported address", "", b""
                continue
            return r.status_code, r.headers.get("Content-Type", "").split(";")[0], b""
        return "too many redirects", "", b""


class AllowListFetcher:
    """Wraps any fetcher (for example the synthetic FakeSite) with the same allow list rule."""

    def __init__(self, inner: Fetcher, allow: tuple[str, ...] = DEFAULT_ALLOW):
        self.inner, self.allow = inner, allow

    def get(self, url: str) -> tuple[int, str, bytes]:
        if not allowed(url, self.allow):
            raise DomainNotAllowed(url)
        return self.inner.get(url)
