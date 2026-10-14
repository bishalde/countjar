# CountJar v2 — Design

Date: 2026-10-14 · Status: approved in chat (brainstorming session)

## Goal

Turn CountJar from an anonymous URL counter into an account-based counter platform
with the feature set of counterapi.dev (workspaces, public/private counters, scoped
API tokens, up/down/set/reset/stats, rate limits, dashboard) plus the widget/event
features of counterapi.com (view/like/poll/rating widgets, badges, tracking pixel,
event properties, time windows, aggregates), with a modern Tailwind UI.

## Decisions (from the user)

- **Accounts required.** No anonymous counters. The only open counter is the public
  demo `demo/test-counter`, which anyone can hit to try the API.
- **Sign-up/sign-in = phone OTP via Twilio Verify.** Passwordless. Uses the app
  owner's Twilio credentials from the environment.
- **Budget: 5 counters per user** (counted across the workspaces they own).
- `/api/v1` and existing anonymous data are dropped.
- **Stack:** Flask + Jinja + Tailwind (standalone build, compiled CSS committed) +
  Alpine.js + Chart.js. MongoDB Atlas. Deployed on Vercel (serverless; no background
  workers).
- `.env.example` is removed; env vars are not advertised to end users.
- Docs and the how-to guide ship as a **separate PR** after the app PR.

## Limits

| Limit | Value | Env override |
|---|---|---|
| Counters per user (owned workspaces) | 5 | `COUNTER_LIMIT` |
| Workspaces owned per user | 3 | `WORKSPACE_LIMIT` |
| Counted writes per user per day | 10,000 | `DAILY_LIMIT` |
| API requests per minute per path per caller | 600 | `RATE_LIMIT` |
| OTP sends | 5/h per phone, 10/h per IP | — |

## Environment

`SECRET_KEY`, `MONGODB_URI`, `MONGODB_DB` (default `countjar`), `TWILIO_ACCOUNT_SID`,
`TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SID`, `TWILIO_PHONE_NUMBER` (SMS milestones),
`VERIFY_DEV_MODE=1` (local only: prints OTP to console; refused when `VERCEL` is set).

## Architecture

Package `countjar/` with an app factory; root `app.py` exposes `app` for Vercel.

| Module | Responsibility |
|---|---|
| `config.py` | env → settings, limits |
| `db.py` | client, collections, indexes, demo seed |
| `verify.py` | Twilio Verify send/check (+ dev mode) |
| `accounts.py` | users, workspaces, members, budgets |
| `tokens.py` | API token create/authenticate/revoke |
| `counters.py` | counter CRUD and **every mutation** (bounds, uniques, like/vote/rate, events, buckets, quota, milestones) |
| `stats.py` | windows, history series, workspace summary, CSV/JSON export |
| `notify.py` | milestone firing: webhook (HMAC-signed, SSRF-guarded) and Twilio SMS |
| `ratelimit.py` | fixed-window limiter on Mongo |
| `visitors.py` | client IP + salted visitor hash |
| `auth.py` | blueprint: login, verify, onboarding, logout |
| `web.py` | blueprint: dashboard pages and form actions (CSRF-protected) |
| `api.py` | blueprint: `/api/v2` |
| `embed.py` | blueprint: `/embed.js`, `/badge/...svg`, `/p/...gif` |

## Data model (MongoDB)

- `users {phone (unique, E.164), name, created_at, last_login}`
- `workspaces {slug (unique), name, owner_id, members:[{user_id, role}], created_at}`
- `counters {workspace_id, name, type: count|like|poll|rating, visibility: public|private,
  description, count, ups, downs, step, min, max, unique: none|daily|once,
  yes, no, rating_sum, rating_count, created_at, updated_at}` — unique (workspace_id, name)
- `events {counter_id, workspace_id, ts, action, delta, value, visitor, referrer, props}` — TTL 90 days
- `buckets {counter_id, hour, ups, downs, events}` — unique (counter_id, hour)
- `marks {counter_id, kind, visitor, expires_at}` — unique (counter_id, kind, visitor); TTL
- `usage {user_id, day, count}` — unique (user_id, day); TTL 3 days
- `tokens {workspace_id, name, prefix, hash (unique), scopes, created_by, created_at, last_used, revoked}`
- `milestones {counter_id, threshold, channel: webhook|sms, target, secret, fired_at, last_error}`
- `ratelimits {_id: key:window, count, expires_at}` — TTL

