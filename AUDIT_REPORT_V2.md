# Holishared — Security Re-Audit (V2)

**Date:** 2026-10-04
**Scope:** Full re-audit of `app/` (all blueprints, models, templates, static), `nginx/saas.conf`, `Dockerfile`, `docker-compose.yml`, `manage.py`, `requirements.txt`, `systemd/saas.service`, CI, `.env`, `tests/`.
**Baseline:** `AUDIT_REPORT.md` (33 findings: 4 Critical, 6 High, 10 Medium, 13 Low). All P0–P2 items claimed fixed in commit `78b01d5`.
**Method:** Line-by-line review of every changed file + dynamic verification of each fix against a live test instance (rate-limit 429s, magic-byte rejection, cross-tenant rejection, token single-use, empty-password login, ProxyFix keying all reproduced).
**Regression gates:** ✅ 215/215 tests pass · ✅ `ruff check app/ manage.py` clean · ✅ app starts · ✅ `SECRET_KEY` fail-fast verified (empty and `"dev"` both raise `RuntimeError`).

---

## 1. Executive Summary

| Metric | Count |
|---|---|
| Original findings (V1) | 33 |
| **Confirmed fixed** (code-level, verified) | **18** |
| **Partially fixed** (code done, residual gap) | **5** |
| **Not fixed** (deferred / operational / P3) | **10** |
| **New findings introduced or missed** | **13** (2 High, 2 Medium, 9 Low, 1 Info) |

**Headline:** The application-layer fixes are largely correct and well done — ProxyFix, guest-code hardening, login rate limiting, SECRET_KEY fail-fast, cross-tenant household validation, magic-byte upload checks, and the verification-token lifecycle all work as intended (each dynamically verified). However:

1. **The P0 operational items were not done.** `.env` still contains `SUPERADMIN_PASSWORD=password` and the live Gmail app password, and the SQLite DB file is still mode 644. The code now *fails fast* on a bad SECRET_KEY, but the deployed credentials were never rotated.
2. **Two regressions were introduced by the fixes:**
   - The global `100 per hour` default limit, now correctly keyed per real IP, **locks out any user who leaves the chat page open for ~8.5 minutes** (chat polls every 5 s = 12 req/min → 429 on the 101st request, verified). The V1 audit explicitly warned to re-evaluate this default; it was kept.
   - **HEIC uploads are now broken**: `image/heic` is in the MIME allow-list but has no magic-byte signature, so `_validate_magic_bytes()` always rejects it — iPhone users (the default HEIC camera format) cannot upload photos at all (verified).
3. **A new auth failure mode:** with `SUPERADMIN_PASSWORD` unset in Docker, the container receives an empty string and **superadmin login succeeds with an empty password** (verified). Unlike SECRET_KEY, there is no fail-fast.
4. **Zero test coverage for the new security features** — no test exercises any rate limit, the magic-byte check, the household scoping, the SECRET_KEY fail-fast, or ProxyFix keying. The V1 audit explicitly recommended a limiter-keying test.

**Overall posture:** Up from "critical weaknesses in auth design + broken rate limiting" to "sound app-layer security with deployment/operational gaps and two availability regressions." The remaining risk is concentrated in: unrotated live credentials, no TLS in the stack, unpinned dependencies, and the chat-polling/limit interaction.

---

## 2. Confirmed Fixes (18) — with verification evidence

