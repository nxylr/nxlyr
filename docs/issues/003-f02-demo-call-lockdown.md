---
name: Task spec
title: "003: Lock down /demo/call (audit F02)"
labels: task, audit
---

Status: APPROVED r3 (human, 2026-10-14). `projects.tenant_id` confirmed by the human. Build is run by the human with Codex from this worktree.
Depends on: none (F01 merged as 7cf8edf). Edits the same function as 004 (log hygiene, `server.py`) and future 006 (call record, `request_demo_call`).

## Goal

`POST /demo/call` can only dial an Indian mobile, only after a consent record is written, only within per-number, per-IP and global caps with a cooldown, and can be switched off instantly from Redis with no deploy. Anything else is refused before Exotel is contacted.

## Non-goals

- `/ws` and the F01 binding. `issue_binding` and the `ws_bind:<sid>` flow are untouched.
- `/start` (still unauthenticated; queued separately).
- OTP / proof that the submitter owns the number. Consent here is "the submitter says so", not "the callee agreed". See Risks.
- DND / TRAI scrubbing. The Exotel email is still pending; this task makes **no** DND-compliance claim anywhere (code, copy, PR).
- Schema changes or SQL execution. Table `consents` already exists.
- nginx changes. The human verified the live config on the VPS (see header path).
- Log hygiene (004), call/lead records (006), `/contact` limits.
- Bot-protection (captcha / Turnstile). Next step if scripts hit the caps.
- Showing dedicated copy for kill-switch (503) or cooldown. The existing frontend branches already show `detail` for 429 and a generic message otherwise.

## Design (files to touch and why)

### What I read (verified against `origin/main` @ 188624e)

