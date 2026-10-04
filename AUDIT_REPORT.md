# Holishared — Exhaustive Adversarial Security Audit

**Date:** 2026-10-04
**Scope:** Full codebase — `app/` (all blueprints, models, templates, static), `nginx/saas.conf`, `Dockerfile`, `docker-compose.yml`, `manage.py`, `requirements.txt`, `systemd/saas.service`, `scripts/`, `.env`, CI.
**Method:** Systematic source review of every file + dynamic verification of attack scenarios against a live test instance (215/215 existing tests pass; findings below were reproduced where noted "verified").
**Stack:** Flask 3.1 + SQLAlchemy 2.1 (SQLite) + Flask-Login + Flask-WTF + Flask-Limiter + Flask-Babel + Waitress + Nginx + Redis.

---

## 1. Executive Summary — Top 5 Critical Findings

| # | Finding | Why it matters |
|---|---------|----------------|
| 1 | **Guest code brute-force / enumeration (CRIT-2)** | Guest access is a 4–8 char user-chosen code checked at `/e/<code>/mycode` with **no rate limit**, and `/e/<code>/join` leaks whether a code exists ("déjà pris"). A 4-char code = 36⁴ ≈ 1.7 M combinations. Any attacker can take over a guest identity and read/modify all event data (photos with GPS, chat, costs, PII-adjacent logistics). |
| 2 | **Rate limiter is broken behind the reverse proxy (CRIT-1)** | `key_func=get_remote_address` with **no ProxyFix** → behind Nginx every request comes from the proxy IP. The `default_limits=["100 per hour"]` bucket is **shared by all users**: the whole app locks out after 100 req/h (self-DoS), and every per-endpoint limit is effectively disabled. |
| 3 | **Superadmin login: no brute-force protection + weak password (CRIT-3)** | `/admin/login` has no rate limit (verified: unlimited attempts). The deployed `.env` contains `SUPERADMIN_PASSWORD=password`. The single superadmin account is the owner of **every** event in the system — one compromised login = total platform compromise. |
| 4 | **SECRET_KEY fallback `"dev"` / empty-string risk (CRIT-4)** | `SECRET_KEY = os.environ.get("SECRET_KEY", "dev")`. If the env var is missing (or empty in Docker, where `SECRET_KEY=${SECRET_KEY}` passes an empty string), session cookies are signed with a known/empty key → **anyone can forge a session cookie** and impersonate the superadmin or any guest. |
| 5 | **No TLS in the deployment stack + `SESSION_COOKIE_SECURE=false` (HIGH-1)** | Nginx listens on port 80 only; `.env` has `SESSION_COOKIE_SECURE=false` while `APP_URL=https://holi.benetnath.fr`. Session cookies (the only auth mechanism) are transmitted over plain HTTP → sniffable on any untrusted network. HSTS on an HTTP response is a no-op. |

**Overall posture:** The application layer is notably well-built — CSRF tokens on every state-changing form, Jinja2 auto-escaping everywhere (no `|safe`), consistent event-scoped queries (no classic IDOR), non-root Docker user, `.env` never committed to git, sane security headers, and a real test suite. The critical weaknesses are concentrated in **authentication/credential design** (short guest codes, single weak superadmin), **rate limiting** (broken keying + gaps), and **deployment configuration** (no TLS, weak secrets, debug mode on 0.0.0.0).

---

## 2. Full Findings Table (sorted by severity)