| ID | Fix | Evidence |
|---|---|---|
| CRIT-1 | `ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)` in `app/__init__.py:91`; limiter now keys on real client IP | Verified: 11th `mycode` POST from one `X-Forwarded-For` IP → 429; same request from a second IP → 200. ProxyFix takes the rightmost XFF entry, which nginx appends via `$proxy_add_x_forwarded_for`, so client-supplied XFF cannot spoof the key *while behind nginx*. ⚠ See NEW-1/NEW-3 for residual issues. |
| CRIT-2 | Guest code min 8 / max 16, `[a-z0-9]+`, `@limiter.limit("10 per 15 minutes")` on `join` + `mycode`, generic "Code invalide ou déjà utilisé" (oracle removed) | Verified: 4-char code rejected ("8 à 16 caractères"); duplicate code returns generic message, no "déjà pris" oracle; 11th wrong-code attempt → 429. Residual: codes still stored **plaintext** (V1 suggested hashing) — mitigated by length+limits, tracked as residual. |
| CRIT-4 | `SECRET_KEY` fail-fast: empty or `"dev"` → `RuntimeError` at startup | Verified: `SECRET_KEY=""` and `SECRET_KEY=dev` both raise; app starts with a 64-hex key. Docker empty-string case now fails the container instead of allowing cookie forgery. |
| HIGH-2 | `manage.py run` → `flask run -h 127.0.0.1`, no `--debug` | Verified in code (`manage.py:293-298`). Residual: help text still says "Flask debug" (NEW-8). |
| HIGH-3 | `_household_in_event()` check on `add_expense`, `add_transfer`, `add_payment_request` | Verified: expense with event B's household id on event A → "Foyer payeur invalide", 0 rows created. |
| HIGH-5 | Magic-byte validation (`_validate_magic_bytes`) + extension forced from verified MIME (`_MIME_EXT`) | Verified: `<html>` body with `Content-Type: image/jpeg` → rejected ("contenu ne correspond pas au format déclaré"); valid JPEG accepted. Residual: HEIC regression (NEW-2). |
| MED-1 | `invite_qr` uses `current_app.config["APP_URL"]` instead of `request.url_root` | Verified: `Host: evil.example.com` header no longer influences the QR payload (APP_URL-based). |
| MED-3 | `strptime` wrapped in try/except on `/e/new` → form error | Verified: `start_date=abc` → 200 with "Format de date invalide (AAAA-MM-JJ)", no 500. |
| MED-4 | Service worker: pages are network-only (`event.respondWith(fetch(request))`), only static assets cached | Verified in `service-worker.js:44-45`. |
| MED-6 | Verify token: `hmac.compare_digest`, single-use (`token=None` after use), 24 h expiry | Verified: first use → "Compte validé !"; second use with same token → "Lien de validation invalide ou expiré". Token is `secrets.token_hex(32)` (256 bits). |
| MED-7 | `num_adults` 1–50, `num_children` 0–50, weights 0–10, `exchange_rate` 0–10000 | Verified: `num_adults=999999` → "entre 1 et 50", 0 households created; `exchange_rate=100000` → "Taux de change invalide", 0 expenses created. Residual: expense **amount** still unbounded (V1 suggested capping). |
| MED-10 | `load_dotenv(BASE_DIR / ".env", override=False)` | Verified in `app/__init__.py:14`; real environment now wins over `.env`. |
| LOW-1 | `ListItem.assigned_to_id` stored on claim; unclaim compares ids, not names | Verified in `lists/__init__.py:299-325` + `models.py:199`. |
| LOW-3 | `sqlite:///:memory:` special-cased (no path rewrite) | Verified in `app/__init__.py:37-38`; test suite runs against true in-memory DB. |
| LOW-4 | `db-shell` opens `instance/holishared.db` | Verified in `manage.py:369`. |
| LOW-7 | `invite.html` uses `config.MAX_GUESTS_PER_EVENT` | Verified in template (was `event.max_guests`, a non-existent property). |
| LOW-9 | `get_limits()` uses `config.get("MEDIA_QUOTA_FREE_MB", 500)` | Verified in `freemium.py:40` — no more KeyError. |
| LOW-13 | `SESSION_COOKIE_SAMESITE = "Lax"` explicit | Verified in `app/__init__.py:30`. |

## 3. Partially Fixed (5)

| ID | What's done | What's missing |
|---|---|---|
| CRIT-3 | `@limiter.limit("5 per 15 minutes")` on `/admin/login` (verified: 6th attempt → 429) | **Password never rotated** — `.env` still has `SUPERADMIN_PASSWORD=password` (P0 item 1). Limit is per-IP only, not per-IP+email as recommended; GETs also consume the 5-attempt budget. See NEW-4/NEW-5. |
| MED-2 | WAL + `busy_timeout=5000` via `connect` event listener (verified in `app/__init__.py:100-110`) | Quota update still read-modify-write (`consume_media_quota`) — the TOCTOU race from V1 remains: concurrent uploads can exceed the quota. |
| MED-5 | Limits added: chat send (30/min), media upload (10/h), expenses/transfers/payment-requests (20/h), list items (20/h), poll create (10/h), logistics create (20/h), invite email (20/h) | Still unlimited: list **create**, household create, logistics **edit**, planning edit/delete/RSVP, poll **vote**, chat delete, payment-request resolve, invite resend. `RATE_LIMIT_INVITE` env var still unused (limit is hardcoded). |
| MED-8 | `email_validator.validate_email()` on event creation (verified: `not-an-email` → "Format d'email invalide") and guest join | `invite_email` (creator → guest invite) only checks disposable domains, **not format** → invalid address reaches `smtplib` → unhandled exception → HTTP 500 (NEW-7). |
| MED-9 | `/static/` location repeats `nosniff`, `X-Frame-Options`, `Referrer-Policy` | **HSTS and Permissions-Policy are still dropped** on static responses (only 3 of 5 server-level headers repeated). |

