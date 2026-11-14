# Security

AURA is a hackathon prototype that uses **fictional crew and simulated data**. The controls below are
built in. Known limits follow.

## Isolation between missions
- Every mission is a separate tenant. All crew, sensor, limit, reading, chat and log queries are
  scoped by mission, and every record ID in an admin request is checked against the mission, so
  guessing another mission's IDs doesn't work.
- A host's session token is bound to one mission and can't administer any other mission.

## Access control
- **Mission admin:** unlocked with the mission's own password (at least 8 characters).
- **Platform team:** individual accounts with passwords of at least 10 characters.
- All passwords are hashed with PBKDF2-SHA256 (200,000 rounds, per-user salt). Sessions use
  HMAC-signed tokens that expire after 12 hours.
- **Viewing:** anyone with a mission's join code can watch it and use its assistant. That's needed for
  judging, and the demo data is fictional.
- Hosting is limited to 3 new missions per IP per hour (300 in total). Idle missions are deleted after 7 days.
- **Sensors:** each sensor has its own API key, compared in constant time and replaceable at any time.
  A disabled sensor's data is rejected.

## Privacy
- Assistant conversations are private to the browser that started them (anonymous per-browser ID).
  Other visitors can't read or clear them.

## Abuse protection
- Assistant: 10 questions per minute per visitor and 400 per hour site-wide, which protects the AI quota.
- Login (mission and team): a 5-minute lockout after 5 failed attempts from one IP.
  Client IPs come from the CDN-set header (CF-Connecting-IP), not from forgeable X-Forwarded-For.
- Sensor ingest: 240 readings per minute per sensor, at most 500 per batch. CSV imports are capped at 2 MB.

## Audit trail
- Every sign-in, failed sign-in and admin change is logged with time, user and IP (Admin → Activity).

## Web hardening
- HTTPS only (HSTS). Content-Security-Policy (scripts from our own origin only), X-Frame-Options DENY,
  nosniff, no-referrer, no caching of API responses.
- Cross-origin API access is off by default (`ALLOWED_ORIGINS` enables specific sites).
- No SQL injection: every query is parameterised through SQLAlchemy. No script injection (XSS): React
  escapes all output, and assistant replies are rendered as text, never as HTML.

## Secrets and data
- Secrets (database URL, AI key, signing key) live only in hosting environment variables, never in the
  repository. The AI key is sent in a request header, so it never appears in URLs or logs.
- The database uses a dedicated least-privilege account in a private schema that the public Supabase API
  doesn't expose.

## Known limits (prototype)
- Rate limits are kept in memory and reset when the server restarts.
- No multi-factor authentication or password-reset email.
- The assistant sends telemetry to Google Gemini. A real mission would need an on-board or approved model.
- Not a medical device and not validated for clinical use.

To report a security issue, open a GitHub issue marked **[security]** and don't include exploit details.
