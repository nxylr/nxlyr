"""Durable booking and callback commitments for voice tools."""

import asyncio
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from time import monotonic
from typing import Any

from loguru import logger

from demo_guard import validate_phone

# These operating limits move to the knowledge base later.
VISIT_OPEN = time(9, 0)
VISIT_CLOSE = time(19, 0)
BOOKING_HORIZON_DAYS = 90
STORE_TIMEOUT_S = 3.0
ALERT_TIMEOUT_S = 3.0
COMMIT_TIMEOUT_S = 6.0
PROJECT_SLUG = "nxlyr-demo"

IST = timezone(timedelta(hours=5, minutes=30))

BOOKING_NOT_CONFIRMED = (
    "Sorry, I couldn't confirm that visit just now, so please don't count on it yet."
)
CALLBACK_NOT_PASSED_ON = "I couldn't pass that on just now."
PAST_TIME = (
    "That time has already gone. What time later today, or which other day, suits you?"
)
PAST_DATE = "That day has already gone. Which day suits you?"
TIME_UNUSABLE = "I didn't get a time I can book. Could you tell me the time again?"
OUTSIDE_HOURS = (
    "Site visits are between nine in the morning and seven in the evening. "
    "What time in that window suits you?"
)
TOO_FAR = (
    "I can only book within the next three months. Which date in that time suits you?"
)
DATE_UNUSABLE = "I didn't get a date I can book. Which day suits you?"

_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


def now_ist() -> datetime:
    return datetime.now(IST)


@dataclass(frozen=True)
class VisitError:
    reason: str
    say: str


def parse_visit(
    preferred_date: Any,
    preferred_time: Any,
    now: datetime | None = None,
) -> tuple[date, time] | VisitError:
    """Parse and validate a requested visit in IST, returning the first error."""
    if not preferred_date:
        return VisitError("date_missing", DATE_UNUSABLE)
    date_text = str(preferred_date)
    if not _DATE_RE.fullmatch(date_text):
        return VisitError("date_malformed", DATE_UNUSABLE)
    try:
        visit_date = date.fromisoformat(date_text)
    except ValueError:
        return VisitError("date_malformed", DATE_UNUSABLE)

    if not preferred_time:
        return VisitError("time_missing", TIME_UNUSABLE)
    time_text = str(preferred_time)
    if not _TIME_RE.fullmatch(time_text):
        return VisitError("time_malformed", TIME_UNUSABLE)
    visit_time = time.fromisoformat(time_text)

    current = (now or now_ist()).astimezone(IST)
    requested = datetime.combine(visit_date, visit_time, IST)
    if requested <= current:
        sentence = PAST_DATE if visit_date < current.date() else PAST_TIME
        return VisitError("in_the_past", sentence)
    if visit_date > current.date() + timedelta(days=BOOKING_HORIZON_DAYS):
        return VisitError("too_far", TOO_FAR)
    if not VISIT_OPEN <= visit_time <= VISIT_CLOSE:
        return VisitError("outside_hours", OUTSIDE_HOURS)
    return visit_date, visit_time


class CommitmentError(RuntimeError):
    def __init__(
        self,
        stage: str,
        reason: str,
        status: int | None = None,
        *,
        db_ms: int = 0,
        tg_ms: int = 0,
    ) -> None:
        self.stage = stage
        self.reason = reason
        self.status = status
        self.db_ms = db_ms
        self.tg_ms = tg_ms
        super().__init__(reason)


class AlertError(RuntimeError):
    def __init__(
        self,
        reason: str,
        status: int | None = None,
        *,
        db_ms: int = 0,
        tg_ms: int = 0,
    ) -> None:
        self.reason = reason
        self.status = status
        self.db_ms = db_ms
        self.tg_ms = tg_ms
        super().__init__(reason)


@dataclass(frozen=True)
class PreviousBooking:
    reference: str
    visit_date: date
    visit_time: time
    alerted: bool


@dataclass(frozen=True)
class CommitResult:
    reference: str
    replaces: tuple[PreviousBooking, ...] = ()
    previous: tuple[PreviousBooking, ...] = ()


def _supabase_configuration() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise CommitmentError("store", "not_configured")
    return url.rstrip("/"), key


def _supabase_headers(key: str, prefer: str) -> dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


