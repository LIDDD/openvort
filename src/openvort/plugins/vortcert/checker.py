"""Live 443 SSL probe — fetch the certificate currently deployed on a host.

Used ONLY by the optional `/api/cert/probe/{id}` endpoint. The result is shown
to the user and recorded as a `source='probe'` check log; it is NEVER written
into `cert_domains.last_check_status` (that field is derived from the
`cert_certificates` table by `router.refresh_domain_status`).

Wildcard inputs like `*.foo.com` are probed via `www.foo.com` (RFC 6125: a
wildcard cert does not match the bare apex), to give a more meaningful result
when only subdomains have certificates deployed.
"""

import asyncio
import socket
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone

from openvort.plugins.vortcert.cert_inspector import parse_certificate
from openvort.utils.logging import get_logger

log = get_logger("plugins.vortcert.checker")


@dataclass
class CertCheckResult:
    domain: str
    status: str  # ok / warning / critical / expired / error
    expires_at: datetime | None = None
    issuer: str = ""
    serial_number: str = ""
    error_message: str = ""
    days_remaining: int | None = None
    san_list: list[str] = field(default_factory=list)
    probe_target: str = ""


def _classify_status(days: int) -> str:
    if days < 0:
        return "expired"
    if days <= 7:
        return "critical"
    if days <= 30:
        return "warning"
    return "ok"


def _resolve_probe_target(domain: str) -> str:
    """Pick a sensible hostname to connect to.

    For wildcard inputs `*.foo.com`, probe `www.foo.com`. RFC 6125 specifies a
    wildcard does not match the apex, and most users only deploy certs to
    subdomains anyway; using `www` typically gives a useful answer instead of
    a guaranteed Hostname mismatch.
    """
    if domain.startswith("*."):
        return "www." + domain.removeprefix("*.")
    return domain


async def check_domain_cert(domain: str, port: int = 443, timeout: float = 10.0) -> CertCheckResult:
    """Probe a domain's SSL certificate and return structured result."""
    target = _resolve_probe_target(domain)

    try:
        cert_info = await asyncio.wait_for(
            _fetch_cert_info(target, port),
            timeout=timeout,
        )
        cert_info.domain = domain
        cert_info.probe_target = target
        return cert_info
    except asyncio.TimeoutError:
        return CertCheckResult(
            domain=domain, status="error",
            error_message=f"连接 {target}:{port} 超时（{int(timeout)}s）",
            probe_target=target,
        )
    except socket.gaierror as e:
        return CertCheckResult(
            domain=domain, status="error",
            error_message=f"DNS 解析 {target} 失败：{e}",
            probe_target=target,
        )
    except ConnectionRefusedError as e:
        return CertCheckResult(
            domain=domain, status="error",
            error_message=f"{target}:{port} 拒绝连接：{e}",
            probe_target=target,
        )
    except ssl.SSLCertVerificationError as e:
        return CertCheckResult(
            domain=domain, status="error",
            error_message=f"证书校验失败（{e.reason if hasattr(e, 'reason') else e}）：{e}",
            probe_target=target,
        )
    except ssl.SSLError as e:
        return CertCheckResult(
            domain=domain, status="error",
            error_message=f"SSL 握手失败：{e}",
            probe_target=target,
        )
    except OSError as e:
        return CertCheckResult(
            domain=domain, status="error",
            error_message=f"网络错误：{e}",
            probe_target=target,
        )
    except Exception as e:
        log.exception("Unexpected error probing %s -> %s", domain, target)
        return CertCheckResult(
            domain=domain, status="error",
            error_message=str(e),
            probe_target=target,
        )


async def _fetch_cert_info(hostname: str, port: int) -> CertCheckResult:
    """Fetch certificate info via thread-pool to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_cert_sync, hostname, port)


def _fetch_cert_sync(hostname: str, port: int) -> CertCheckResult:
    """Fetch the deployed certificate without enforcing hostname / chain validation.

    `ssl.get_server_certificate` performs a TLS handshake and returns the leaf
    cert PEM without validating hostname or chain — exactly what we want for an
    informational probe. The caller renders SAN / issuer / expiry as-is and adds
    a hostname-mismatch warning to the message if applicable.
    """
    pem = ssl.get_server_certificate((hostname, port), timeout=10)
    cert_info = parse_certificate(pem)

    if not cert_info.ok:
        return CertCheckResult(
            domain=hostname,
            status="error",
            error_message=cert_info.error or "证书解析失败",
        )

    expires_at = cert_info.not_after
    days_remaining = None
    if expires_at is not None:
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        delta = expires_at - now_naive
        days_remaining = delta.days

    status = _classify_status(days_remaining) if days_remaining is not None else "error"

    # Best-effort hostname match check — record it in the message but don't
    # downgrade the status (probe is informational).
    error_message = ""
    sans = list(cert_info.san_list)
    if sans and not _hostname_matches_any(hostname, sans):
        error_message = f"证书 SAN 未覆盖 {hostname}（实际 SAN: {', '.join(sans[:6])}{'…' if len(sans) > 6 else ''}）"

    return CertCheckResult(
        domain=hostname,
        status=status,
        expires_at=expires_at,
        issuer=cert_info.issuer,
        serial_number=cert_info.serial_number,
        days_remaining=days_remaining,
        san_list=sans,
        error_message=error_message,
    )


def _hostname_matches_any(hostname: str, sans: list[str]) -> bool:
    return any(_hostname_matches(hostname, s) for s in sans)


def _hostname_matches(hostname: str, pattern: str) -> bool:
    """RFC 6125 wildcard matching: `*.foo.com` matches `a.foo.com` but not `foo.com`."""
    if not pattern:
        return False
    if pattern == hostname:
        return True
    if pattern.startswith("*."):
        suffix = pattern[2:]
        if "." not in hostname:
            return False
        host_suffix = hostname.split(".", 1)[1]
        return host_suffix == suffix
    return False


async def batch_check_domains(domains: list[dict], concurrency: int = 10) -> list[CertCheckResult]:
    """Check multiple domains concurrently. Each item: {"domain": "...", "port": 443}.

    Kept for backward compatibility / ad-hoc tooling. Patrol no longer uses this.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _check(item: dict) -> CertCheckResult:
        async with sem:
            return await check_domain_cert(
                item["domain"], port=item.get("port", 443),
            )

    tasks = [_check(d) for d in domains]
    return await asyncio.gather(*tasks)