## Counter semantics

- `up`/`down`: delta = `by` (default counter `step`). Result clamped to `min`/`max` when set.
  Anonymous callers may only use the counter's step.
- `set?value=` (must lie within bounds), `reset` → 0 (or min if min > 0).
- Unique mode: `daily` counts a visitor once per UTC day, `once` counts them once ever.
  A non-counted hit returns `counted: false` and the unchanged count.
- `like` (type like): once per visitor. `vote?choice=yes|no` (type poll): once per visitor.
  `rate?value=1..5` (type rating): once per visitor; returns average.
- Every counted mutation writes an event (with referrer host and extra query params as
  `props`), bumps the hourly bucket, increments the owner's daily usage, and checks milestones.
- Over the daily limit → 429 `quota_exceeded`.

## API v2

Base `/api/v2`. JSON errors `{"error": {"code", "message"}}`. CORS `*`.
Rate-limit headers `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `Retry-After` on 429.
Auth: `Authorization: Bearer cj_…` (workspace-scoped token, scopes `read`/`write`/`admin`);
`?token=` is also accepted. Session cookies are **not** accepted (prevents CSRF via GET).

| Endpoint | Public counter, no token | Private counter |
|---|---|---|
| `GET /<ws>/<name>` (`?window=15m\|1h\|24h\|7d\|30d`) | yes | read |
| `GET /<ws>/<name>/stats` | yes | read |
| `GET /<ws>/<name>/history?range=24h\|7d\|30d&format=json\|csv` | yes | read |
| `GET\|POST /<ws>/<name>/up` | yes (step only) | write |
| `GET\|POST /<ws>/<name>/like`, `/vote`, `/rate` | yes | write |
| `GET\|POST /<ws>/<name>/down`, `/set`, `/reset` | no → write | write |
| `GET /<ws>/<name>/events?format=json\|csv` | read | read |
| `GET /<ws>` (summary, top counters, totals) | public counters only | read → all |
| `POST /<ws>/counters`, `PATCH\|DELETE /<ws>/<name>` | admin | admin |

The demo counter additionally allows `down` without a token.

## Embeds

- `/embed.js` scans `.countjar` elements: `data-workspace`, `data-counter`, `data-type`
  (`count|like|poll|rating`), `data-readonly`, `data-icon`, `data-label`, `data-abbreviate`,
  `data-hide-zero`, `data-no-anim`, `data-theme (light|dark|glass)`, `data-color`, `data-bg`,
  `data-accent`, `data-window`, `data-question`, `data-start` (display offset). Renders in a
  Shadow DOM so host CSS cannot break it.
- `/badge/<ws>/<name>.svg?style=flat|social|big&label=&color=&labelColor=&readonly=1&abbreviate=1`
  increments public `count` counters unless `readonly=1`.
- `/p/<ws>/<name>.gif?<props>` — 1×1 GIF that increments a public counter and records props.

## Milestones

Threshold crossing on the way up fires once (atomic `fired_at` claim); can be re-armed.
Webhook: `POST` JSON, `X-CountJar-Signature: sha256=<hmac>`, 3 s timeout, https only and
non-private IPs only. SMS: via `TWILIO_PHONE_NUMBER`, target must be a workspace member's
verified phone.

## UI

Dark-first with light toggle; warm "honey jar" amber accent on ink; display + mono type with
tabular numerals. Pages: landing (live demo counter, feature grid, code tabs, widget gallery),
login (phone with country picker → 6-box OTP with resend timer), onboarding, workspace overview
(KPI tiles incl. budget and today-vs-limit, 24h chart, activity feed, top counters), counters
list (search/filter, create modal with budget meter), counter detail (big number, quick actions,
24h/7d/30d chart, embed builder with live preview, badge builder, milestones, events table with
export, settings, danger zone), tokens (show-once), members, workspace settings, account.

## Testing

pytest + mongomock; Twilio and outbound HTTP mocked. Unit tests per service module, API auth
matrix, embed outputs, dashboard access control and CSRF.