async def store_commitment(session: Any, row: dict[str, Any]) -> str:
    """Insert a callback or upsert a booking and return its database id."""
    url, key = _supabase_configuration()
    booking = row.get("kind") == "site_visit"
    endpoint = f"{url}/rest/v1/call_commitments"
    prefer = "return=representation"
    payload = dict(row)
    if booking:
        endpoint += "?on_conflict=call_sid,kind,visit_date,visit_time"
        prefer += ",resolution=merge-duplicates"
        payload["superseded_at"] = None
    try:
        async with asyncio.timeout(STORE_TIMEOUT_S):
            async with session.post(
                endpoint,
                headers=_supabase_headers(key, prefer),
                json=payload,
            ) as response:
                if response.status not in {200, 201}:
                    raise CommitmentError("store", "http", response.status)
                rows = await response.json(content_type=None)
    except CommitmentError:
        raise
    except TimeoutError:
        raise CommitmentError("store", "timeout") from None
    except Exception as error:
        raise CommitmentError("store", type(error).__name__) from None
    reference = rows[0].get("id") if isinstance(rows, list) and rows else None
    if not isinstance(reference, str) or not reference:
        raise CommitmentError("store", "missing_reference")
    return reference


async def send_alert(session: Any, text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise AlertError("not_configured")
    try:
        async with asyncio.timeout(ALERT_TIMEOUT_S):
            async with session.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            ) as response:
                payload = await response.json(content_type=None)
                if (
                    response.status != 200
                    or not isinstance(payload, dict)
                    or payload.get("ok") is not True
                ):
                    raise AlertError("http", response.status)
    except AlertError:
        raise
    except TimeoutError:
        raise AlertError("timeout") from None
    except Exception as error:
        raise AlertError(type(error).__name__) from None


def _safe_note(note: Any, limit: int) -> str:
    value = str(note or "none")
    value = re.sub(r"(?<![0-9])(?:[0-9][ -]*){10,}(?![0-9])", "[redacted]", value)
    return value[:limit]


def _phone_line(phone: str | None) -> str:
    return f"Phone: ends {phone[-4:]}" if phone else "Phone: unknown"


def _format_visit_day(value: date, include_year: bool) -> str:
    base = f"{value:%a} {value.day} {value:%b}"
    return f"{base} {value.year}" if include_year else base


def booking_alert_text(
    reference: str,
    *,
    date_value: date,
    time_value: time,
    note: Any,
    phone: str | None,
    replaces: list[tuple[date, time]] | tuple[tuple[date, time], ...] = (),
) -> str:
    heading = "Updated booking" if replaces else "Site visit booked"
    lines = [
        f"{heading} [ref {reference[:8]}]",
        f"{_format_visit_day(date_value, True)}, {time_value:%H:%M} IST",
    ]
    if replaces:
        replaced = "; ".join(
            f"{_format_visit_day(day, False)}, {at:%H:%M}" for day, at in replaces
        )
        lines.append(f"replaces {replaced}")
    lines.extend((f"Note: {_safe_note(note, 200)}", _phone_line(phone)))
    return "\n".join(lines)


def callback_alert_text(
    reference: str, *, notes: Any, phone: str | None
) -> str:
    return "\n".join(
        (
            f"Callback request [ref {reference[:8]}]",
            f"Asked: {_safe_note(notes, 200)}",
            _phone_line(phone),
        )
    )


def _normalise_indian_mobile(value: Any) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    elif len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    candidate = f"+91{digits}" if len(digits) == 10 else ""
    return candidate if validate_phone(candidate) else None


def _normalise_for_comparison(value: Any) -> str | None:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits or None


def pick_lead_phone(
    call_data: Any, own_exotel_number: Any
) -> tuple[str | None, str, str]:
    own = _normalise_for_comparison(own_exotel_number)
    if own is None:
        return None, "none", "own_unknown"
    from_value = getattr(call_data, "from_number", "")
    to_value = getattr(call_data, "to_number", "")
    from_differs = _normalise_for_comparison(from_value) != own
    to_differs = _normalise_for_comparison(to_value) != own
    if from_differs == to_differs:
        reason = "both_differ" if from_differs else "neither_differs"
        return None, "none", reason
    value, field = (from_value, "from") if from_differs else (to_value, "to")
    phone = _normalise_indian_mobile(value)
    if phone is None:
        return None, "none", "lead_invalid"
    return phone, field, f"lead_{field}"


