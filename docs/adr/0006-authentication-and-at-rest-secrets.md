# 6. Authentication, first-run onboarding, and at-rest encryption of secrets only

Date: 2026-06-19
Status: Accepted

## Context

AutoLedger shipped with **no authentication** — the only protection was the
advice to "keep it behind a VPN" ([HANDOVER](../../HANDOVER.md) Known
Limitations). That violates the standing rule that every app gets a
user+password authority with a forced first-run onboarding step. The app is also
a public GitHub repo (`quiggles/autoledger`), so the change had to add real
access control without ever committing a secret.

A second, related question was raised: should the data volume be **encrypted at
rest**, and if so, with a key derived from the login password?

## Decision

**Authentication** — a single admin account (username + Argon2id hash via
`argon2-cffi`), stored in `data/auth.json` (gitignored). A `before_request`
guard protects every `/api/*` route except a small public allow-list
(`/api/health`, `/api/auth/status|login|onboard`). Until an account exists the
API returns `403 onboarding_required` and the SPA forces an onboarding screen.
Sessions use Flask's signed cookie, keyed by a persistent secret in
`data/session.key` so logins survive restarts. No secret is ever returned by a
GET — `/api/auth/status` returns only booleans and the username.

**At-rest encryption — secrets only, not the cost data.** Cost/vehicle/settings
JSON stays **plaintext**; only operational secrets (SMTP password, Home
Assistant token) are encrypted, via Fernet with an app-managed key in
`data/secret.key` (`routes/crypto.py`). The key is **not** derived from the login
password.

## Alternatives considered

- **Full at-rest encryption from the login password.** Strongest on paper, but it
  destroys the ADR 0001 value — "open the JSON in any editor, diff it, back it up
  by copying the folder" — forces the derived key to live in session memory, and
  makes a forgotten password equal *total data loss* (no key escrow). Excessive
  for a single-user home-lab tool whose threat model is a LAN/VPN, and whose
  *public* exposure is code, not data (data is gitignored).
- **No encryption at all.** Simplest, but leaves the SMTP password / HA token in
  plaintext on disk, violating the "secrets encrypted at rest" standing rule.
- **Multi-user accounts / roles.** Over-engineering for one person.

The chosen middle path — gate + encrypt secrets only — satisfies the secrets
rule while preserving the plain-JSON philosophy and avoiding password-reset data
loss.

## Consequences

- **Positive:** real access control with forced onboarding; secrets never sit in
  plaintext and never reach the browser; cost data stays inspectable/diffable;
  resetting the password (future feature) cannot destroy data because the
  encryption key is independent of it.
- **Negative:** a new `data/secret.key` and `data/session.key` must travel with
  the data volume in backups — losing `secret.key` means stored secrets must be
  re-entered (they are re-enterable in the UI, so this is recoverable). There is
  deliberately **no password recovery**; the README says to store the admin
  credential safely.
- **Migration:** existing deployments hit the onboarding screen on first launch
  after upgrade and create the admin account then. No data migration needed.