## 4. Not Fixed (10) — deferred / operational / P3

| ID | Status | Note |
|---|---|---|
| HIGH-1 | **Not fixed** | Nginx still `listen 80` only; `.env` has `SESSION_COOKIE_SECURE=false`; docker-compose default is `false`. App code now *defaults* to `true` when unset, but both deployment configs explicitly override to `false`. TLS termination (VPS-level or in-stack) + `SESSION_COOKIE_SECURE=true` still outstanding. HSTS is still emitted on plain HTTP (no-op, misleading). |
| HIGH-4 | **Not fixed** | `instance/holishared.db` still mode **644** (world-readable; contains guest emails, names, plaintext codes). `.env` (mode 600 ✓) still holds the live Gmail app password and `password` superadmin password. |
| HIGH-6 | **Not fixed** | `requirements.txt` still `>=` lower bounds only; no lockfile; no `pip-audit` in CI (bandit runs with `--exit-zero`, i.e. non-blocking). Pillow parses untrusted uploads — supply-chain exposure unchanged. |
| LOW-2 | Not fixed | Any guest can still resolve any payment request (V1: "confirm policy" — still unconfirmed). |
| LOW-5 | Not fixed | `/health` still discloses DB status, disk ratio, uptime unauthenticated. |
| LOW-6 | Not fixed | CSP still `script-src 'unsafe-inline'` (accepted: required for Alpine inline handlers). |
| LOW-8 | Not fixed | EXIF extraction still reads the whole upload (≤50 MB) into memory per request. |
| LOW-10 | Not fixed | Redis still unauthenticated (internal network only — acceptable, hardening note). |
| LOW-11 | Not fixed | Chat still polls every 5 s — now **interacts badly with the per-IP 100/h limit** (see NEW-1). |
| LOW-12 | Not fixed | Guest code still displayed in plaintext on dashboard (design note). |

P3 strategic items (per-creator accounts, server-generated join tokens, Postgres) remain intentionally deferred — consistent with V1.

---

## 5. New Findings (13)