def phone_last_four(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-4:] if digits else "none"


async def _lookup_previous(
    session: Any,
    call_sid: str,
    visit_date: date,
    visit_time: time,
) -> list[PreviousBooking]:
    url, key = _supabase_configuration()
    params = {
        "call_sid": f"eq.{call_sid}",
        "kind": "eq.site_visit",
        "superseded_at": "is.null",
        "select": "id,visit_date,visit_time,alert_sent_at",
    }
    try:
        async with asyncio.timeout(STORE_TIMEOUT_S):
            async with session.get(
                f"{url}/rest/v1/call_commitments",
                headers=_supabase_headers(key, "return=representation"),
                params=params,
            ) as response:
                if response.status != 200:
                    raise CommitmentError("store", "lookup_http", response.status)
                rows = await response.json(content_type=None)
    except CommitmentError:
        raise
    except TimeoutError:
        raise CommitmentError("store", "lookup_timeout") from None
    except Exception as error:
        raise CommitmentError("store", f"lookup_{type(error).__name__}") from None
    previous = []
    for row in rows if isinstance(rows, list) else []:
        try:
            old_date = date.fromisoformat(row["visit_date"])
            old_time = time.fromisoformat(row["visit_time"])
            reference = row["id"]
        except (KeyError, TypeError, ValueError):
            raise CommitmentError("store", "lookup_malformed") from None
        if old_date == visit_date and old_time == visit_time:
            continue
        previous.append(
            PreviousBooking(reference, old_date, old_time, bool(row.get("alert_sent_at")))
        )
    return previous


async def _patch(
    session: Any,
    endpoint: str,
    payload: dict[str, Any],
) -> None:
    url, key = _supabase_configuration()
    async with asyncio.timeout(STORE_TIMEOUT_S):
        async with session.patch(
            f"{url}/rest/v1/call_commitments?{endpoint}",
            headers=_supabase_headers(key, "return=minimal"),
            json=payload,
        ) as response:
            if response.status not in {200, 204}:
                raise CommitmentError("store", "patch_http", response.status)


async def _mark_alerted(session: Any, call_sid: str, reference: str) -> None:
    started = monotonic()
    try:
        await _patch(session, f"id=eq.{reference}", {"alert_sent_at": now_ist().isoformat()})
    except Exception as error:
        logger.warning(
            "commitment alert marker FAILED call_sid={} error_type={} db_ms={} tg_ms=0",
            call_sid,
            type(error).__name__,
            max(0, int((monotonic() - started) * 1000)),
        )


async def _mark_superseded(
    session: Any, call_sid: str, previous: list[PreviousBooking]
) -> None:
    if not previous:
        return
    started = monotonic()
    references = ",".join(item.reference for item in previous)
    try:
        await _patch(
            session,
            f"id=in.({references})&superseded_at=is.null",
            {"superseded_at": now_ist().isoformat()},
        )
        logger.info(
            "supersede ok call_sid={} count={} db_ms={} tg_ms=0",
            call_sid,
            len(previous),
            max(0, int((monotonic() - started) * 1000)),
        )
    except Exception as error:
        logger.warning(
            "supersede FAILED call_sid={} error_type={} db_ms={} tg_ms=0",
            call_sid,
            type(error).__name__,
            max(0, int((monotonic() - started) * 1000)),
        )


