"""Fail-closed guard and consent persistence for public demo-call requests."""

import asyncio
import ipaddress
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit

from loguru import logger


# This wording is recorded verbatim as version v1; changing a single character
# requires a new version (v2) here, on the page, and in demoCall.ts. Never edit
# v1 in place.
CONSENT_TEXTS = {
    "v1": (
        "By submitting your number, you consent to receiving an AI-generated "
        "demonstration call. This is a demo — no real property transaction is involved."
    )
}

REDIS_TIMEOUT_SECONDS = 2.0
SUPABASE_TIMEOUT_SECONDS = 5.0
MAX_PAGE_URL_LENGTH = 2048
_REFUND_IF_POSITIVE = """
local value = redis.call('GET', KEYS[1])
if not value or tonumber(value) <= 0 then return 0 end
return redis.call('DECR', KEYS[1])
"""


@dataclass(frozen=True)
class DemoConfig:
    phone_limit: int = 3
    ip_limit: int = 10
    global_limit: int = 50
    phone_cooldown_seconds: int = 180
    ip_cooldown_seconds: int = 30
    window_seconds: int = 24 * 60 * 60


DEFAULT_CONFIG = DemoConfig()


@dataclass(frozen=True)
class ClientIP:
    address: str | None
    bucket: str


@dataclass(frozen=True)
class Reservation:
    counter_keys: tuple[str, str, str]


class GuardUnavailable(RuntimeError):
    """Redis cannot safely enforce the demo-call boundary."""


class LimitExceeded(RuntimeError):
    def __init__(self, limit: str, retry_after: int | None = None) -> None:
        self.limit = limit
        self.retry_after = retry_after
        super().__init__(limit)


class ConsentStorageError(RuntimeError):
    """Tenant lookup or insert failed; a consent record cannot be guaranteed."""


def validate_phone(phone_number: Any) -> bool:
    """Return whether a value is exactly an Indian mobile E.164 number."""
    if not isinstance(phone_number, str):
        return False
    return bool(re.fullmatch(r"\+91[6-9]\d{9}", phone_number))


def parse_client_ip(raw_value: Any) -> ClientIP:
    """Parse nginx's X-Real-IP, grouping IPv6 callers into /64 buckets."""
    if not isinstance(raw_value, str) or not raw_value or "%" in raw_value:
        return ClientIP(address=None, bucket="unknown")
    try:
        address = ipaddress.ip_address(raw_value)
    except ValueError:
        return ClientIP(address=None, bucket="unknown")
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        mapped = address.ipv4_mapped
        return ClientIP(address=str(mapped), bucket=str(mapped))
    if isinstance(address, ipaddress.IPv6Address):
        bucket = str(ipaddress.ip_network(f"{address}/64", strict=False))
        return ClientIP(address=str(address), bucket=bucket)
    return ClientIP(address=str(address), bucket=str(address))


def page_url_from_headers(headers: Mapping[str, str]) -> str | None:
    """Persist only an Origin or the origin portion of a Referer."""
    raw_url = headers.get("origin") or headers.get("referer")
    if not raw_url:
        return None
    try:
        parsed = urlsplit(raw_url)
        host = parsed.hostname
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not host
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return origin if len(origin) <= MAX_PAGE_URL_LENGTH else None


async def _redis_call(awaitable: Any) -> Any:
    try:
        return await asyncio.wait_for(awaitable, timeout=REDIS_TIMEOUT_SECONDS)
    except Exception as error:
        raise GuardUnavailable("demo-call Redis guard is unavailable") from error


async def kill_switch_on(redis_client: Any) -> bool:
    return bool(await _redis_call(redis_client.get("demo:kill")))


async def read_config(redis_client: Any) -> DemoConfig:
    raw_config = await _redis_call(redis_client.hgetall("demo:config"))
    if not isinstance(raw_config, dict):
        raise GuardUnavailable("demo-call configuration is invalid")

    values: dict[str, int] = {}
    for field_name, default in DEFAULT_CONFIG.__dict__.items():
        raw_value = raw_config.get(field_name)
        if raw_value is None:
            values[field_name] = default
            continue
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            parsed = 0
        if parsed < 1:
            logger.warning("Invalid demo:config value for {}; using default", field_name)
            parsed = default
        values[field_name] = parsed
    return DemoConfig(**values)


