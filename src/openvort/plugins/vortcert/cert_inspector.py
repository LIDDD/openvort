"""PEM certificate inspector — parse cert files locally without network access.

Used by VortCert to derive `cert_domains` status from `cert_certificates` records.
This module does NOT touch the network; it only parses PEM bytes.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.x509.oid import ExtensionOID, NameOID

from openvort.utils.logging import get_logger

log = get_logger("plugins.vortcert.cert_inspector")


@dataclass
class CertInfo:
    """Parsed certificate metadata. All fields are optional — empty if parse fails."""

    not_before: datetime | None = None
    not_after: datetime | None = None
    issuer: str = ""
    subject: str = ""
    serial_number: str = ""
    san_list: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.error == "" and self.not_after is not None


def _format_name(name: x509.Name) -> str:
    """Render a Name as 'Org / CN' for display, fall back to RFC4514 string."""
    parts: list[str] = []
    for oid, label in (
        (NameOID.ORGANIZATION_NAME, None),
        (NameOID.COMMON_NAME, None),
    ):
        for attr in name.get_attributes_for_oid(oid):
            parts.append(attr.value)
    if parts:
        return " / ".join(parts)
    try:
        return name.rfc4514_string()
    except Exception:
        return ""


def _to_naive_utc(dt: datetime | None) -> datetime | None:
    """Strip tzinfo after converting to UTC, matching DB columns (TIMESTAMP WITHOUT TIME ZONE)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def parse_certificate(pem: str) -> CertInfo:
    """Parse a PEM-encoded X.509 certificate and return its metadata.

    Returns CertInfo with `error` populated if parsing fails. Caller should check `ok`.
    """
    if not pem:
        return CertInfo(error="empty PEM")

    try:
        cert = x509.load_pem_x509_certificate(pem.encode("utf-8"), default_backend())
    except Exception as e:
        log.warning("Failed to load PEM certificate: %s", e)
        return CertInfo(error=f"load_pem failed: {e}")

    try:
        not_before = cert.not_valid_before_utc
        not_after = cert.not_valid_after_utc
    except AttributeError:
        not_before = cert.not_valid_before.replace(tzinfo=timezone.utc)
        not_after = cert.not_valid_after.replace(tzinfo=timezone.utc)
    except Exception as e:
        return CertInfo(error=f"validity parse failed: {e}")

    issuer = _format_name(cert.issuer)
    subject = _format_name(cert.subject)

    serial_hex = ""
    try:
        serial_hex = format(cert.serial_number, "x").upper()
    except Exception:
        pass

    san_list: list[str] = []
    try:
        ext = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        san = ext.value
        san_list = list(san.get_values_for_type(x509.DNSName))
    except x509.ExtensionNotFound:
        pass
    except Exception as e:
        log.debug("SAN parse failed: %s", e)

    return CertInfo(
        not_before=_to_naive_utc(not_before),
        not_after=_to_naive_utc(not_after),
        issuer=issuer,
        subject=subject,
        serial_number=serial_hex,
        san_list=san_list,
    )


def classify_status(not_after: datetime | None, *, now: datetime | None = None) -> tuple[str, int | None]:
    """Classify cert health based on `not_after`. Returns (status, days_remaining).

    Status values:
      - none: no cert / not_after missing
      - expired: not_after < now
      - critical: <= 7 days remaining
      - warning: <= 30 days remaining
      - ok: > 30 days remaining
    """
    if not_after is None:
        return ("none", None)

    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)

    target = not_after
    if target.tzinfo is not None:
        target = target.astimezone(timezone.utc).replace(tzinfo=None)

    delta = target - now
    days = delta.days
    if delta.total_seconds() < 0:
        return ("expired", days)
    if days <= 7:
        return ("critical", days)
    if days <= 30:
        return ("warning", days)
    return ("ok", days)