async def commit_visit(
    session: Any,
    *,
    project_slug: str,
    call_sid: str,
    visit_date: date,
    visit_time: time,
    notes: Any,
    phone: str | None,
    lookup_previous: bool,
) -> CommitResult:
    db_started = monotonic()
    db_ms = 0
    tg_started: float | None = None
    try:
        async with asyncio.timeout(COMMIT_TIMEOUT_S):
            previous = (
                await _lookup_previous(session, call_sid, visit_date, visit_time)
                if lookup_previous
                else []
            )
            row = {
                "project_slug": project_slug,
                "call_sid": call_sid,
                "kind": "site_visit",
                "visit_date": visit_date.isoformat(),
                "visit_time": visit_time.isoformat(timespec="minutes"),
                "notes": _safe_note(notes, 500) if notes else None,
                "phone_normalized": phone,
            }
            reference = await store_commitment(session, row)
            db_ms = max(0, int((monotonic() - db_started) * 1000))
            logger.info(
                "commitment stored call_sid={} ref={} db_ms={} tg_ms=0",
                call_sid,
                reference[:8],
                db_ms,
            )
            alerted_previous = [item for item in previous if item.alerted]
            alert_text = booking_alert_text(
                reference,
                date_value=visit_date,
                time_value=visit_time,
                note=notes,
                phone=phone,
                replaces=[(item.visit_date, item.visit_time) for item in alerted_previous],
            )
            tg_started = monotonic()
            await send_alert(session, alert_text)
            tg_ms = max(0, int((monotonic() - tg_started) * 1000))
            logger.info(
                "commitment alert sent call_sid={} ref={} db_ms={} tg_ms={}",
                call_sid,
                reference[:8],
                db_ms,
                tg_ms,
            )
            return CommitResult(
                reference,
                tuple(alerted_previous),
                tuple(previous),
            )
    except CommitmentError as error:
        error.db_ms = max(0, int((monotonic() - db_started) * 1000))
        error.tg_ms = 0
        raise
    except AlertError as error:
        error.db_ms = db_ms
        error.tg_ms = max(
            0, int((monotonic() - (tg_started or monotonic())) * 1000)
        )
        raise
    except TimeoutError:
        if tg_started is None:
            db_ms = max(0, int((monotonic() - db_started) * 1000))
            tg_ms = 0
        else:
            tg_ms = max(0, int((monotonic() - tg_started) * 1000))
        raise CommitmentError(
            "timeout", "timeout", db_ms=db_ms, tg_ms=tg_ms
        ) from None


async def commit_callback(
    session: Any,
    *,
    project_slug: str,
    call_sid: str,
    notes: str,
    phone: str | None,
) -> CommitResult:
    db_started = monotonic()
    db_ms = 0
    tg_started: float | None = None
    try:
        async with asyncio.timeout(COMMIT_TIMEOUT_S):
            row = {
                "project_slug": project_slug,
                "call_sid": call_sid,
                "kind": "callback_request",
                "visit_date": None,
                "visit_time": None,
                "notes": _safe_note(notes, 500),
                "phone_normalized": phone,
            }
            reference = await store_commitment(session, row)
            db_ms = max(0, int((monotonic() - db_started) * 1000))
            logger.info(
                "commitment stored call_sid={} ref={} db_ms={} tg_ms=0",
                call_sid,
                reference[:8],
                db_ms,
            )
            tg_started = monotonic()
            await send_alert(
                session,
                callback_alert_text(reference, notes=notes, phone=phone),
            )
            tg_ms = max(0, int((monotonic() - tg_started) * 1000))
            logger.info(
                "commitment alert sent call_sid={} ref={} db_ms={} tg_ms={}",
                call_sid,
                reference[:8],
                db_ms,
                tg_ms,
            )
            return CommitResult(reference)
    except CommitmentError as error:
        error.db_ms = max(0, int((monotonic() - db_started) * 1000))
        error.tg_ms = 0
        raise
    except AlertError as error:
        error.db_ms = db_ms
        error.tg_ms = max(
            0, int((monotonic() - (tg_started or monotonic())) * 1000)
        )
        raise
    except TimeoutError:
        if tg_started is None:
            db_ms = max(0, int((monotonic() - db_started) * 1000))
            tg_ms = 0
        else:
            tg_ms = max(0, int((monotonic() - tg_started) * 1000))
        raise CommitmentError(
            "timeout", "timeout", db_ms=db_ms, tg_ms=tg_ms
        ) from None


async def finalize_visit(
    session: Any, *, call_sid: str, result: CommitResult
) -> None:
    """Best-effort reconciliation after the caller-facing result is delivered."""
    await _mark_alerted(session, call_sid, result.reference)
    await _mark_superseded(session, call_sid, list(result.previous))


async def finalize_callback(
    session: Any, *, call_sid: str, result: CommitResult
) -> None:
    """Best-effort alert marker after the caller-facing result is delivered."""
    await _mark_alerted(session, call_sid, result.reference)