async def reserve(
    redis_client: Any, phone_number: str, ip_bucket: str, config: DemoConfig
) -> Reservation:
    """Take cooldowns and rate slots, leaving refused requests counted."""
    phone_cooldown_key = f"demo:cd:phone:{phone_number}"
    ip_cooldown_key = f"demo:cd:ip:{ip_bucket}"
    ip_cooldown = await _redis_call(
        redis_client.set(ip_cooldown_key, "1", ex=config.ip_cooldown_seconds, nx=True)
    )
    if not ip_cooldown:
        retry_after = await _cooldown_retry_after(redis_client, ip_cooldown_key)
        raise LimitExceeded("cooldown", retry_after)
    phone_cooldown = await _redis_call(
        redis_client.set(phone_cooldown_key, "1", ex=config.phone_cooldown_seconds, nx=True)
    )
    if not phone_cooldown:
        await _redis_call(redis_client.delete(ip_cooldown_key))
        retry_after = await _cooldown_retry_after(redis_client, phone_cooldown_key)
        raise LimitExceeded("cooldown", retry_after)

    now = datetime.now(timezone.utc)
    counter_keys = (
        f"demo:rate:phone:{phone_number}",
        f"demo:rate:ip:{ip_bucket}",
        f"demo:rate:global:{now.date().isoformat()}",
    )
    limits = (config.phone_limit, config.ip_limit, config.global_limit)
    names = ("phone", "ip", "global")
    next_midnight = datetime.combine(
        now.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
    )
    ttls = (
        config.window_seconds,
        config.window_seconds,
        max(1, int((next_midnight - now).total_seconds())),
    )
    for key, limit, name, ttl in zip(counter_keys, limits, names, ttls):
        await _redis_call(redis_client.set(key, "0", ex=ttl, nx=True))
        count = await _redis_call(redis_client.incr(key))
        if count > limit:
            raise LimitExceeded(name)
    return Reservation(counter_keys=counter_keys)


async def refund(redis_client: Any, reservation: Reservation) -> None:
    """Return live positive count slots without recreating expired counters."""
    for key in reservation.counter_keys:
        await _redis_call(redis_client.eval(_REFUND_IF_POSITIVE, 1, key))


async def _cooldown_retry_after(redis_client: Any, key: str) -> int:
    remaining = await _redis_call(redis_client.ttl(key))
    return remaining if isinstance(remaining, int) and remaining > 0 else 1


def _supabase_headers(supabase_key: str) -> dict[str, str]:
    return {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def _supabase_configuration() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise ConsentStorageError("Supabase service-role configuration is missing")
    return url.rstrip("/"), key


async def resolve_tenant_id(app_state: Any, session: Any, project_slug: str) -> str:
    """Resolve and cache the tenant from the demo project, failing closed."""
    cached = getattr(app_state, "demo_tenant_id", None)
    if isinstance(cached, str) and cached:
        return cached
    supabase_url, supabase_key = _supabase_configuration()
    params = {
        "select": "id,tenant_id,tenants!inner(slug)",
        "tenants.slug": f"eq.{project_slug}",
        "limit": "1",
    }
    try:
        async with asyncio.timeout(SUPABASE_TIMEOUT_SECONDS):
            async with session.get(
                f"{supabase_url}/rest/v1/projects",
                headers=_supabase_headers(supabase_key),
                params=params,
            ) as response:
                if response.status != 200:
                    raise ConsentStorageError("project tenant lookup failed")
                rows = await response.json()
    except ConsentStorageError:
        raise
    except Exception as error:
        raise ConsentStorageError("project tenant lookup failed") from error
    if not isinstance(rows, list) or len(rows) != 1:
        raise ConsentStorageError("project tenant lookup returned no unique row")
    tenant_id = rows[0].get("tenant_id") if isinstance(rows[0], dict) else None
    if not isinstance(tenant_id, str) or not tenant_id:
        raise ConsentStorageError("project tenant_id is missing")
    app_state.demo_tenant_id = tenant_id
    return tenant_id


async def record_consent(
    session: Any,
    *,
    tenant_id: str,
    phone_number: str,
    consent_version: str,
    headers: Mapping[str, str],
    ip_address: str | None,
) -> None:
    """Write the server-held consent wording before an Exotel request."""
    supabase_url, supabase_key = _supabase_configuration()
    payload = {
        "tenant_id": tenant_id,
        "phone_normalized": phone_number,
        "action": "granted",
        "source": "web_form",
        "consent_text": CONSENT_TEXTS[consent_version],
        "consent_text_version": consent_version,
        "page_url": page_url_from_headers(headers),
        "ip_address": ip_address,
        "user_agent": headers.get("user-agent", "")[:512] or None,
    }
    try:
        async with asyncio.timeout(SUPABASE_TIMEOUT_SECONDS):
            async with session.post(
                f"{supabase_url}/rest/v1/consents",
                headers=_supabase_headers(supabase_key),
                json=payload,
            ) as response:
                if response.status not in {200, 201}:
                    raise ConsentStorageError("consent insert failed")
    except ConsentStorageError:
        raise
    except Exception as error:
        raise ConsentStorageError("consent insert failed") from error
