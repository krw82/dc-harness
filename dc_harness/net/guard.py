from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

DC_HOSTS = frozenset({"gall.dcinside.com", "m.dcinside.com", "www.dcinside.com"})


class UnsafeUrlError(ValueError):
    pass


def host_is_public(host: str) -> bool:
    """도메인은 DNS 조회로, IP 리터럴은 즉시 검사한다. 조회 실패는 거부(fail-closed)."""
    try:
        addr = ipaddress.ip_address(host)
        return not (addr.is_private or addr.is_loopback or addr.is_reserved
                    or addr.is_link_local or addr.is_multicast or addr.is_unspecified)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise UnsafeUrlError(f"cannot resolve host: {host}") from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if addr.is_private or addr.is_loopback or addr.is_reserved \
                or addr.is_link_local or addr.is_multicast or addr.is_unspecified:
            return False
    return True


def validate_http_url(url: str, allowed_hosts: frozenset[str] | None = None) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError(f"scheme not allowed: {parsed.scheme!r} in {url}")
    host = parsed.hostname or ""
    if not host:
        raise UnsafeUrlError(f"missing host: {url}")
    if allowed_hosts is not None:
        if host not in allowed_hosts:
            raise UnsafeUrlError(f"host not in allowlist: {host}")
    elif not host_is_public(host):
        raise UnsafeUrlError(f"host is not public: {host}")
    return url