| ID | Sev | Title | Location | Detail |
|---|---|---|---|---|
| NEW-1 | **High** | **Availability regression: per-IP 100/h global limit + 5 s chat polling → user 429 after ~8.5 min of chat** | `app/extensions.py:24`, `app/templates/chat/index.html:54` | The CRIT-1 fix made the global `default_limits=["100 per hour"]` bucket per-real-IP — but the V1 audit explicitly said to re-evaluate that default. Chat polls every 5 s (12 req/min = 720 req/h). **Verified: the 101st request from one IP returns 429**, and the 429 applies to *all* endpoints for that IP (Flask-Limiter default limits stack with per-endpoint limits). Any user who leaves the chat page open for ~8.5 minutes is locked out of the entire app for the rest of the hour. Fix: raise/remove the app-level default (nginx `limit_req` already provides the coarse per-IP guard), or exempt the chat-poll GET, or slow the poll to ≥2 min. |
| NEW-2 | **Medium** | **Functional regression: HEIC uploads always rejected** | `app/media/__init__.py:31,46-60` | `image/heic` is in `ALLOWED_MIME` but `_MAGIC_BYTES`/`_validate_magic_bytes` has no HEIC signature → returns `False` for every HEIC file. **Verified:** a valid `ftypmif1` HEIC body with `Content-Type: image/heic` → "Fichier invalide (contenu ne correspond pas au format déclaré)". iPhone users (default camera format) can no longer upload photos. Fix: add the HEIF/HEIC signature (`ftyp` box with `mif1`/`heic`/`heix` brand at offset 8) or drop `image/heic` from the allow-list. |
| NEW-3 | **Medium** | **ProxyFix without `trusted_proxies` → rate-limit bypass if the app is directly reachable** | `app/__init__.py:91`, `manage.py:301-321` | ProxyFix unconditionally trusts `X-Forwarded-For`. Behind nginx this is safe (nginx appends the true client IP rightmost, and ProxyFix takes the rightmost entry — verified). But `manage.py start` binds Waitress to `APP_HOST=0.0.0.0` (the generated `.env` value), and nothing prevents publishing the Docker app port. If the app is reachable directly, an attacker sends `X-Forwarded-For: <rotated-ip>` and **bypasses every rate limit** (login, mycode, join, upload). Fix: `ProxyFix(..., trusted_proxies="172.16.0.0/12, 127.0.0.1/8")` (or the nginx subnet), and/or make `manage.py start` default to `127.0.0.1`. |
| NEW-4 | **High** | **Empty `SUPERADMIN_PASSWORD` → superadmin login with empty password** | `app/__init__.py:52`, `app/auth/__init__.py:43-44`, `docker-compose.yml:48` | `os.environ.get("SUPERADMIN_PASSWORD", "change")` returns `""` when the variable is set-but-empty (exactly what `SUPERADMIN_PASSWORD=${SUPERADMIN_PASSWORD}` produces when the host var is unset). The login check `password == ""` then matches an empty password field. **Verified: with `SUPERADMIN_PASSWORD=""`, POST `/admin/login` with `password=""` → 302 to `/e/` (logged in).** The CRIT-4 fix added fail-fast for SECRET_KEY but not for the superadmin password. Fix: fail fast on empty/`change` password, or reject empty passwords in the login view. |
| NEW-5 | **High** | **P0 operational items not performed: live weak credentials on disk** | `.env:22,48`, `instance/holishared.db` | `SUPERADMIN_PASSWORD=password` and the live Gmail SMTP app password are still in the workspace `.env`; the DB file is still 644. V1 P0 item 1 ("rotate now") was not executed. Combined with NEW-4 and the per-IP-only login limit, the single account that owns every event remains the weakest link. |
| NEW-6 | Low | Nginx `/static/` and `/health` locations don't set `X-Forwarded-For` → all static requests share one proxy-IP limiter bucket | `nginx/saas.conf:50-67` | With ProxyFix, these requests key on the nginx container IP. The shared 100/h bucket means ~16 first-time page loads (6 static assets each) before static files start 429-ing for everyone (mitigated by the service worker cache on repeat visits). Add `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` to both locations. |
| NEW-7 | Low | `invite_email` doesn't validate email format → unhandled SMTP exception → HTTP 500 | `app/events/__init__.py:210-230` | MED-8 was fixed for event creation and join but not here. `email="not-an-email"` passes the disposable check, reaches `smtplib.send_message`, and the resulting exception is unhandled (500 + traceback in logs). Add `_valid_email()` to this branch. |
| NEW-8 | Low | Stale strings contradict the new behavior | `app/events/__init__.py:354-355`, `manage.py:488` | Guest invite email still says "crée ton code personnel (**4 à 8** lettres/chiffres…)" — codes are now 8–16; guests following the email instructions get a validation error. `manage.py` help still advertises "Run dev server (Flask debug)" — debug was removed. |
| NEW-9 | Low | **Zero test coverage for the new security features** | `tests/` | No test asserts: any 429 rate limit, limiter keying via `X-Forwarded-For` (explicitly recommended in V1), magic-byte rejection, HEIC handling, cross-event household rejection, SECRET_KEY fail-fast, verify-token single-use/expiry, SameSite flag. All 215 tests pass, but none of the P0–P2 fixes is regression-protected — a future refactor can silently re-open any of them. |
| NEW-10 | Low | Race conditions in the new/adjacent validation logic | `app/events/__init__.py:274-298`, `app/freemium.py:10-13,75-80` | (a) Two concurrent `join` POSTs with the same code both pass the `first()` check; the `uq_guest_event_code` constraint then raises `IntegrityError` → unhandled 500 (no duplicate data — safe, but ugly). (b) `can_add_guest` check-then-insert is non-atomic → concurrent joins can exceed `MAX_GUESTS_PER_EVENT` by 1. (c) Media quota TOCTOU (carried over from MED-2). |
| NEW-11 | Low | Expense `currency` never validated against `CURRENCIES` | `app/costs/__init__.py:265` | Any string is accepted and stored (e.g. `currency="XXXX"`); the UI dropdown is the only guard. Validate against the `CURRENCIES` list. |
| NEW-12 | Info | HSTS still emitted on plain-HTTP responses | `app/__init__.py:215`, `nginx/saas.conf:18` | Harmless (browsers ignore HSTS on HTTP) but misleading until HIGH-1 is resolved; consider gating on `request.is_secure` or the deployment scheme. |
| NEW-13 | Low | Rate limits keyed per-IP only (not per-IP+event / per-IP+email) | `app/extensions.py:23` | V1 recommended "per IP **and** per event code" for guest endpoints and "per IP + per email" for login. Per-IP alone means an attacker with a rotating IP pool gets 5 login attempts (or 10 code guesses) per IP per 15 min. Acceptable given the 8-char codes and the (still weak) superadmin password, but worth tightening once NEW-5 is resolved. Also note: GETs consume the login/mycode budgets (a user refreshing the login page 5× in 15 min is locked out). |

