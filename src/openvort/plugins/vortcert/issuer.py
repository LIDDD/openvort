"""acme.sh wrapper — issue and renew Let's Encrypt certificates."""

import asyncio
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from openvort.utils.logging import get_logger

log = get_logger("plugins.vortcert.issuer")

# Hard timeout for acme.sh subprocess to avoid hangs on flaky DNS / LE outages.
# DNS-01 typically completes within 1-3 minutes; 4 minutes leaves headroom.
ACME_ISSUE_TIMEOUT = 240.0
ACME_INSTALL_TIMEOUT = 120.0


async def _run_with_timeout(
    cmd: list[str] | str,
    *,
    env: dict[str, str] | None = None,
    timeout: float,
    shell: bool = False,
) -> tuple[int | None, str, str, bool]:
    """Run a subprocess with a hard timeout. Returns (returncode, stdout, stderr, timed_out)."""
    if shell:
        proc = await asyncio.create_subprocess_shell(
            cmd,  # type: ignore[arg-type]
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            *cmd,  # type: ignore[arg-type]
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            stdout_bytes, stderr_bytes = b"", b""
        return (
            None,
            stdout_bytes.decode(errors="replace"),
            stderr_bytes.decode(errors="replace"),
            True,
        )

    return (
        proc.returncode,
        stdout_bytes.decode(errors="replace"),
        stderr_bytes.decode(errors="replace"),
        False,
    )


# ACME CA: explicitly use Let's Encrypt to avoid acme.sh v3 default ZeroSSL,
# which is often unreachable from mainland China and forces email registration.
ACME_SERVER = "letsencrypt"


DNS_PROVIDER_MAP = {
    "aliyun": "dns_ali",
    "tencent": "dns_dp",
    "cloudflare": "dns_cf",
    "namesilo": "dns_namesilo",
    "godaddy": "dns_gd",
    "namecheap": "dns_namecheap",
    "aws": "dns_aws",
    "azure": "dns_azure",
    "gcore": "dns_gcore",
    "hetzner": "dns_hetzner",
    "linode": "dns_linode",
    "vultr": "dns_vultr",
}

ENV_KEY_MAP = {
    "aliyun": {"api_key": "Ali_Key", "api_secret": "Ali_Secret"},
    "tencent": {"api_key": "DP_Id", "api_secret": "DP_Key"},
    "cloudflare": {"api_key": "CF_Key", "api_secret": "CF_Email"},
    "namesilo": {"api_key": "Namesilo_Key"},
    "godaddy": {"api_key": "GD_Key", "api_secret": "GD_Secret"},
    "namecheap": {"api_key": "NAMECHEAP_API_KEY", "api_secret": "NAMECHEAP_USERNAME"},
    "aws": {"api_key": "AWS_ACCESS_KEY_ID", "api_secret": "AWS_SECRET_ACCESS_KEY"},
}


@dataclass
class IssueResult:
    ok: bool
    domain: str
    cert_path: str = ""
    key_path: str = ""
    chain_path: str = ""
    fullchain_path: str = ""
    message: str = ""
    stdout: str = ""
    stderr: str = ""


def _get_acme_path() -> str | None:
    acme = shutil.which("acme.sh")
    if acme:
        return acme
    home_acme = Path.home() / ".acme.sh" / "acme.sh"
    if home_acme.exists():
        return str(home_acme)
    return None


async def _try_install_acme_official(email: str, env: dict) -> tuple[bool, str]:
    """Install via official https://get.acme.sh (downloads from GitHub)."""
    install_cmd = (
        "cd /tmp"
        " && curl -fsSL -o acme_install.sh https://get.acme.sh"
        f" && bash acme_install.sh --force --email {email}"
        " && rm -f acme_install.sh"
    )

    rc, stdout, stderr, timed_out = await _run_with_timeout(
        install_cmd, env=env, timeout=ACME_INSTALL_TIMEOUT, shell=True,
    )
    combined = f"{stdout}\n{stderr}".strip()

    if timed_out:
        return False, f"timed out after {int(ACME_INSTALL_TIMEOUT)}s"
    if rc != 0:
        return False, f"rc={rc}: {combined[-300:]}"

    if _get_acme_path():
        log.info("acme.sh installed via official source")
        return True, "acme.sh installed via official source"

    return False, "script exited 0 but binary not found (likely GitHub download failed)"


async def _try_install_acme_gitee(email: str, env: dict) -> tuple[bool, str]:
    """Install via Gitee mirror (works in mainland China without GitHub access)."""
    if not shutil.which("git"):
        return False, "git not installed (required for Gitee mirror)"

    install_cmd = (
        "rm -rf /tmp/acme.sh.install"
        " && git clone --depth 1 https://gitee.com/neilpang/acme.sh.git /tmp/acme.sh.install"
        " && cd /tmp/acme.sh.install"
        f" && ./acme.sh --install --force --email {email}"
        " && cd /tmp && rm -rf /tmp/acme.sh.install"
    )

    rc, stdout, stderr, timed_out = await _run_with_timeout(
        install_cmd, env=env, timeout=ACME_INSTALL_TIMEOUT, shell=True,
    )
    combined = f"{stdout}\n{stderr}".strip()

    if timed_out:
        return False, f"timed out after {int(ACME_INSTALL_TIMEOUT)}s"
    if rc != 0:
        return False, f"rc={rc}: {combined[-300:]}"

    if _get_acme_path():
        log.info("acme.sh installed via Gitee mirror")
        return True, "acme.sh installed via Gitee mirror"

    return False, "script exited 0 but binary not found"


async def _auto_install_acme(email: str) -> tuple[bool, str]:
    """Auto-install acme.sh if not present. Tries official source then Gitee mirror.

    Returns (ok, message).
    """
    if _get_acme_path():
        return True, "acme.sh already installed"

    if not email:
        return False, "ACME email not configured. Go to Admin -> Plugins -> VortCert to set it."

    log.info("acme.sh not found, attempting auto-install...")

    import os
    env = dict(os.environ)
    home = env.get("HOME", str(Path.home()))
    env.setdefault("HOME", home)

    ok, official_msg = await _try_install_acme_official(email, env)
    if ok:
        return True, official_msg

    log.warning("Official acme.sh installer failed (%s), falling back to Gitee mirror", official_msg)

    ok, gitee_msg = await _try_install_acme_gitee(email, env)
    if ok:
        return True, gitee_msg

    log.error("Both official and Gitee installers failed. official=%s | gitee=%s", official_msg, gitee_msg)
    return False, (
        "acme.sh auto-install failed via both official source and Gitee mirror.\n"
        f"  - Official (get.acme.sh): {official_msg}\n"
        f"  - Gitee (gitee.com/neilpang/acme.sh): {gitee_msg}\n\n"
        "Please install manually on the server:\n"
        "  # Mainland China:\n"
        "  git clone --depth 1 https://gitee.com/neilpang/acme.sh.git /tmp/acme.sh\n"
        f"  cd /tmp/acme.sh && ./acme.sh --install --email {email}\n"
        "  # Or via official source (requires GitHub access):\n"
        f"  curl -fsSL https://get.acme.sh | sh -s email={email}"
    )


def _find_cert_dir(domain: str, wildcard: bool = False) -> Path | None:
    """Locate the acme.sh cert directory, handling _ecc suffix and wildcard naming."""
    base = Path.home() / ".acme.sh"
    candidates = [
        domain,
        f"{domain}_ecc",
        f"*.{domain}",
        f"*.{domain}_ecc",
    ]
    for name in candidates:
        d = base / name
        if d.is_dir():
            return d
    return None


def _build_env(provider_type: str, api_key: str, api_secret: str) -> dict[str, str]:
    """Build environment variables for acme.sh DNS validation."""
    import os
    env = dict(os.environ)
    mapping = ENV_KEY_MAP.get(provider_type, {})
    if "api_key" in mapping and api_key:
        env[mapping["api_key"]] = api_key
    if "api_secret" in mapping and api_secret:
        env[mapping["api_secret"]] = api_secret
    return env


async def issue_certificate(
    domain: str,
    provider_type: str,
    api_key: str,
    api_secret: str,
    wildcard: bool = False,
    email: str = "",
) -> IssueResult:
    """Issue a certificate via acme.sh with DNS-01 validation."""
    acme = _get_acme_path()
    if not acme:
        ok, msg = await _auto_install_acme(email)
        if not ok:
            return IssueResult(ok=False, domain=domain, message=msg)
        acme = _get_acme_path()

    dns_plugin = DNS_PROVIDER_MAP.get(provider_type)
    if not dns_plugin:
        return IssueResult(
            ok=False, domain=domain,
            message=f"Unsupported DNS provider: {provider_type}. Supported: {', '.join(DNS_PROVIDER_MAP.keys())}",
        )

    cmd = [acme, "--issue", "--server", ACME_SERVER, "--dns", dns_plugin]
    if wildcard:
        cmd.extend(["-d", domain, "-d", f"*.{domain}"])
    else:
        cmd.extend(["-d", domain])

    env = _build_env(provider_type, api_key, api_secret)

    log.info(f"Issuing certificate for {domain} via {dns_plugin}")
    rc, stdout, stderr, timed_out = await _run_with_timeout(
        cmd, env=env, timeout=ACME_ISSUE_TIMEOUT,
    )

    if timed_out:
        log.error("acme.sh issue timed out after %ss for %s", ACME_ISSUE_TIMEOUT, domain)
        return IssueResult(
            ok=False, domain=domain,
            message=(
                f"acme.sh timed out after {int(ACME_ISSUE_TIMEOUT)}s. "
                "Common causes: DNS API credentials incorrect, DNS TXT record not propagating, "
                "or Let's Encrypt rate limit. Check DNS provider config and try again."
            ),
            stdout=stdout, stderr=stderr,
        )

    if rc != 0:
        # returncode 2 means cert already issued and not due for renewal
        if rc == 2:
            log.info(f"Certificate for {domain} already issued and valid")
        else:
            log.error(f"acme.sh failed (rc={rc}): {stderr}")
            return IssueResult(
                ok=False, domain=domain,
                message=f"acme.sh exited with code {rc}",
                stdout=stdout, stderr=stderr,
            )

    cert_dir = _find_cert_dir(domain, wildcard)
    if not cert_dir:
        return IssueResult(
            ok=False, domain=domain,
            message=f"Certificate files not found in ~/.acme.sh/ after issuing",
            stdout=stdout, stderr=stderr,
        )

    cert_path = cert_dir / f"{domain}.cer"
    key_path = cert_dir / f"{domain}.key"
    chain_path = cert_dir / "ca.cer"
    fullchain_path = cert_dir / "fullchain.cer"

    if not cert_path.exists():
        for f in cert_dir.iterdir():
            if f.suffix == ".cer" and "ca" not in f.name and "fullchain" not in f.name:
                cert_path = f
                break

    return IssueResult(
        ok=True,
        domain=domain,
        cert_path=str(cert_path) if cert_path.exists() else "",
        key_path=str(key_path) if key_path.exists() else "",
        chain_path=str(chain_path) if chain_path.exists() else "",
        fullchain_path=str(fullchain_path) if fullchain_path.exists() else "",
        message="Certificate issued successfully",
        stdout=stdout, stderr=stderr,
    )


async def renew_certificate(domain: str) -> IssueResult:
    """Renew an existing certificate via acme.sh."""
    acme = _get_acme_path()
    if not acme:
        return IssueResult(
            ok=False, domain=domain,
            message="acme.sh not found",
        )

    cmd = [acme, "--renew", "--server", ACME_SERVER, "-d", domain, "--force"]

    rc, stdout, stderr, timed_out = await _run_with_timeout(
        cmd, timeout=ACME_ISSUE_TIMEOUT,
    )

    if timed_out:
        log.error("acme.sh renew timed out after %ss for %s", ACME_ISSUE_TIMEOUT, domain)
        return IssueResult(
            ok=False, domain=domain,
            message=f"acme.sh renewal timed out after {int(ACME_ISSUE_TIMEOUT)}s",
            stdout=stdout, stderr=stderr,
        )

    if rc != 0:
        return IssueResult(
            ok=False, domain=domain,
            message=f"Renewal failed (rc={rc})",
            stdout=stdout, stderr=stderr,
        )

    cert_dir = _find_cert_dir(domain)
    if not cert_dir:
        return IssueResult(
            ok=False, domain=domain,
            message="Certificate files not found after renewal",
            stdout=stdout, stderr=stderr,
        )
    return IssueResult(
        ok=True,
        domain=domain,
        cert_path=str(cert_dir / f"{domain}.cer"),
        key_path=str(cert_dir / f"{domain}.key"),
        chain_path=str(cert_dir / "ca.cer"),
        fullchain_path=str(cert_dir / "fullchain.cer"),
        message="Certificate renewed successfully",
        stdout=stdout, stderr=stderr,
    )


def read_cert_file(path: str) -> str:
    """Read a certificate/key file and return its content."""
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


_PEM_CERT_RE = re.compile(
    r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
    re.DOTALL,
)


def split_pem_certs(pem: str) -> list[str]:
    """Split a PEM bundle into individual certificate blocks (whitespace-trimmed)."""
    if not pem:
        return []
    return [m.group(0).strip() for m in _PEM_CERT_RE.finditer(pem)]


def count_certs(pem: str) -> int:
    """Count how many certificates a PEM bundle contains."""
    return len(split_pem_certs(pem))


def read_chain_pem(result: IssueResult) -> str:
    """Robustly obtain the intermediate chain PEM for an issued certificate.

    acme.sh writes the intermediate chain to ``ca.cer`` and the full chain
    (leaf + intermediates) to ``fullchain.cer``. We prefer ``ca.cer``; if it is
    missing or empty we derive the chain from ``fullchain.cer`` by dropping the
    leaf certificate. This prevents silently storing a leaf-only certificate,
    which breaks strict TLS clients (Java/curl) even though browsers may still
    work by fetching the issuer via the AIA extension.
    """
    chain = read_cert_file(result.chain_path) if result.chain_path else ""
    if split_pem_certs(chain):
        return chain.strip()

    fullchain = read_cert_file(result.fullchain_path) if result.fullchain_path else ""
    blocks = split_pem_certs(fullchain)
    if len(blocks) >= 2:
        return "\n".join(blocks[1:]).strip()
    return ""
