# Security Policy

Hermes exposes a **complete** Home Assistant installation to an MCP client
(Claude) over the internet, behind a reverse proxy (Tailscale Funnel, Cloudflare
Tunnel or similar). It is a sensitive component: security is a first-order
requirement here, not an extra.

## Supported versions

Security support is provided for the **latest published version** only. There are
no maintained release branches: fixes ship in a new version, and the upgrade path
is the Home Assistant add-on store.

| Version | Supported |
|---|---|
| Latest published release | ✅ |
| Anything older | ❌ |

The version history is in [hermes/CHANGELOG.md](hermes/CHANGELOG.md).

## Reporting a vulnerability

**Do not open a public issue, pull request or discussion.**

Use GitHub's private channel:

**[Security → Report a vulnerability](../../security/advisories/new)**

It is a private form between the reporter and the maintainer. Nothing is indexed,
and GitHub coordinates publishing the advisory once the flaw is fixed. If you
cannot use GitHub advisories, write to `nadeon@gmail.com` instead, and say up
front that the message is a security report.

Please include, if you can:

- A description of the flaw and its impact.
- Reproduction steps, or a proof of concept.
- The Hermes version, your `network_mode`, and how Hermes is exposed.
- The `X-Request-ID` from the failing response and the surrounding log lines.

> [!CAUTION]
> Redact your own secrets before sending anything. Logs redact known values, but
> not values Hermes has never seen.

### What to expect

This is a single-maintainer project, so these are honest targets rather than a
contractual SLA:

| Stage | Target |
|---|---|
| Acknowledgement of your report | 5 business days |
| Initial assessment, with a severity call | 10 business days |
| Fix released for a confirmed high-severity flaw | 30 days |
| Coordinated public disclosure | 90 days after the report, or on release of the fix, whichever comes first |

If a deadline is going to slip, you will be told before it slips rather than
after. If you disagree with an assessment — including a decision that something
is not a vulnerability — say so; that conversation stays in the private thread.

### Safe harbour

Research conducted in good faith under this policy is welcome, and no legal
action will be pursued over it, provided you:

- Test only against **your own installation**. Never against someone else's.
- Do not access, modify or destroy data that is not yours.
- Do not degrade the service for others, and do not run automated scanning
  against third-party deployments.
- Give a reasonable window to fix before disclosing publicly.

Credit is given to whoever wants it, in the advisory and in the changelog.

### Out of scope

These are known and documented properties of the design, not vulnerabilities. A
report about one of them will be closed with a pointer to this section:

- Anything from the **Assumptions and known limitations** list below.
- Findings that require the attacker to already know `auth_password`, or to
  already have administrator access to Home Assistant.
- Missing security headers on endpoints that serve no content.
- Reports produced solely by an automated scanner, with no demonstrated impact.
- Denial of service achieved by exhausting the documented, configurable resource
  limits (`max_concurrent_requests` and friends) from an authenticated session.
- Vulnerabilities in Home Assistant itself, in the Supervisor, or in the proxy
  you put in front. Report those upstream.

## Security model

- **TLS** is always terminated by the proxy in front; Hermes speaks plain HTTP on
  `mcp_bind:8765` (`127.0.0.1` by default) and never handles certificates. The
  default bind makes it unreachable from outside the host: the only way in is the
  proxy. **Do not set it to `0.0.0.0`**: that would publish Hermes unencrypted
  across your whole local network, bypassing TLS.
- **Authentication**: OAuth 2.1 with mandatory PKCE (S256), Dynamic Client
  Registration, high-entropy opaque tokens stored only as a SHA-256 hash,
  single-use auth codes, and revocation (RFC 7009). Refresh tokens rotate, with
  reuse detection.
- **The add-on password (`auth_password`) is the only secret protecting the whole
  system.** Hermes enforces a minimum of 12 characters at startup and rejects
  guessable passwords — repetitive ones, keyboard and alphabet runs, entries from
  the most-used lists, and passwords containing project or hostname words. The
  rules follow NIST SP 800-63B §5.1.1.2. On top of that, failed logins are
  throttled with a global exponential backoff, which cannot be evaded by rotating
  source IP.
- **Defence in depth** on actions:
  - `confirmation_token` for every destructive operation (writing or deleting
    files, restarting, uninstalling add-ons, restoring backups, dangerous
    services…). The token is bound to the tool **and its arguments**, expires,
    and is single-use.
  - Service denylist + recursive `service_data` sanitisation + automatic
    classification of dangerous scripts and automations.
  - `/config` filesystem: anti-traversal (resolve + boundary check), secret
    blacklist, *default-deny* allowlist for `.storage/`, *managed paths* that are
    never writable, automatic backup before every write.
  - Identifier validation (slug, `entry_id`, …) before interpolating them into
    URLs, plus a central anti path-injection guard in the HA client.
- **Secret redaction** in all logs, both Hermes's own and those of other add-ons.
- **Security headers** (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, CSP) and a body size limit (`chunked` included).
- **Resource limits**: caps on concurrency, request body, response size and
  WebSocket message size, all configurable and all enforced.

## Assumptions and known limitations

These are **inherent to the design**. They are documented so an operator can take
them into account:

1. **Trust in the MCP client.** The `confirmation_token` is handed to the client
   (Claude), which can pass it along. It is not an enforced human approval: the
   real human-in-the-loop is the *preview* the MCP client shows before
   confirming. Treat access to Hermes as administrator access to Home Assistant.
2. **Supervisor token with admin role.** The add-on uses `SUPERVISOR_TOKEN` to
   operate; anyone who gets past authentication has administrator capability over
   Home Assistant. This is why `auth_password` strength is critical.
3. **The source IP limits, it never authorizes.** Under
   `network_mode: tailscale`, the client's real IP does reach Hermes: the proxy
   delivers from the loopback and the server trusts the `X-Forwarded-For` that
   proxy rewrites. Under `network_mode: reverse_proxy` with `mcp_bind` on the
   bridge network, the header is ignored and the per-IP limit becomes a global
   ceiling. In neither case does an IP grant access: it only feeds rate limiting
   and logs. The specific anti-brute-force defence is the login throttle, which
   is global on purpose.
4. **Container runs as root.** Like most HAOS add-ons, the container needs access
   to `/config` and `/data` and runs as root inside the space the Supervisor
   isolates for it.
5. **Single owner.** The authorization model assumes one owner. There are no
   roles, no per-tool scopes, and no separation between concurrent clients.

## Deployment recommendations

- Use an `auth_password` produced by a password manager (24 characters or more
  recommended, well above the enforced minimum).
- Prefer a tunnel. Tailscale Funnel and Cloudflare Tunnel open no router port; a
  classic reverse proxy requires opening 443 and leaves your installation
  directly exposed. All else being equal, take the tunnel.
- Keep the add-on that publishes the hostname (Tailscale, Cloudflared…) updated,
  and periodically review what is exposed.
- Narrow what Claude can do without asking: `call_service_denylist_extra`,
  `call_service_restricted_entities` and `fire_event_allowlist` exist for that.
  `fire_event_allowlist` is empty by default, which disables event firing
  entirely until you name the events you want.
- Watch the logs (`ha apps logs local_hermes -f`, or the add-on's Log tab) for
  repeated `oauth_login_locked`, `oauth_login_throttled` or `auth_rejected`
  events.
- If you stop using Hermes, uninstall the add-on rather than just stopping it:
  uninstalling clears `/data`, and with it the stored OAuth keys and tokens.