| Where | What I found |
|---|---|
| `agent/server.py:452-518` `request_demo_call` | Validates with `E164_PHONE_NUMBER` (`^\+[1-9]\d{1,14}$`, line 59): **any country** is dialled. Calls `check_demo_rate_limits`, then `trigger_exotel_call`, then `issue_binding`. No consent, no IP, no cooldown, no kill switch. |
| `agent/server.py:315-338` `check_demo_rate_limits` | Limiting already exists, contrary to the audit wording: `demo:rate:phone:<n>` 5 per 24h (`DEMO_PHONE_LIMIT`, line 61), `demo:rate:global:<date>` 50/day (line 62). Counters are incremented **before** the dial, so a failed Exotel call burns a slot. `INCR` then `EXPIRE` is two calls: a crash between them leaves a key with no TTL (F13). |
| `agent/server.py:281-312` `get_demo_redis_client` | Shared client on `app.state.redis`; unavailable Redis raises, `request_demo_call` returns 500 `rate_limit_unavailable` (fail closed). Reused. |
| `agent/server.py:367-397` `store_contact_submission` | The existing Supabase REST insert pattern: `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` (lines 376-377), aiohttp session on `app.state.session`, **no timeout** (F12). The consent insert copies the pattern and adds a timeout. |
| `agent/kb_loader.py:57-71` `_fetch_kb` | Same `SUPABASE_SERVICE_ROLE_KEY`. Queries `projects` with `select=id,name,config,tenants!inner(slug)`, `tenants.slug=eq.<slug>`, `limit=1`, and returns only `config` (the row's other columns are dropped). Blocking `requests`, 300s cache. The only place a tenant is identified; it never reads a `tenant_id`. |
| `agent/bot.py:123-125` | `KB_PROJECT_SLUG = "nxlyr-demo"`, "single-project for now". `server.py` already imports from `bot` at module scope (line 47). |
| `agent/server.py:120-126` `DemoCallRequest` | Single field `phone_number: Any`. |
| `agent/server.py:153-251` `trigger_exotel_call` | Returns 200 with `call_sid`, or an error `JSONResponse`. Unchanged. |
| `infra/nginx/api.infrasmith.dev.conf` `location /demo/call` | `X-Real-IP $remote_addr` (overwrites client value) and `X-Forwarded-For $proxy_add_x_forwarded_for` (**appends**, so leftmost XFF is attacker-controlled). Human confirmed the live file matches for both proxy blocks. |
| `docker-compose.yml` `agent` ports | `127.0.0.1:7860` only; human confirmed on the VPS. Only nginx can reach the app. |
| `agent/Dockerfile` CMD | `uvicorn server:app`, no `--proxy-headers`; uvicorn reads only `X-Forwarded-For`, never `X-Real-IP`, so the app must read `X-Real-IP` itself. |
| `dashboard/src/components/Hero.tsx:224, 285-290` | **Correction to my r1:** `<p id="consent">` renders the exact v1 sentence, always visible below the phone card (outside the open/closed `AnimatePresence`), and the phone input's `aria-describedby="form-message consent"` points at it. My r1 grep was truncated and I wrongly said the text was absent. |
| `dashboard/index.html:306, 311` | A second copy of the same sentence in a legacy static page; its script (`:359-362`) posts `{phone_number}` only. |
| `dashboard/src/app/page.tsx` imports `Hero` from `@/components/Hero`; `package.json` build is `next build`; `dashboard/NOTES_existing_logic.md:3-5` says `index.html` is the pre-scaffold page kept "unchanged". | So the **live page renders the Hero.tsx copy**. UNVERIFIED: the Vercel project's framework/root settings (I cannot see them); a Next.js project does not serve a root `index.html`, but I did not confirm that nothing serves it. The design below works whichever copy is served. |
| `dashboard/src/lib/demoCall.ts:21-33` | `normalizeIndianNumber` already yields `+91` + 10 digits `[6-9]`; `requestDemoCall` posts only `{phone_number}`. |
| `agent/test_ws_auth.py:158-179` | `test_request_demo_call_issues_a_binding` builds a header-less `request` and patches `check_demo_rate_limits`; needs updating. |
| `agent/.dockerignore` | `COPY *.py` model: a new module ships by default; test modules must be listed to be excluded (check at build). |

### Findings that shaped the design

1. **`X-Real-IP`, not `X-Forwarded-For`** is the client IP (verified live by the human).
2. **Per-number and global caps already exist** (5/24h, 50/day). This task replaces that limiter rather than stacking a second one, and adds IP cap, cooldown, kill switch, India-only, consent.
3. **`consents.tenant_id` is NOT NULL** and nothing in `/demo/call` knows a tenant. Resolved below from the project row, not the `tenants` table.
4. **Redis-unreachable behaviour was implicit** (a 500 from a ping with no timeout). It is now stated and tested (below).

### Request flow (new order in `request_demo_call`)

1. **Kill switch.** `GET demo:kill`; any non-empty value returns 503 `{"type":"demo_disabled","error":"demo_disabled"}`. Checked first. Redis unavailable keeps today's behaviour (500 `rate_limit_unavailable`, fail closed).
2. **Phone.** Must fullmatch `^\+91[6-9]\d{9}$`, else 400 `invalid_phone_number` (same type/error strings the frontend already handles). Strict, no server-side normalisation.
3. **Consent version.** Body field `consent_text_version` is optional:
   - absent → version `"v1"`. This is the legacy request shape (the live page today and `index.html` both send no field, and both display the v1 sentence). Recorded as `v1`, truthfully.
   - present and a key of `CONSENT_TEXTS` → that version.
   - present and unknown → 400 `consent_version_unknown`, no dial. This is what stops a future page showing v2 wording from being recorded as something else by an older backend.

   The browser never supplies wording. The stored text is always `CONSENT_TEXTS[version]`, held server-side.
4. **Client IP.** `X-Real-IP`, parsed with `ipaddress.ip_address`; a value containing `%`, or that fails to parse, counts as invalid; an IPv4-mapped IPv6 address is reduced to its IPv4. Valid: the limiter key is the IPv4 address, or the IPv6 `/64` network (`2401:4900:1234:5678::/64`), and `consents.ip_address` gets the unreduced address. **Invalid or missing: the request still proceeds** with `ip_address = NULL` (column is `inet`, nullability beyond tenant/phone not stated; UNVERIFIED that it is nullable, see open question 1), limiter bucket `unknown` (one shared bucket, so it can only throttle harder), and a warning log. This replaces r1's "refuse 503": a bad header value must not turn into a failed insert or a refused real user.
5. **Cooldown.** `SET demo:cd:phone:<n> 1 NX EX <phone_cooldown>` and `SET demo:cd:ip:<key> 1 NX EX <ip_cooldown>`. A key already present: 429 `rate_limited`, `limit: "cooldown"`, `Retry-After`. Checked before the counters, so a cooled-down request does not use a slot.
6. **Counters** (per-number, per-IP over `window`, global per UTC day). Each is `SET key 0 NX EX <ttl>` then `INCR`, so a key never exists without a TTL (fixes F13 for these keys). Over the cap: 429 `rate_limit_exceeded`, `limit` of `phone`, `ip` or `global`: the shape the frontend already parses. A refused request is **not** refunded.
7. **Tenant.** Resolved once per process and cached on `app.state`, from the **project row** the KB loader already queries, not from the `tenants` table (see "tenant_id for a demo call" for the exact query). Zero rows, more than one distinct `tenant_id`, a null `tenant_id`, an HTTP error or a timeout: log, fail closed (step 8 outcome).
8. **Consent row.** Insert into `consents` (see Data touched), 5s timeout. If the tenant lookup or the insert fails: **no dial**, 500 `consent_storage_failed`, and the phone, IP and global counters are refunded (our failure, no call made). The cooldown is kept. No consent record, no dial.
9. **Dial** via `trigger_exotel_call`, then `issue_binding`, exactly as today.
10. **Refund on our-side failure only.** Two cases refund the phone, IP and global counters with `DECR` and keep the cooldown: Exotel returned non-200 (step 9), and `consent_storage_failed` (step 8). Refused and invalid requests (bad phone, unknown consent version, cooldown, cap, kill switch, Redis unavailable) are never refunded. The consent row stays after an Exotel failure (the person did submit).

### When Redis is unreachable: refuse, fail closed

Redis holds the kill switch, the caps and the cooldowns, so without it the endpoint cannot prove it is within limits. Stated behaviour:

- **Unreachable at the first Redis call** (kill-switch read, or the client's connect/ping in `get_demo_redis_client`): return 500 `{"status":"error","type":"rate_limit_unavailable","error":"rate_limit_unavailable","detail":"Demo calls are temporarily unavailable. Please try again later."}`. This is today's response, kept so the frontend's existing 500 branch shows `detail`. **No** consent row, **no** tenant lookup, **no** Exotel call, **no** binding. Nothing is written anywhere.
- **Hangs, not just errors:** every Redis operation in the guard runs under `asyncio.wait_for(..., 2.0)`; a timeout takes the same refuse path. (Today's `/demo/call` pings with no timeout; this closes that gap for F12 on this route only.)
- **Config read fails** (`HGETALL demo:config`): treated as Redis unavailable, same refusal. It does not silently fall back to defaults, because the same Redis would also be what enforces them.
- **Redis dies after the consent row and before the dial** (a counter operation fails mid-flight): refuse with the same 500, no dial; the consent row remains (insert-only record that the person submitted). Counters cannot be refunded, which only counts against the user, never for them.
- **Redis dies after the dial succeeded** (`issue_binding` or a refund fails): the call is already placed; log the error and return the normal response. Under `WS_AUTH_MODE=enforce` that call's WebSocket is denied for want of a binding. Unchanged F01 behaviour.
- A failure during a **refund** is logged and swallowed; the response is still the original failure response, and counters stay counted.

Not exercised on the live system: stopping production Redis is disruptive, so this is proven by the automated tests only.

### Adjustable numbers (no deploy, no `.env` edit)

Defaults live in `demo_guard.py`; each can be overridden at runtime by a field in the Redis hash `demo:config`, read once per request (`HGETALL`). A missing, non-integer or `< 1` value falls back to the default with a warning, so a typo cannot disable a limit.

| Field | Default | Meaning |
|---|---|---|
| `phone_limit` | 3 | accepted requests per number per `window_seconds` |
| `ip_limit` | 10 | per IP (v4 address or v6 /64) per `window_seconds` |
| `global_limit` | 50 | per UTC day, all callers |
| `phone_cooldown_seconds` | 180 | min gap between requests for one number |
| `ip_cooldown_seconds` | 30 | min gap between requests from one IP |
| `window_seconds` | 86400 | rolling window for the phone and IP counters (applies to keys created after the change) |

Why Redis and not env vars: editing the VPS `.env` recreates the redis container and must not happen while calls are in flight (`docs/memory/inbox/2026-10-13-env-edit-recreates-redis.md`).

### Operator commands (🧑 YOU, on the VPS; plain `redis-cli`, DB 0, no password, verified by the human)

```bash
# Kill switch
docker exec nxlyr_redis redis-cli SET demo:kill 1     # ON  (demo disabled)
docker exec nxlyr_redis redis-cli GET demo:kill       # "1" = disabled, (nil) = enabled
docker exec nxlyr_redis redis-cli DEL demo:kill       # OFF (demo enabled)

# Adjust a number (examples), view, and revert to default
docker exec nxlyr_redis redis-cli HSET demo:config phone_limit 10 ip_limit 30
docker exec nxlyr_redis redis-cli HGETALL demo:config
docker exec nxlyr_redis redis-cli HDEL demo:config phone_limit
docker exec nxlyr_redis redis-cli DEL demo:config      # all defaults

# Reset one NUMBER (counter + cooldown) for testing
docker exec nxlyr_redis redis-cli DEL demo:rate:phone:+91XXXXXXXXXX demo:cd:phone:+91XXXXXXXXXX

# Reset one IP (counter + cooldown). <key> is the IPv4 address, or for IPv6 the /64
# network exactly as stored, e.g. 2401:4900:1234:5678::/64. List candidates first:
docker exec nxlyr_redis redis-cli --scan --pattern 'demo:*:ip:*'
docker exec nxlyr_redis redis-cli DEL demo:rate:ip:<key> demo:cd:ip:<key>

# Reset today's global counter
docker exec nxlyr_redis redis-cli DEL demo:rate:global:$(date -u +%F)
```

The container name `nxlyr_redis` is from `docker-compose.yml`; UNVERIFIED that the live container has that exact name (the human confirmed plain `redis-cli` works inside the redis container).

### Consent wording v1 (stored verbatim, server-held constant)

> By submitting your number, you consent to receiving an AI-generated demonstration call. This is a demo — no real property transaction is involved.

Code comments (both required by the human): above `CONSENT_TEXTS` in `demo_guard.py`, and above the `<p id="consent">` in `Hero.tsx`, each saying: *this wording is recorded verbatim as version v1; changing a single character requires a new version (v2) in `CONSENT_TEXTS`, the page, and `demoCall.ts`; never edit v1 in place.* (Absent-field requests are recorded as v1, so when v2 ships v1 stays in the dict.)

### Supabase key and RLS

The server uses `SUPABASE_SERVICE_ROLE_KEY` (`server.py:377`, same as `/contact` and `kb_loader.py:50`). Supabase's `service_role` role has `BYPASSRLS`, so the insert is allowed with RLS on and no policies (`architecture.md` records the same). **Not proven for this table:** nobody has inserted into `consents` with this key yet. Exit test step 3 is the real proof; if the insert is rejected the request fails closed and no call is placed. I cannot and will not inspect the key's value to confirm it is the service-role one.

### tenant_id for a demo call

Taken from the **project row** of the project the demo bot serves, using the same lookup `kb_loader._fetch_kb` already runs (`agent/kb_loader.py:57-71`). `load_kb()` itself cannot be reused: it returns only `config`, drops the rest of the row, uses blocking `requests` (F06) and caches for 300s. So `demo_guard.py` makes the same request shape with a different `select`, over the existing aiohttp session with a 5s timeout:

```
GET {SUPABASE_URL}/rest/v1/projects
    ?select=id,tenant_id,tenants!inner(slug)
    &tenants.slug=eq.nxlyr-demo
    &limit=1
```

Differences from the KB loader's query: `select` is `id,tenant_id,tenants!inner(slug)` instead of `id,name,config,tenants!inner(slug)`. The `tenants!inner(slug)` embed and its filter are kept exactly as the KB loader has them, because that is how the project is matched to the slug; it exposes only `tenants.slug`, never `*` or `api_key`. The slug comes from `bot.KB_PROJECT_SLUG`. Result cached on `app.state` after the first success.

**Confirmed by the human (2026-10-14): `projects.tenant_id` exists.** (Earlier text: I had not seen the columns.) What supports it: the working embed `tenants!inner(slug)` needs a foreign key from `projects` to `tenants`, and `architecture.md` says `calls` carries `tenant_id` NOT NULL; but I have not seen the `projects` columns and the migration is not in the repo. If the column is absent, PostgREST answers 400, the request fails closed, and exit step 3 catches it before any real use. The human can settle it first (names only, no data, no secrets):

```sql
select column_name from information_schema.columns
where table_schema = 'public' and table_name = 'projects' order by ordinal_position;
```

**Fallback, only if `projects.tenant_id` does not exist:** `select=id,tenants!inner(id,slug)` and take the `id` from the embedded tenant object. This still reads only the `id` and `slug` columns of `tenants`, never `*`, per AGENTS.md. I will not use it unless the check above shows the column missing, and I would show you before building it.

Alternative rejected: a `DEMO_TENANT_ID` env var, which needs an `.env` edit (redis recreate) and can drift from the slug.

### Files to touch

| File | Change | Why |
|---|---|---|
| `agent/demo_guard.py` (new) | `CONSENT_TEXTS`, config defaults + `demo:config` reader, `validate_phone`, `parse_client_ip`, `kill_switch_on`, `reserve` / `refund`, `resolve_tenant_id` (project lookup), `record_consent`. Redis and the HTTP session are passed in. | Keeps the `server.py` diff to wiring, limiting conflicts with 004/006; unit-testable without importing `server`. |
| `agent/server.py` | `DemoCallRequest` gains `consent_text_version: Any = None`; `request_demo_call` (452-518) follows the flow; `check_demo_rate_limits` (315-338) and constants (61-62) removed or delegated; import `KB_PROJECT_SLUG`. `/contact` untouched. | Wiring. |
| `agent/test_demo_guard.py` (new) | Tests below. | Gate. |
| `agent/test_ws_auth.py:158-179` | Update `test_request_demo_call_issues_a_binding` for the new request shape; binding assertions unchanged. | Keeps F01 proven. |
| `docs/memory/inbox/` | Note: XFF spoofability; consents wiring; `demo:config` keys. | Memory rule. |

**Frontend, a separate commit, minimum only:**

| File | Change |
|---|---|
| `dashboard/src/lib/demoCall.ts` | Add `export const consentTextVersion = "v1"` and include `consent_text_version: consentTextVersion` in the POST body (`:31`). |
| `dashboard/src/components/Hero.tsx` | Comment only, above `<p id="consent">` (`:285`): the wording-version rule above. No visible change. |

Not touched: `dashboard/index.html` (legacy, flagged "unchanged" by `NOTES_existing_logic.md`; it carries the same sentence and sends no field, which the backend records as v1). If you want the same comment added there, say so.

No change to `infra/nginx/`, `docker-compose.yml`, `deploy.yml`, `/ws`, `ws_auth.py`.

### Deploy-gap behaviour (backend and Vercel deploy independently on merge)

- **Old page, new backend** (the page does not send the field yet): the field is absent, recorded as `v1`, request proceeds. This is the same text that page shows, so the record is accurate. No errors for visitors.
- **New page, old backend** (the page already sends `consent_text_version`): the old model ignores unknown JSON fields (pydantic v2 default) and the old route behaves as today. No errors.
- Net: merge order does not matter and there is no refused-visitor window.

## Data touched

Table `consents`, **insert only, one row per request that reaches the insert**, via Supabase REST with the service-role key. Table `projects`, **read only, one row, columns `id` and `tenant_id`** (the `tenants` table is touched only by the embed that already exists in the KB loader, exposing `slug`). No `SELECT *`, nothing from `tenants` beyond `slug`. No schema change; no SQL executed by any agent.

| `consents` column | Value |
|---|---|
| `tenant_id` uuid NOT NULL | `projects.tenant_id` of the `nxlyr-demo` project (cached lookup; column confirmed by the human) |
| `lead_id` uuid null | omitted (null); `/demo/call` creates no lead (006) |
| `phone_normalized` varchar(32) NOT NULL | `+91XXXXXXXXXX` (13 chars) |
| `action` | `granted` |
| `source` | `web_form` |
| `consent_text` text | `CONSENT_TEXTS[version]` verbatim |
| `consent_text_version` varchar(20) | `v1` |
| `page_url` text | **origin only**: the `Origin` header; if absent, scheme + host of `Referer`; else NULL. Path and query are never stored. |
| `ip_address` inet | validated address from `X-Real-IP`, or NULL if invalid/missing |
| `user_agent` text | `User-Agent`, truncated to 512 chars |
| `occurred_at`, `created_at` | table defaults (`now()`); not sent |

`ip_address`, `page_url` and `user_agent` are nullable per the human (migration). UNVERIFIED: whether `action`/`source` are CHECK constraints or enums; this does not change the insert.

Redis keys: `demo:kill`, `demo:config` (hash), `demo:cd:phone:<n>`, `demo:cd:ip:<key>`, `demo:rate:phone:<n>` (existing name, so existing counters carry over), `demo:rate:ip:<key>`, `demo:rate:global:<date>` (existing name). No flush or migration needed.

## Acceptance tests (automated)

**Test module:** `agent/test_demo_guard.py` (new; a `unittest.IsolatedAsyncioTestCase`, same style as `agent/test_ws_auth.py`). Guard logic is tested by importing `agent.demo_guard` directly; the endpoint-level cases call `server.request_demo_call` the way `test_ws_auth.py:158-179` does (import via the same `import_server_without_dotenv` helper, `trigger_exotel_call` patched).

**Where the tests get Redis: they do not get one.** No Redis server, no Docker, no network. The module defines its own in-memory fakes:
- `FakeRedis`: async `get`, `set(key, value, ex=None, nx=False)`, `incr`, `decr`, `delete`, `hgetall`, `hset`, `expire`, with a dict of values and a dict of TTLs so tests can assert "no key exists without a TTL", plus a call log for ordering assertions. Returns strings like a `decode_responses=True` client.
- `UnavailableRedis` (every method raises `ConnectionError`) and `HangingRedis` (every method awaits a never-set event), for the Redis-down tests.
- `FakeSession`: scripted async-context-manager `get`/`post` for the Supabase `projects` lookup, the `consents` insert and nothing else, recording URL, params and JSON body, able to return HTTP 400/500 or raise `TimeoutError`. Dummy `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` values are injected with `patch.dict(os.environ, ...)`; no real secret is read or needed.
- The `request` object is a `SimpleNamespace` with `app.state.{redis,session}` and a `headers` dict with lowercase keys (as Starlette presents them).

Limit of this approach: a fake proves our logic, not Redis's own semantics. The real-Redis behaviour (`SET NX EX`, `INCR` keeping the TTL, `HGETALL` decoding, `DEL` resets) is covered by exit steps 4, 6 and 7 against the live Redis.

Run:

```bash
MAIN="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"; PY="$MAIN/agent/venv/bin/python"
"$PY" -m unittest agent.test_demo_guard agent.test_ws_auth
(cd agent && "$PY" -c "import server, week2_latency_observer")
```

- [ ] Phone: `+919876543210` accepted; `+14155550100`, `+911234567890`, `+91987654321`, `9876543210`, `None`, an int, `+9198765432100` refused 400, no Redis write, no insert, no dial.
- [ ] Kill switch: `demo:kill` set refuses 503 `demo_disabled`, touching no counter, no tenant lookup, no insert, no dial; clearing it restores acceptance.
- [ ] Consent version: absent recorded `v1`; `"v1"` recorded `v1`; `"v2"` (not in dict) 400 `consent_version_unknown`; any browser-sent text field is ignored: the inserted `consent_text` always equals the server constant.
- [ ] Consent row: `action == "granted"`, `source == "web_form"`, `phone_normalized`, `tenant_id`, `ip_address`, truncated `user_agent`, `page_url` from headers (Referer over Origin); `lead_id`, `occurred_at`, `created_at` not sent.
- [ ] Tenant lookup: the request goes to `/rest/v1/projects` (not `/tenants`) with `select=id,tenant_id,tenants!inner(slug)`, `tenants.slug=eq.nxlyr-demo`, `limit=1`; the URL contains no `*` and no `api_key`; the `tenant_id` from the row is what the insert sends; cached (a second request makes no second lookup); 0 rows, a null `tenant_id`, HTTP 400/500 and a timeout each fail closed with no dial.
- [ ] Insert failure or timeout, and tenant-lookup failure: no dial, 500 `consent_storage_failed`, phone/IP/global counters refunded, cooldown keys kept.
- [ ] Order: tenant lookup, then insert, then Exotel call (call-order assertion).
- [ ] `page_url` is origin only: an `Origin` of `https://nxlyr.vercel.app` is stored as is; a `Referer` of `https://nxlyr.vercel.app/a/b?x=1` (no Origin) is stored as `https://nxlyr.vercel.app`; neither header gives NULL; a path or query is never stored.
- [ ] IP: `X-Forwarded-For` ignored even when `X-Real-IP` is present; garbage, empty, missing, and `fe80::1%eth0` give `ip_address=None`, bucket `unknown`, request still proceeds; IPv4-mapped IPv6 reduced to IPv4; two addresses in one /64 share a bucket; the unreduced address is stored.
- [ ] Caps: 4th request for a number (after clearing cooldown) 429 `limit: "phone"`; 11th from an IP 429 `limit: "ip"`; 51st global 429 `limit: "global"`. Response shape matches what `demoCall.ts` parses (`type: rate_limited`, `error: rate_limit_exceeded`).
- [ ] Cooldown: second request inside the window 429 `limit: "cooldown"` with `Retry-After`, counters unchanged.
- [ ] Atomicity: whenever a counter key exists in the fake, it has a TTL.
- [ ] Refund: Exotel non-200 **and** `consent_storage_failed` each decrement the phone, IP and global counters exactly once and **keep** the cooldown keys; invalid phone, unknown consent version, cooldown, cap, kill switch and Redis-unavailable requests refund nothing.
- [ ] Config: `demo:config` values override the defaults (`phone_limit=1` makes the 2nd request 429); `"abc"`, `"0"`, `"-3"` fall back to defaults.
- [ ] Redis unreachable (fake raises `ConnectionError` on every call): 500 `rate_limit_unavailable`, and the fakes record **no** tenant lookup, **no** consent insert, **no** Exotel call, **no** binding write.
- [ ] Redis hanging (fake never returns): the request returns 500 `rate_limit_unavailable` within the 2s guard timeout, same no-side-effects assertions.
- [ ] `HGETALL demo:config` raising is treated as Redis unavailable (500), not as "use defaults".
- [ ] Redis failing after the consent insert but before the dial: 500, no Exotel call, insert already recorded. Redis failing during `issue_binding` or a refund after a successful dial: the normal 200 is still returned and the error is logged.
- [ ] F01 regression: success path still writes `ws_bind:<call_sid>` with `{"issued_at": int}` and 120s TTL. `/ws` tests untouched and green.
- [ ] Frontend commit: `npm ci && npm run build && npm run lint` pass in `dashboard/`; the POST body contains `consent_text_version: "v1"`.

Known baseline: `agent.test_kb_loader` has 5 failures on `main` (F23), unrelated.

## Exit test (🧑 YOU, on real calls and infrastructure)

Not passed until every step is observed. Use your own phone. Steps 3 and 5 each place one real call. Paste only the lines requested, never logs.

Before: merge is a deploy of both halves. Check container health twice, a few seconds apart (`docker ps`, `docker inspect -f '{{.State.Health.Status}}' nxlyr_agent`).

1. 🤖/👀 **Non-Indian number refused, no call.**
   ```bash
   curl -s -i -X POST https://api.infrasmith.dev/demo/call -H 'Content-Type: application/json' \
     -d '{"phone_number":"+14155550100","consent_text_version":"v1"}'
   ```
   Expect `HTTP 400`, `"type":"invalid_phone_number"`. No phone rings.
2. 🧑 **Unknown consent version refused, no call.** Same with your own `+91…` number and `"consent_text_version":"v9"`. Expect 400 `consent_version_unknown`.
3. 🧑 **Real call from the website.** Open the live site, confirm the v1 sentence is visible under the phone card, submit your number. 👀 Phone rings and the agent speaks. Then in the Supabase SQL Editor (human-run): `select * from consents order by created_at desc limit 3;` and confirm one new row: `action = granted`, `source = web_form`, `consent_text` equal to the sentence, `consent_text_version = v1`, `tenant_id` set, your number in `phone_normalized`, your public IP in `ip_address`, your browser's `user_agent`, and `https://nxlyr.vercel.app` (origin only, no path or query) in `page_url`. This is also the proof that the service key can insert past RLS.
4. 🧑 **Cooldown.** Within 3 minutes of step 3, submit the same number again on the site. Expect the cooldown message and no ring; `select count(*) from consents` unchanged.
5. 🧑 **Real client IP behind nginx.** After the 180s cooldown, from your machine:
   ```bash
   curl -4 -s https://api.ipify.org; echo
   curl -4 -s -i -X POST https://api.infrasmith.dev/demo/call -H 'Content-Type: application/json' \
     -H 'X-Forwarded-For: 203.0.113.9' -H 'X-Real-IP: 198.51.100.7' \
     -d '{"phone_number":"+91XXXXXXXXXX"}'
   ```
   👀 The new row's `ip_address` equals the ipify value, **not** `203.0.113.9` or `198.51.100.7`, and is not null or a `127.*`/`172.*` address. (The request also omits the consent field on purpose: it must be accepted and recorded as `v1`.) If it fails, stop and report (rule 9).
6. 🧑 **Kill switch.** On the VPS: `docker exec nxlyr_redis redis-cli SET demo:kill 1`; repeat the step 1 curl with your own valid number: expect 503 `demo_disabled`, no ring, no new row. Then `docker exec nxlyr_redis redis-cli DEL demo:kill` and repeat step 1 as written: expect 400 `invalid_phone_number`, not 503.
7. 🧑 **Adjustable numbers + reset.** `docker exec nxlyr_redis redis-cli HSET demo:config phone_cooldown_seconds 5`, wait out step 5's cooldown with the reset command for your number, then confirm a second submission 10 seconds after a first is accepted (one more real call), then `DEL demo:config`. Shows both the override and the reset command work.
8. 👀 **F01 intact.** `docker logs nxlyr_agent --since 15m 2>&1 | grep -c "ws_auth bound ok"` is at least 1 for the step 3 call. Paste only the count.

Per-number, per-IP and global caps are proven by the automated tests only; hitting them for real costs several calls (step 7 shows the knobs are live).

## Risks and rollback

- **Consent is not proof the callee agreed.** Anyone can type someone else's number. Caps limit damage; OTP would close it (out of scope).
- **Consent is not DND clearance.** Do not describe this as TRAI/DND compliance until Exotel answers.
- **Absent field is recorded as v1 forever.** True and safe while the live page shows v1; it stays true after v2 ships because absent still means the legacy page. The risk is a wording edit without a version bump: the stored record would then be inaccurate. Mitigated only by the code comments and review.
- **A bad `X-Real-IP` no longer refuses**; it collapses into the shared `unknown` bucket (10/24h). If the header path ever broke, real users would soon hit that cap. Exit step 5 and a periodic `select count(*) from consents where ip_address is null` catch it.
- **Tenant lookup is a new hard dependency** on first request after a restart (cached afterwards): a Supabase outage then blocks demo calls. Intended: fail closed.
- **Refund and cooldown together:** after our-side failures the counters are refunded but the cooldown is kept, so a visitor retrying through a Supabase or Exotel outage waits 180s between tries and cannot burn the daily cap. Retry traffic is bounded by the cooldown, not by refunds.
- **`projects.tenant_id` unverified:** if the column is missing every demo call fails closed with 500 `consent_storage_failed` until the lookup is fixed. That is loud, immediate (exit step 3) and refunds counters, but it is an outage if merged without the check below.
- **CGNAT.** Many Indian mobile users share one public IP; 10/24h and a 30s cooldown could refuse legitimate visitors in a room. `demo:config` is the dial; the kill switch is the brake.
- **Same-function conflicts.** 004 and 006 touch `server.py`/`request_demo_call`; recommended order is 003 first.
- **Rollback:** (a) instant, no deploy: `SET demo:kill 1`; (b) revert the merge commit (human merges; deploy re-runs). Consent rows already written stay; they are insert-only. Old Redis keys are compatible with both versions. The frontend commit can be reverted alone with no backend effect.

## Open questions for me

Resolved by you in r2 review: `ip_address`, `page_url`, `user_agent` nullable; `page_url` origin only; `index.html` untouched; refunds as in step 10.

None open. The `projects.tenant_id` check is done; the `tenants!inner(id,slug)` fallback is not needed.
