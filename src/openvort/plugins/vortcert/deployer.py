"""Certificate deployer — push certs to Alibaba Cloud CDN, BaoTa panel, etc."""

import fnmatch
import hashlib
import time
from dataclasses import dataclass

import httpx

from openvort.utils.logging import get_logger

log = get_logger("plugins.vortcert.deployer")


@dataclass
class DeployResult:
    ok: bool
    target_name: str
    message: str = ""


# ============ Alibaba Cloud CDN ============


async def deploy_to_aliyun_cdn(
    *,
    cdn_domain: str,
    cert_pem: str,
    key_pem: str,
    access_key_id: str,
    access_key_secret: str,
    cert_name: str = "",
) -> DeployResult:
    """Deploy SSL certificate to Alibaba Cloud CDN via OpenAPI SDK."""
    try:
        from alibabacloud_cdn20180510.client import Client
        from alibabacloud_cdn20180510 import models as cdn_models
        from alibabacloud_tea_openapi import models as openapi_models
    except ImportError:
        return DeployResult(
            ok=False,
            target_name=cdn_domain,
            message="alibabacloud-cdn20180510 SDK not installed. Run: pip install alibabacloud-cdn20180510",
        )

    if not cert_name:
        cert_name = f"vortcert-{cdn_domain}-{int(time.time())}"

    try:
        config = openapi_models.Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
        )
        config.endpoint = "cdn.aliyuncs.com"
        client = Client(config)

        req = cdn_models.SetCdnDomainSSLCertificateRequest(
            domain_name=cdn_domain,
            cert_name=cert_name,
            cert_type="upload",
            sslprotocol="on",
            sslpub=cert_pem,
            sslpri=key_pem,
        )
        response = client.set_cdn_domain_sslcertificate(req)
        log.info("Deployed cert to Alibaba CDN %s, request_id=%s", cdn_domain, response.body.request_id)
        return DeployResult(ok=True, target_name=cdn_domain, message="Certificate deployed to Alibaba Cloud CDN")
    except Exception as exc:
        log.error("Alibaba CDN deploy failed for %s: %s", cdn_domain, exc)
        return DeployResult(ok=False, target_name=cdn_domain, message=str(exc))


# ============ BaoTa Panel ============


def _bt_auth_params(api_key: str) -> dict:
    """Generate BaoTa panel API authentication parameters."""
    now = str(int(time.time()))
    key_md5 = hashlib.md5(api_key.encode()).hexdigest()
    request_token = hashlib.md5((now + key_md5).encode()).hexdigest()
    return {"request_time": now, "request_token": request_token}


async def _bt_post(panel_url: str, path: str, api_key: str, extra: dict | None = None) -> dict:
    """Helper: POST to BaoTa panel API."""
    panel_url = panel_url.rstrip("/")
    url = f"{panel_url}{path}"
    data = dict(extra or {})
    data.update(_bt_auth_params(api_key))
    async with httpx.AsyncClient(verify=False, timeout=30) as client:
        resp = await client.post(url, data=data)
        resp.raise_for_status()
        return resp.json()


async def list_baota_sites(panel_url: str, api_key: str) -> list[str]:
    """Fetch all site names from a BaoTa panel.

    Uses /data?action=getData&table=sites with a large limit.
    """
    try:
        result = await _bt_post(
            panel_url, "/data?action=getData",
            api_key,
            {"table": "sites", "limit": "1000", "p": "1"},
        )
    except Exception as exc:
        log.error("BaoTa list_sites failed at %s: %s", panel_url, exc)
        raise

    items = result.get("data") or []
    names: list[str] = []
    for item in items:
        name = item.get("name") if isinstance(item, dict) else None
        if name:
            names.append(name)
    log.info("BaoTa %s: found %d sites", panel_url, len(names))
    return names


def _match_wildcard_domain(site: str, pattern: str) -> bool:
    """Match a site name against a wildcard pattern.

    Semantics:
    - ``*.example.com`` matches exactly one-level subdomains (``a.example.com``)
      but NOT the apex (``example.com``) and NOT multi-level (``a.b.example.com``),
      mirroring the Let's Encrypt wildcard certificate scope.
    - Pattern without ``*`` requires an exact match.
    - ``*`` alone matches every site (rare but explicit).
    """
    site = site.lower().strip()
    pattern = pattern.lower().strip()

    if pattern == "*":
        return True
    if pattern.startswith("*."):
        suffix = pattern[2:]
        if not site.endswith("." + suffix):
            return False
        prefix = site[: -len(suffix) - 1]
        return bool(prefix) and "." not in prefix
    if "*" in pattern or "?" in pattern:
        return fnmatch.fnmatch(site, pattern)
    return site == pattern