| ID | Severity | Title | Location |
|----|----------|-------|----------|
| CRIT-1 | Critical | Rate limiter keys on proxy IP (no ProxyFix) → app-wide shared 100/h bucket; per-IP limits disabled | `app/extensions.py:19-28`, `nginx/saas.conf:66-77` |
| CRIT-2 | Critical | Guest code brute-force + enumeration oracle; no rate limit on `mycode`/`join`; codes stored in plaintext | `app/events/__init__.py:234-304`, `app/models.py:88-105` |
| CRIT-3 | Critical | Superadmin login unlimited brute-force; weak password `password` in `.env`; single account owns all events | `app/auth/__init__.py:35-53`, `.env:21-22` |
| CRIT-4 | Critical | `SECRET_KEY` falls back to `"dev"`; empty-string in Docker → session cookie forgery → full takeover | `app/__init__.py:21`, `docker-compose.yml:44` |
| HIGH-1 | High | No TLS termination in stack; `SESSION_COOKIE_SECURE=false` in production; HSTS on HTTP | `nginx/saas.conf:14-18`, `.env:13,26` |
| HIGH-2 | High | `manage.py run` starts Flask **debug mode** on `0.0.0.0` (Werkzeug debugger → RCE if PIN compromised) | `manage.py:293-299`, `.env:7` |
| HIGH-3 | High | Cross-event data leak: `add_expense` accepts any `household_id` (other events' households shown on costs page) — **verified** | `app/costs/__init__.py:241-310` |
| HIGH-4 | High | Live secrets in workspace `.env` (Gmail app password, superadmin password, VAPID private key); DB file mode 644 | `.env:22,36,48`, `instance/holishared.db` |
| HIGH-5 | High | Media upload trusts client `Content-Type`; original extension kept → polyglot `evil.html` stored as `uuid.html` — **verified** | `app/media/__init__.py:137,159-161` |
| HIGH-6 | High | Unpinned dependencies (`>=`); Pillow parses untrusted uploads (EXIF) — supply-chain / parser CVE exposure | `requirements.txt`, `app/media/__init__.py:56-93` |
| MED-1 | Medium | Host-header injection in `invite_qr` → QR encodes attacker-controlled host (phishing) | `app/events/__init__.py:179` |
| MED-2 | Medium | SQLite concurrency: 4 Waitress threads, no WAL, no busy_timeout → `database is locked` 500s; media-quota TOCTOU race | `Dockerfile:30`, `app/freemium.py:69-88` |
| MED-3 | Medium | Unhandled `ValueError` → HTTP 500 on `/e/new` with malformed dates — **verified** | `app/events/__init__.py:62-63` |
| MED-4 | Medium | Service worker caches **authenticated** pages in Cache Storage (PII on shared devices) | `app/static/js/service-worker.js:44-53` |
| MED-5 | Medium | Rate-limit gaps: chat, media upload, costs, lists, voting, logistics, invite-email; `RATE_LIMIT_INVITE` defined but never used | multiple (see §3.5) |
| MED-6 | Medium | Creator verification token: not constant-time, not single-use, no expiry, not bound to event | `app/events/__init__.py:378-389` |
| MED-7 | Medium | Cost manipulation: any guest sets arbitrary amount/exchange rate; household headcount unbounded server-side (`num_adults=999999` accepted — **verified**) | `app/costs/__init__.py:178-310` |
| MED-8 | Medium | Email format never validated (`email-validator` in requirements but unused); `not-an-email` accepted as `creator_email` — **verified** | `app/events/__init__.py:53,68-71`, `requirements.txt:11` |
| MED-9 | Medium | Nginx `/static/` location defines its own `add_header` → server-level security headers dropped on static responses; HSTS emitted on HTTP | `nginx/saas.conf:49-56` |
| MED-10 | Medium | `load_dotenv(override=True)` → `.env` overrides real environment (inverted precedence; surprising in Docker/systemd) | `app/__init__.py:14` |
| LOW-1 | Low | `unclaim_item` ownership check based on display name → same-name guests can unclaim each other's items | `app/lists/__init__.py:319-321` |
| LOW-2 | Low | Any guest can resolve any payment request (no author/creator check) | `app/costs/__init__.py:504-526` |
| LOW-3 | Low | `sqlite:///:memory:` is rewritten to a **file** named `:memory:` in the project root (tests + prod misconfig) | `app/__init__.py:29-33` |
| LOW-4 | Low | `manage.py db-shell` opens wrong DB path (`saas.db` instead of `instance/holishared.db`) | `manage.py:367-371` |
| LOW-5 | Low | `/health` leaks disk usage ratio, DB status, uptime (unauthenticated info disclosure) | `app/__init__.py:208-228` |
| LOW-6 | Low | CSP `script-src 'unsafe-inline'` weakens XSS defense-in-depth (required for Alpine inline handlers) | `app/__init__.py:197` |
| LOW-7 | Low | `invite.html` renders `event.max_guests` — property doesn't exist (silent blank; bug, not security) | `app/templates/events/invite.html:51` |
| LOW-8 | Low | EXIF extraction reads entire upload (≤50 MB) into memory per request, ×4 threads | `app/media/__init__.py:56-93` |
| LOW-9 | Low | `get_limits()` references undefined `MEDIA_QUOTA_FREE_MB` → KeyError if ever called (dead code) | `app/freemium.py:33-41` |
| LOW-10 | Low | Redis has no password (internal network only — acceptable, note for hardening) | `docker-compose.yml:20-27` |
| LOW-11 | Low | Chat polls every 5 s per visitor (load amplification; interacts with CRIT-1 bucket) | `app/templates/chat/index.html:54` |
| LOW-12 | Low | Guest code is the sole credential, displayed in plaintext on dashboard (shoulder-surfing / screen-share risk) — design note | `app/templates/events/dashboard.html:14-18` |
| LOW-13 | Low | Session cookie has no explicit `SameSite` (browser default Lax — acceptable; make explicit) | `app/__init__.py:22-23` |

---

## 3. Detailed Analysis

### 3.1 Authentication & Authorization

#### CRIT-1 — Rate limiter broken behind the reverse proxy
- **Vulnerability:** `Limiter(key_func=get_remote_address, default_limits=["100 per hour"])` (`app/extensions.py:19-28`). `get_remote_address()` returns `request.remote_addr`. There is **no `ProxyFix`** anywhere in the codebase (verified by grep) and no `trusted_proxies` config. In both deployment modes (Docker: app behind the `nginx` container; systemd: app behind host nginx), `remote_addr` is the proxy address, so **all users share one key**.
- **Consequences (both directions):**
  1. *Availability:* after ~100 requests/hour **total** (all users combined), every request returns 429. A handful of active users (chat polls every 5 s alone generate 12 req/min per visitor) lock the entire app out — a self-inflicted DoS.
  2. *Security:* every per-endpoint limit (`10 per hour` on event creation, `20 per hour` on activities) is also keyed on the proxy IP, so it protects nothing per-user; an attacker behind the same proxy as everyone else is only limited by the shared global bucket.
- **Example:** 3 users chatting → ~36 req/min → app-wide 429 within ~17 minutes.
- **Solution:**
  - Add `werkzeug.middleware.proxy_fix.ProxyFix(app.wsgi_app)` (or `app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)`) and configure Flask-Limiter with `trusted_proxies` / `proxy_fix` settings so `get_remote_address` sees the real client IP from `X-Forwarded-For`.
  - Alternatively, drop the app-level `default_limits` and rely on Nginx `limit_req` for coarse limits + explicit per-endpoint limits in the app.
  - Add a test that asserts the limiter key changes with `X-Forwarded-For`.

#### CRIT-2 — Guest code brute-force & enumeration
- **Vulnerability:** Guest identity = a **user-chosen** code of **4–8** lowercase alphanumerics (`app/events/__init__.py:251-254`), stored **in plaintext** (`app/models.py:94`), checked at `POST /e/<code>/mycode` with **no rate limit** (only the broken global default). Verified: 5 consecutive wrong-code attempts → all 200, no 429.
  - 4-char code: 36⁴ ≈ **1.68 M** possibilities. With per-IP limits disabled (CRIT-1) or via IP rotation, this is brute-forceable in hours.
  - **Enumeration oracle:** `POST /e/<code>/join` with a candidate code returns *"Ce code est déjà pris par un autre invité."* if the code exists → an attacker can enumerate which codes are taken, then brute-force only the live ones (or target a specific victim whose code length they guess).
- **Impact:** Full guest takeover: read chat, photos (with GPS coordinates), costs, logistics (access codes, addresses), RSVPs; modify/delete content; act as the victim in the activity log.
- **Example:**
  ```
  for c in $(seq 0 16777215 | ...); do
    curl -d "guest_code=$c" https://holi.benetnath.fr/e/<event>/mycode
  done
  ```
- **Solution:**
  - Enforce a **minimum length of 8** (ideally 10+) and a complexity check; store a **hash** (e.g., SHA-256 with per-code salt) of the guest code, not the plaintext.
  - Add `@limiter.limit("10 per hour")` (or stricter, e.g. `5 per 15 minutes`) on `my_code` and `guest_access`, keyed per IP **and** per event code.
  - Remove the enumeration oracle: return a generic error on `join` for taken codes, or rate-limit the join POST heavily.
  - Consider time-limited, server-generated join tokens (one-time) instead of permanent user-chosen codes.

#### CRIT-3 — Superadmin login
- **Vulnerability:** `POST /admin/login` (`app/auth/__init__.py:35-53`) has **no rate limit** (verified: unlimited wrong-password attempts). The password is compared in plaintext against `SUPERADMIN_PASSWORD`. The deployed `.env` contains `SUPERADMIN_PASSWORD=password`.
- **Aggravating factor:** there is **no user registration** — the superadmin is the *only* creator account, and every event's `creator_id` points to it. Compromise = read/modify/delete **all** events, all guests' data, all media, plus the ability to create events and invite emails.
- **Example:** `hydra -l admin@example.com -P rockyou.txt https://holi.benetnath.fr/admin/login` (no lockout, no CAPTCHA, no limit).
- **Solution:**
  - `@limiter.limit("5 per 15 minutes")` on login (per IP + per email), plus account-level lockout/backoff after N failures.
  - Rotate the superadmin password to a long random value **now** (the current one is `password`); store it only in the environment.
  - Long term: replace the single superadmin with per-creator accounts (hashed passwords, e.g., `werkzeug.security`), so one credential doesn't own the whole platform.

#### CRIT-4 — SECRET_KEY fallback / empty string
- **Vulnerability:** `app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev")` (`app/__init__.py:21`). Two failure modes:
  1. Env var **missing** → key is literally `"dev"` (public, in every commit's context).
  2. Docker: `SECRET_KEY=${SECRET_KEY}` — if the host variable is unset, the container gets an **empty string**, and `os.environ.get` returns `""` (the `"dev"` default only applies when the variable is absent). An empty signing key is trivially known.
- **Impact:** Flask session cookies are signed (itsdangerous), not encrypted. With a known key, an attacker **forges a session cookie** containing `_user_id=<superadmin id>` → instant full login, or `guest_<code>=<id>` → any guest identity. No server-side session store means no revocation.
- **Example:**
  ```python
  from itsdangerous import URLSafeTimedSerializer
  s = URLSafeTimedSerializer("dev", salt="cookie-session", signer_kwargs={"key_derivation":"hmac-sha1","digest_method":"sha512"})
  print(s.dumps({"_user_id": "<creator-id>"}))
  ```
- **Solution:** Fail fast at startup: `if not secret_key or secret_key in ("dev", ""): raise RuntimeError`. Generate a 64-hex key per deployment; never allow empty.

#### Session management (positive + notes)
- Sessions are client-side signed cookies: no classic session-fixation (cookie is re-signed on login). `SESSION_COOKIE_HTTPONLY=True` ✓. No explicit `SameSite` (LOW-13). `PERMANENT_SESSION_LIFETIME=86400`; `remember=True` on superadmin login gives a 30-day remember cookie — acceptable, but consider shortening.
- Guest identity is stored per-event in the session (`session[f"guest_{code}"]`) and re-validated against the DB on every request with an `event_id` scope check — correct design (prevents cross-event session reuse).

### 3.2 Input Validation & Injection

- **SQL injection:** none found. All queries go through SQLAlchemy ORM with bound parameters; no `text()` with f-strings on user input (the only `text()` uses are `SELECT 1` in `/health` and static `ALTER TABLE` statements in `manage.py migrate` with hardcoded identifiers).
- **XSS:** no reflected/stored XSS found. All templates use Jinja2 auto-escaping; no `|safe`, no `Markup`, no `innerHTML` in app code (only inside the vendored `htmx.min.js`/`alpine.min.js` libraries, which are trusted static assets). Chat content, captions, list items, logistics content, poll labels are all auto-escaped. CSP is present (though weakened by `unsafe-inline`, LOW-6).
- **CSRF:** `CSRFProtect(app)` is global and **every** state-changing form in every template carries `csrf_token` (verified by grep across all 20 templates). HTMX usage is GET-only polling (`hx-get` on chat), which is safe. No `hx-post`/`fetch()` state changes.
- **Path traversal (media):** stored filenames are server-generated `uuid4().hex + ext` (`app/media/__init__.py:159-161`); `send_from_directory` is fed the DB-stored name, not user input. The `code` URL segment cannot contain `/` (Werkzeug routing), and event lookup by code prevents `..` tricks. **No traversal found.** The real issue is the extension/MIME handling (HIGH-5).
- **Command injection:** none. `manage.py` uses `subprocess.run` with argv lists (no shell); `backup.sh` uses fixed paths.
- **Template injection:** no user input reaches `render_template_string` or Jinja evaluation. Alpine.js `x-data`/`x-model` bindings are static literals in templates.
- **MED-3 — Crash on malformed input (verified):** `POST /e/new` with `start_date=abc` → unhandled `ValueError` → **HTTP 500** with full traceback in server logs (`app/events/__init__.py:62-63`). Fix: wrap `strptime` in try/except and return the form with a field error (as `planning._validate_form` already does).
- **MED-8 — Email format never validated:** `email-validator` is in `requirements.txt` but never imported. Verified: `email=not-an-email` creates an event with `creator_email="not-an-email"`. The disposable-domain check (`is_disposable_email`) is the only gate. Fix: validate with `email_validator.validate_email()` on event creation, guest join, and invite-email.

### 3.3 Data Exposure

- **HIGH-3 — Cross-event household reference (verified):** `costs.add_expense` takes `household_id` from the form and stores it **without checking it belongs to the event** (`app/costs/__init__.py:254,298`). Verified: a guest of event A created an expense with event B's household id; event A's costs page then **displays event B's household name** (`exp.paid_by.name`). Settlement math skips the foreign household (so no direct financial corruption), but it is a cross-tenant data leak and an integrity bug. Same pattern in `add_transfer`/`add_payment_request` (`from_household_id`/`to_household_id` unvalidated). Fix: `Household.query.filter_by(id=..., event_id=event.id).first_or_404()` before use.
- **HIGH-4 — Secrets on disk:** `.env` (mode 600 ✓) contains the live Gmail SMTP app password, superadmin password `password`, SECRET_KEY, and VAPID private key. It is **not** in git history (verified: `git log --all -- .env` empty; only `.env.example` was ever committed) — good. However, the SQLite DB file is mode **644** (world-readable) and contains guest emails, display names, and plaintext guest codes. Fix: `chmod 640`/`600` the DB (or run the app as a dedicated user with a private group), and treat the workspace `.env` as a live credential store (rotate the Gmail app password if the workspace is shared).
- **File upload (HIGH-5, verified):** MIME allow-list checks the **client-supplied** `Content-Type` only. Verified: an HTML body uploaded as `evil.html` with `Content-Type: image/jpeg` is accepted and stored as `6b09c1…html`. It is served with `Content-Type: image/jpeg` (so browsers won't render it as HTML — mitigating), but: (a) the `.html` extension on disk is a landmine for any future static-serving change, (b) polyglot files (e.g., valid JPEG header + embedded script) pass, (c) `original_name` is stored and displayed. Fix: validate **magic bytes** (e.g., `python-magic` or Pillow `verify()` for images), force the extension from the verified MIME type, and consider re-encoding uploads.
- **PII in URLs/logs:** event codes and guest ids appear in URLs (by design, unguessable 6/8-char codes — though see CRIT-2 for guest codes). Activity logs store `chat.message` content[:50] and expense amounts — fine. Flask error logs contain full tracebacks (no user data in the verified 500 case, but enable `LOG_LEVEL=INFO` without request bodies in prod).
- **LOW-5:** `/health` (unauthenticated, no rate limit) discloses DB status, disk-usage ratio, and uptime — minor info disclosure; acceptable for monitoring but consider restricting to the internal network.

### 3.4 Business Logic

- **Freemium limits:** `MAX_GUESTS_PER_EVENT` (checked in `join` and `invite`), `MAX_DURATION_DAYS` (checked at creation), `MAX_EVENTS_PER_CREATOR` (checked at creation) — all enforced server-side and **not bypassable** via direct form manipulation (values come from config, not the request). Media quota is enforced per-creator with a per-file 50 MB cap. **Gap:** the quota check-then-consume is not atomic (MED-2 TOCTOU) — concurrent uploads can exceed the quota.
- **Event isolation:** verified — a guest of event A is redirected to `mycode` when accessing event B's planning/lists/voting/chat/costs/media (all child queries are scoped by `event_id`). The only cross-event leak found is HIGH-3 (household reference).
- **Poll voting:** one vote per guest per poll — the vote endpoint deletes previous votes on the same poll before inserting (verified: two votes → 1 stored). The `PollVote` unique constraint is on `(option_id, guest_id)`, which *would* allow multi-option voting, but the endpoint logic prevents it. Creators cannot vote. Closed polls reject votes. **OK.**
- **Activity RSVP:** strictly per-guest via session; creators cannot RSVP; upsert semantics correct. **OK.**
- **MED-7 — Cost manipulation:** any guest can add expenses with **any** amount and **any** positive `exchange_rate` (no sanity bounds, e.g., rate=1000 on a 1 € expense), and household creation accepts `num_adults=999999` server-side (verified — client-side `max=20` is the only guard). This lets a malicious guest skew the settlement. Mitigating: every action is attributed in the activity log and the creator can delete expenses/households. Fix: bound `num_adults`/`num_children` (e.g., ≤ 50), cap `exchange_rate` (e.g., 0.01–1000), cap amounts, and consider creator-approval for expenses above a threshold.
- **Chat:** per-event, session-scoped; no cross-event access (verified). Any guest can delete only their own messages or the creator can delete any (correct).
- **Household/costs access:** all costs routes require a valid guest session for *that* event or creator (verified). Deletions are creator-only. **LOW-2:** any guest can mark any payment request resolved — likely intended (collaborative), but worth confirming.
- **LOW-1:** `lists.unclaim_item` compares `item.assigned_to != actor_name` (display names). Two guests named "Alice" can unclaim each other's items. Fix: store the guest id (or creator flag) on the item, not just the name.

### 3.5 Infrastructure

- **Docker:** runs as non-root `appuser` (uid 1000) ✓; no privileged mode; app port only `expose`d (not published) ✓; Redis not published ✓ (but unauthenticated, LOW-10); named volumes for DB/logs ✓; log rotation configured ✓; healthcheck ✓. `client_max_body_size 50M` matches the app limit ✓.
- **Nginx:** `limit_req` 10 r/s burst 20 per IP ✓ (this is the *only* working per-IP rate limit in the stack — see CRIT-1). **MED-9:** the `/static/` location sets its own `add_header Cache-Control`, which **suppresses inheritance** of the server-level security headers (HSTS, nosniff, XFO, Referrer-Policy, Permissions-Policy) on static responses. Fix: repeat the security headers in the location, or serve statics from the app consistently. HSTS is emitted on plain HTTP (ignored by browsers) — harmless but misleading until TLS exists (HIGH-1).
- **Secrets:** no hardcoded secrets in code (bandit-clean patterns; defaults are `"dev"`/`"change"` which are the problem, see CRIT-4). `.env` never committed (verified). Redis URL has no password (internal only).
- **Dependencies (HIGH-6):** `requirements.txt` uses `>=` lower bounds only — no pinning, no lockfile. Pillow (which parses untrusted uploads) has a history of CVEs (e.g., CVE-2024-28219, fixed in 10.3.0); the installed 12.3.0 is current, but a fresh build could pull anything. Fix: generate a lockfile (`pip-compile`/`uv pip compile`), pin in the Dockerfile, and add `pip-audit` to CI.
- **SQLite (MED-2):** 4 Waitress threads share one SQLite file with **no WAL mode and no busy_timeout** configured anywhere → concurrent writes raise `database is locked` → 500 errors under normal multi-user load (chat + RSVP + lists are all write-heavy). Fix: `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;` via an `event.listens_for(engine, "connect")` hook, and make quota updates atomic (`UPDATE media_quotas SET used_bytes = used_bytes + ? WHERE used_bytes + ? <= max_bytes` with a rowcount check).
- **LOW-3:** `DATABASE_URL=sqlite:///:memory:` is rewritten to a **file** named `:memory:` in the project root (the path-resolution block at `app/__init__.py:29-33` doesn't special-case `:memory:`). The test suite therefore runs against a real file (which is why a stray `:memory:` file keeps appearing in the repo). Fix: skip resolution when the path is `:memory:`.

### 3.6 Web-Specific

- **Open redirects:** none. `login.html` passes `next` into the form action but the view ignores it (always redirects to `events.index`); all other redirects use `url_for`.
- **Clickjacking:** `X-Frame-Options: DENY` on all responses ✓ (app-level `after_request` + nginx).
- **MIME sniffing:** `X-Content-Type-Options: nosniff` ✓ (except on `/static/` due to MED-9).
- **CSP:** present and reasonable (`default-src 'self'`), weakened by `script-src 'unsafe-inline'` (LOW-6) — acceptable for inline Alpine handlers, but consider nonces or moving inline handlers to external JS.
- **Cookie flags:** HttpOnly ✓; Secure ✗ in production (HIGH-1); SameSite unset (LOW-13).
- **Cache poisoning:** no `Cache-Control` on HTML responses → heuristic caching possible; the service worker (MED-4) actively caches authenticated pages. Fix: send `Cache-Control: no-store` on authenticated HTML and media-file responses.
- **Host header attacks:** **MED-1 (verified):** `invite_qr` builds the QR payload from `request.url_root` (i.e., the `Host` header). Sending `Host: evil.example.com` produces a QR encoding `http://evil.example.com/e/<code>/join` — a phishing vector (the invite page shows the *real* URL from `APP_URL`, but the QR points elsewhere). Fix: use `current_app.config["APP_URL"]` instead of `request.url_root`.

### 3.7 DoS

- **Resource exhaustion:** 50 MB/file upload cap (nginx + app) ✓; EXIF extraction reads the whole file into memory (LOW-8, bounded at 50 MB × 4 threads ≈ 200 MB worst case); Pillow parsing of untrusted images (HIGH-6).
- **Algorithmic complexity:** no obvious quadratic endpoints; `_poll_results` does one count query per option (≤10) — fine.
- **Rate-limiting gaps (MED-5):** endpoints with **no** dedicated limit (only the broken global default): `/admin/login` (CRIT-3), `/e/<code>/mycode` (CRIT-2), `/e/<code>/join`, `/e/<code>/invite/email` (email-sending; `RATE_LIMIT_INVITE=20/hour` exists in `.env` but is **never used in code**), chat send, media upload, all costs POSTs, lists create, voting create, logistics create. Only `events.create` (10/h) and `planning.create` (20/h) have explicit limits.
- **SQLite lock contention:** MED-2 — the most likely real-world availability failure under concurrent use.
- **Self-DoS via shared limiter bucket:** CRIT-1.

---

## 4. What's Done Well (keep these)

- CSRF tokens on **every** state-changing form; global `CSRFProtect`.
- Jinja2 auto-escaping everywhere; no `|safe`/`Markup` in app code; sensible CSP.
- Consistent event-scoped authorization (`_resolve_actor` + `event_id` filters) — no classic IDOR in any module.
- Non-root Docker user, unpublished app/redis ports, log rotation, healthcheck.
- `.env` gitignored and never committed; `manage.py init` generates strong secrets and `chmod 600`.
- `backup.sh` uses `sqlite3 .backup` (safe online backup) with retention.
- Activity log (audit trail) on essentially every mutation, with actor attribution.
- 215 passing tests including hardening tests (headers, health, upload size).
- Disposable-email blocking; per-event guest codes; zero-PII guest model (ADR-003).

---

## 5. Remediation Roadmap (ordered by priority)

**P0 — immediate (this week)**
1. **Rotate the superadmin password** (currently `password`) and the Gmail SMTP app password; keep them only in the environment (CRIT-3, HIGH-4).
2. **Fix SECRET_KEY handling:** fail fast on missing/empty/`dev` key; verify the deployed key is the 64-hex one from `.env` (CRIT-4).
3. **Fix rate-limiter keying:** add `ProxyFix` + trusted-proxy config so per-IP limits actually work; re-evaluate the 100/h global default (raise it or move it to nginx) (CRIT-1).
4. **Rate-limit `my_code`, `join`, and `/admin/login`** (e.g., 5–10 per 15 min per IP+event) (CRIT-2, CRIT-3).
5. **Stand up TLS** in front of nginx (or terminate at the VPS) and set `SESSION_COOKIE_SECURE=true` (HIGH-1).

**P1 — short term (2 weeks)**
6. **Guest code hardening:** minimum length 8+, hash storage, remove the "code déjà pris" enumeration oracle (CRIT-2).
7. **Validate `household_id`/transfer endpoints against the event** (HIGH-3); bound household headcounts and exchange rates (MED-7).
8. **Media upload:** magic-byte validation, extension derived from verified MIME, Pillow `verify()` (HIGH-5).
9. **SQLite:** enable WAL + busy_timeout; make quota updates atomic (MED-2).
10. **Remove debug mode from `manage.py run`** (or force `127.0.0.1`); fix `db-shell` path (HIGH-2, LOW-4).
11. **Fix `/e/new` date parsing** (try/except → form error) (MED-3); validate email formats with `email-validator` (MED-8).
12. **Use `APP_URL` in `invite_qr`** instead of `request.url_root` (MED-1).

**P2 — medium term (1 month)**
13. Pin dependencies with a lockfile + `pip-audit` in CI (HIGH-6).
14. Add the missing per-endpoint rate limits (chat, upload, costs, invite-email — wire up `RATE_LIMIT_INVITE`) (MED-5).
15. Service worker: stop caching authenticated pages (or add `Cache-Control: no-store` on HTML/media) (MED-4); nginx `/static/` header inheritance fix (MED-9).
16. Verification token: constant-time compare, single-use, expiry, event-bound (MED-6).
17. `load_dotenv(override=False)` or explicit precedence (MED-10); special-case `:memory:` DB (LOW-3).
18. Store guest id on list items for claim/unclaim (LOW-1); confirm payment-request resolve policy (LOW-2).
19. Explicit `SESSION_COOKIE_SAMESITE=Lax`; consider shortening remember-cookie duration (LOW-13).

**P3 — strategic**
20. Replace the single superadmin with per-creator accounts (hashed passwords) so platform compromise ≠ total data compromise (CRIT-3 root cause).
21. Move to server-generated, time-limited join tokens instead of permanent user-chosen guest codes (CRIT-2 root cause).
22. Evaluate Postgres if multi-writer load grows (ADR-001 already anticipates this).

---

*Report generated by static review + dynamic verification. All "verified" findings were reproduced against a live instance of the current code on 2026-10-04. No fixes were applied.*