---

## 6. What's Done Well (carried over + new)

- All V1 positives still hold: CSRF everywhere, Jinja2 auto-escaping, event-scoped authorization, non-root Docker user, `.env` gitignored, activity-log audit trail, disposable-email blocking.
- **New:** the fix commit is disciplined — each P0–P2 code item maps to a real, verifiable change; the fail-fast on SECRET_KEY is exactly the pattern V1 asked for; the verification-token lifecycle (constant-time + single-use + expiry) is textbook; the cross-tenant household helper is applied consistently to all three cost endpoints; tests were updated for the new code-length rule (215/215 green).
- `manage.py init` now generates strong secrets, chmod 600, and warns on insecure `.env` perms — good onboarding hygiene.

## 7. Recommendations (ordered)

**Immediate (this week)**
1. **Rotate the superadmin password and the Gmail app password; `chmod 600` the DB** (NEW-5, HIGH-4, CRIT-3). Use `manage.py reset-admin`.
2. **Fix the chat-polling/limit interaction** (NEW-1): remove or raise the app-level `default_limits` (nginx `limit_req` already guards per-IP), or exempt the chat poll, or raise the poll interval to ≥2 min.
3. **Fail fast on empty `SUPERADMIN_PASSWORD`** (NEW-4) — mirror the SECRET_KEY check; reject empty passwords in the login view.
4. **Fix or drop HEIC** (NEW-2): add the `ftyp`+brand magic check or remove `image/heic` from `ALLOWED_MIME`.

**Short term (2 weeks)**
5. Stand up TLS (VPS or in-stack) and set `SESSION_COOKIE_SECURE=true` (HIGH-1); gate HSTS on the real scheme (NEW-12).
6. Pin dependencies (lockfile) + `pip-audit` in CI; make bandit blocking (HIGH-6).
7. Constrain ProxyFix with `trusted_proxies` and make `manage.py start` default to `127.0.0.1` (NEW-3); add `X-Forwarded-For` to the nginx `/static/` and `/health` locations (NEW-6).
8. Add the missing tests for the new security features (NEW-9) — at minimum: 429 on login/mycode/join, XFF keying, magic-byte reject/accept, cross-event household reject, SECRET_KEY fail-fast, token single-use.
9. Finish MED-8 on `invite_email` (NEW-7); repeat HSTS + Permissions-Policy in the nginx `/static/` location (MED-9); validate expense currency (NEW-11); fix the stale "4 à 8" email text and "Flask debug" help string (NEW-8).

**Medium term (1 month)**
10. Atomic quota/guest-count updates (MED-2/NEW-10); handle the duplicate-code `IntegrityError` gracefully.
11. Fill the remaining rate-limit gaps (household create, list create, logistics edit, planning edit/RSVP, poll vote, chat delete, invite resend) and wire `RATE_LIMIT_INVITE` from the environment (MED-5/NEW-13).
12. Consider hashing guest codes at rest (CRIT-2 residual) and per-IP+event / per-IP+email limiter keys (NEW-13).
13. P3 strategic items remain: per-creator accounts, server-generated time-limited join tokens, Postgres evaluation.

---

*Report generated by full static re-review + dynamic verification (live test instance, 2026-10-04). Every "verified" claim above was reproduced against commit `78b01d5`.*
