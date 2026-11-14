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
  Registration and Client ID Metadata Documents (CIMD), the `iss` parameter on
  every redirect to the client (RFC 9207), high-entropy opaque tokens stored only as a SHA-256 hash,
  single-use auth codes, and revocation (RFC 7009). Refresh tokens rotate, with
  reuse detection. Changing `auth_password` closes every open session on the
  next start; to notice the change, Hermes keeps a salted scrypt fingerprint of
  the password in `/data`, never the password itself.
- **The add-on password (`auth_password`) is the only secret protecting the whole
  system.** Hermes enforces a minimum of 12 characters at startup and rejects
  guessable passwords — repetitive ones, keyboard and alphabet runs, entries from
  the most-used lists, and passwords containing project or hostname words. The
  rules follow NIST SP 800-63B §5.1.1.2. On top of that, failed logins are
  throttled per source IP with an exponential backoff, plus a global backstop
  that trips when many distinct IPs fail at once, so rotating the source IP
  does not lift the ceiling and a single IP cannot lock the owner out. That
  last guarantee needs Hermes to see real client IPs: under `reverse_proxy`
  without `trusted_proxy_ips`, every client shares the proxy's IP and 5
  failures from anyone lock the login for everyone.
- **Defence in depth** on actions:
  - `confirmation_token` for every destructive operation (writing or deleting
    files, restarting, uninstalling add-ons, restoring backups, dangerous
    services…). The token is bound to the tool **and its arguments**, expires,
    and is single-use. For the five tools that carry a large document
    (`ha_save_lovelace_dashboard`, `fs_write_file` and
    `ha_create_or_update_automation`/`_script`/`_scene`), the preview keeps
    that document in the add-on storage next to the token, so the
    confirmation does not have to resend it. It is deleted when the token is
    completed (successfully or not) or, if the token expires unconfirmed, at
    most 60 s after it expires; it is never written to the log.
  - Service denylist + recursive `service_data` sanitisation + automatic
    classification of dangerous scripts and automations.
  - `/config` filesystem: anti-traversal (resolve + boundary check), secret
    blacklist, *default-deny* allowlist for `.storage/`, *managed paths* that are
    never writable, automatic backup before every write.
  - Identifier validation (slug, `entry_id`, …) before interpolating them into
    URLs, plus a central anti path-injection guard in the HA client.
- **Secret redaction** in all logs, both Hermes's own and those of other add-ons.
- **Network redaction** in the log (`log_redact_network`, on by default): the
  configured `public_hostname`, any `*.ts.net` name and every IP address
  except loopback are replaced with placeholders. IPs become a pseudonym with
  their class (`tailnet`, `private`, `public`…) and an HMAC whose salt changes
  on every start, so lines from one run can be correlated without revealing
  the address. It also covers the standard Python loggers (the MCP SDK,
  uvicorn, aiohttp) and the lines `sv_get_addon_logs` returns for Hermes
  itself. Turning it off logs `log_network_redaction_disabled`; secrets are
  redacted either way.
- **CIMD downloads (SSRF).** With CIMD, the `client_id` is an `https://` URL
  chosen by whoever calls the public `/oauth/authorize`, and Hermes downloads
  it. To keep Hermes from becoming a proxy into the owner's network: the URL
  shape is checked before anything is fetched; Hermes resolves the host itself
  and refuses the request if **any** resolved address is special-use (RFC 6890:
  loopback, private, link-local, CGNAT and therefore the tailnet, ULA,
  multicast…), then connects to the already-validated addresses without
  resolving again (against DNS rebinding). The `client_id` host must be a DNS
  name: any IP literal, including the short, decimal, octal or trailing-dot
  IPv4 forms that HTTP libraries treat as IPs without resolving them, is
  refused before anything is fetched. No redirects, no environment proxies, no
  compressed bodies, 5 s in total, at most 5 120 bytes, at most 4 downloads at
  once, 30 per minute in total and 10 per source IP. Clients the owner has
  already signed in with (and every refresh with a valid refresh token) do not
  use that quota, and their cached documents are never evicted by anonymous
  ones, so an attacker cannot lock the owner out by exhausting it. The
  document is parsed as strict JSON and its `client_id` must match the URL
  exactly; errors are never cached, and every rejection is logged as
  `oauth_cimd_rejected` with the reason and the host (only when the URL is
  valid), never the document. A refresh only revokes a client's sessions when
  its document is really gone or invalid (404/410, invalid document,
  `client_id` mismatch); a 401/403, a redirect or a special-use address is
  answered with a temporary error and nothing is revoked.
  `oauth_cimd_enabled: false` turns CIMD off, including access tokens and
  codes already issued to CIMD clients, and leaves DCR as it was.
- **CIMD host allowlist (`oauth_cimd_allowed_hosts`).** Empty by default,
  which means any public host. Every CIMD download leaves **from your home
  IP** towards the host in the `client_id`, and anyone who knows your public
  hostname (it is in Certificate Transparency logs) can pick that host without
  a password. The host's owner then learns your home's public IP, which a
  tunnel such as Funnel otherwise hides. Listing hosts (for Claude Code,
  `claude.ai`) makes Hermes refuse any other host before downloading
  anything; removing a host also stops the tokens already issued to it. The
  request no longer carries the Hermes version in its `User-Agent`. claude.ai
  itself has been verified to sign in with CIMD against a real installation,
  with its document on the host `claude.ai`.
  Every resolution is logged as `oauth_cimd_document` with the result (`ok`,
  `cache` or `error` and its reason) and only the `client_id` host, which is
  public; never an IP address.
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
   bridge network, the header is ignored unless the proxy is listed in
   `trusted_proxy_ips`, and without it every per-IP limit, the login throttle
   included, becomes one shared ceiling. In no case does an IP grant access: it
   only feeds rate limiting and logs. Anyone inside a trusted range can forge
   the client IP, which skews those limits and logs but never authorization.
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
  entirely until you name the events you want. These are guard rails against
  mistakes, not a sandbox: Claude can change Hermes' own options with
  `sv_set_addon_options` after a confirmed call, so they do not hold against a
  client that has been manipulated into acting against you.
- Under `network_mode: reverse_proxy`, list your proxy in `trusted_proxy_ips`
  so that rate limits and the login throttle count each client separately.
- Restrict CIMD to the hosts you use. claude.ai and Claude Code publish their
  documents on `claude.ai` (verified with claude.ai in production), so if you
  only use Claude, `oauth_cimd_allowed_hosts: ["claude.ai"]` covers it, and
  Hermes will then never contact any other host from your home IP on behalf
  of an anonymous caller. The default stays empty so that no other client
  breaks. If another client stops connecting, the
  `oauth_cimd_rejected` event with reason `host_not_allowed` names the host
  to add.
- Watch the logs (the add-on's Log tab, or `ha apps logs <slug> -f` with the
  slug shown on the add-on's page) for repeated `oauth_login_locked`,
  `oauth_login_locked_global`, `oauth_login_throttled` or `auth_rejected`
  events.
- If you suspect the password has been seen, change `auth_password` and restart
  the add-on: every open session is closed and every client must authorize
  again with the new one.
- If you stop using Hermes, uninstall the add-on rather than just stopping it:
  uninstalling clears `/data`, and with it the stored OAuth keys and tokens.