async def deploy_to_baota_site(
    *,
    panel_url: str,
    api_key: str,
    site_name: str,
    cert_pem: str,
    key_pem: str,
) -> DeployResult:
    """Deploy SSL certificate to a single BaoTa panel site."""
    try:
        result = await _bt_post(
            panel_url, "/site?action=SetSSL",
            api_key,
            {
                "type": "1",
                "siteName": site_name,
                "key": key_pem,
                "csr": cert_pem,
            },
        )
    except Exception as exc:
        log.error("BaoTa deploy failed for %s: %s", site_name, exc)
        return DeployResult(ok=False, target_name=site_name, message=str(exc))

    if result.get("status"):
        log.info("Deployed cert to BaoTa site %s at %s", site_name, panel_url)
        return DeployResult(ok=True, target_name=site_name, message="Certificate deployed to BaoTa panel")

    msg = result.get("msg", "Unknown BaoTa API error")
    log.error("BaoTa deploy failed for %s: %s", site_name, msg)
    return DeployResult(ok=False, target_name=site_name, message=msg)


async def deploy_to_baota_pattern(
    *,
    panel_url: str,
    api_key: str,
    domain_pattern: str,
    cert_pem: str,
    key_pem: str,
) -> list[DeployResult]:
    """Deploy SSL certificate to ALL BaoTa sites matching a wildcard pattern.

    Returns a list of DeployResult, one per matched site. If no sites match,
    returns a single failure result describing the pattern.
    """
    try:
        all_sites = await list_baota_sites(panel_url, api_key)
    except Exception as exc:
        return [DeployResult(
            ok=False,
            target_name=domain_pattern,
            message=f"Failed to list BaoTa sites: {exc}",
        )]

    matched = [s for s in all_sites if _match_wildcard_domain(s, domain_pattern)]
    if not matched:
        return [DeployResult(
            ok=False,
            target_name=domain_pattern,
            message=f"No site matched pattern '{domain_pattern}' (panel has {len(all_sites)} sites)",
        )]

    log.info("BaoTa pattern '%s' matched %d sites: %s", domain_pattern, len(matched), matched)

    results: list[DeployResult] = []
    for site in matched:
        result = await deploy_to_baota_site(
            panel_url=panel_url,
            api_key=api_key,
            site_name=site,
            cert_pem=cert_pem,
            key_pem=key_pem,
        )
        results.append(result)
    return results


# ============ Dispatcher ============


async def deploy_certificate(
    *,
    target_type: str,
    config: dict,
    cert_pem: str,
    key_pem: str,
    api_key: str = "",
    api_secret: str = "",
    target_api_key: str = "",
) -> list[DeployResult]:
    """Dispatch deployment to the appropriate handler based on target_type.

    Returns a list of DeployResult — one entry per actual destination.
    Most target types produce a single result; ``baota`` with
    ``match_mode='pattern'`` may produce multiple results, one per matched site.

    Args:
        api_key/api_secret: from the linked DNS provider (for aliyun_cdn).
        target_api_key: from the deploy target itself (for baota).
    """
    if target_type == "aliyun_cdn":
        cdn_domain = config.get("cdn_domain", "")
        if not cdn_domain:
            return [DeployResult(ok=False, target_name="", message="Missing cdn_domain in config")]
        if not api_key or not api_secret:
            return [DeployResult(ok=False, target_name=cdn_domain, message="Missing Alibaba Cloud API credentials")]
        result = await deploy_to_aliyun_cdn(
            cdn_domain=cdn_domain,
            cert_pem=cert_pem,
            key_pem=key_pem,
            access_key_id=api_key,
            access_key_secret=api_secret,
            cert_name=config.get("cert_name", ""),
        )
        return [result]

    if target_type == "baota":
        panel_url = config.get("panel_url", "")
        if not panel_url:
            return [DeployResult(ok=False, target_name="", message="Missing panel_url in config")]
        if not target_api_key:
            return [DeployResult(ok=False, target_name=panel_url, message="Missing BaoTa API key")]

        match_mode = config.get("match_mode", "single")
        if match_mode == "pattern":
            domain_pattern = config.get("domain_pattern", "").strip()
            if not domain_pattern:
                return [DeployResult(
                    ok=False, target_name=panel_url,
                    message="Missing domain_pattern in config (e.g. *.example.com)",
                )]
            return await deploy_to_baota_pattern(
                panel_url=panel_url,
                api_key=target_api_key,
                domain_pattern=domain_pattern,
                cert_pem=cert_pem,
                key_pem=key_pem,
            )

        site_name = config.get("site_name", "")
        if not site_name:
            return [DeployResult(ok=False, target_name=panel_url, message="Missing site_name in config")]
        result = await deploy_to_baota_site(
            panel_url=panel_url,
            api_key=target_api_key,
            site_name=site_name,
            cert_pem=cert_pem,
            key_pem=key_pem,
        )
        return [result]

    return [DeployResult(ok=False, target_name="", message=f"Unsupported target type: {target_type}")]
