# Security

AURA is a hackathon prototype that uses **fictional crew and simulated data**. The controls below are
built in. Known limits follow.

## Access control
- **Admin panel:** individual accounts (admin or viewer role) with passwords of at least 10 characters,
  hashed with PBKDF2-SHA256 (200,000 rounds, per-user salt). Sessions use HMAC-signed tokens that
  expire after 12 hours. Admins can't delete themselves or the last admin.
- **Dashboard and assistant:** *Public* mode (for the demo and judging) or *Private* mode (team accounts
  only), switched under Admin → Team & access.
- **Sensors:** each sensor has its own API key, compared in constant time and replaceable at any time.
  A disabled sensor's data is rejected.

## Privacy
- Assistant conversations are private to the browser that started them (anonymous per-browser ID).
  Other visitors can't read or clear them.

## Abuse protection
- Assistant: 10 questions per minute per visitor and 400 per hour site-wide, which protects the AI quota.
- Login: a 5-minute lockout after 5 failed attempts from one IP (20 per username).
  Client IPs come only from the hosting proxy's own entry, so they can't be spoofed with headers.
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
