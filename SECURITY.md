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
    most 60 s after it expires; it is never written to the log. The same goes
    for the single view of `ha_save_lovelace_dashboard` (`view_index` +
    `view`). Saving a single view also binds the token to the state of the
    dashboard read in the preview (only its hash is stored): if the dashboard
    changes before the confirmation, it is refused (`dashboard_changed`) and
    nothing is saved.
  - Service denylist + recursive `service_data` sanitisation + automatic
    classification of dangerous scripts and automations. The denylist asks
    for confirmation in both `ha_call_service` and
    `ha_call_service_response`: a denylisted service, or one that reaches a
    restricted script or automation, only runs with a `confirmation_token`
    bound to that tool and its arguments (the response tool stores only
    `{"called": true}` next to the token, never the response). The HA client
    enforces the same denylist on both service endpoints, so no other code
    path can run a denylisted service. Only tools with two-step confirmation
    lift it, and only after validating their token: `ha_call_service` and
    `ha_call_service_response` (a denylisted service or a restricted script
    or automation), the reload tools `ha_reload_automations`,
    `ha_reload_scenes`, `ha_reload_schedules`, `ha_reload_scripts`,
    `ha_reload_timers` and `ha_reload_zones` (always confirmed, since a
    reload applies whatever YAML is in `/config`; `ha_reload_counters` no
    longer calls Home Assistant, which has no `counter.reload`, and answers
    `not_supported`), and
    `ha_run_script` and `ha_trigger_automation` (only for a restricted
    script or automation), `ha_clear_system_log` and
    `ha_dismiss_persistent_notification` (always confirmed: clearing the
    system log or dismissing a notification hides traces), and
    `ha_install_update` (1.2.0; always confirmed, with the token bound to
    the from/to versions: `update.install` is in the denylist). A test walks
    the code and fails if any other place lifts it.
  - **`update.install` through `ha_call_service`** (1.2.0) is checked before
    any token is issued or accepted: the target must be an explicit list of
    `entity_id` (no area, device, label, floor or `all`), each entity is
    resolved through the entity registry, Hermes' own update entity is
    refused (`self_update_not_supported`; fail-closed when Hermes cannot read
    its own app slug), and the Core, OS and Supervisor entities are sent to
    `sv_update_core`, `sv_update_os` and `sv_update_supervisor`, which run
    their own checks (configuration check for Core). Without this, Hermes
    could update itself through Core, which calls the Supervisor as Core and
    so skips the Supervisor's own self-update protection.
  - **Generic tools behind a fail-closed command table.**
    `ha_read_ws_command`/`ha_call_ws_command` (Core WebSocket commands) and
    `sv_read_api`/`sv_call_api` (Supervisor API routes) cover what no
    dedicated tool does, and run only what Hermes' command table
    (`command_table.py`) allows. Every one of the 623 Core commands and 254
    Supervisor routes of HA 2026.11 is classified by hand as `dedicated`,
    `read`, `confirm` or `deny`; anything not in the table is refused. A
    refusal never reaches Home Assistant or the Supervisor. The generic tools
    never: run a command that has a dedicated tool (it may carry a semantic
    preview or protections of its own), even when that tool's family is
    switched off; run a `confirm` entry without a preview and a token bound to
    the tool, the command or method and route, and the whole payload; go
    through the Supervisor's Core proxy (`/core/api`, `/homeassistant/api`,
    which would bypass the service denylist); act on Hermes itself
    (`{app}` resolving to Hermes); accept malformed paths (`..`, encoded
    dots, `//`, query strings, absolute URLs); or run anything belonging to a
    family switched off with `tool_families_disabled`. The preview shows every
    payload key with its type and size, and a value only when it is short and
    no key on its path or its content looks secret. Only `{"executed": true}`
    is stored next to the token, never the answer. Answers go through the
    secret redaction and the response cap; the log records one
    `generic_command` event per call with the payload keys, never values.
    Under a sensitive key (by name, or listed in the entry's `redact_extra`)
    the WHOLE value is masked, whatever its type: an object or a list is not
    walked, so a network key nested as `{"key": …}` cannot leak. Commands of
    specific integrations (Z-Wave JS, ZHA, Matter, Thread, MQTT, KNX,
    Insteon…) that return or take network keys, DSKs, pairing codes, tokens or
    passwords are refused, or answered with those values masked.
    Tests keep the table in step with the inventories of the HA source and
    forbid `read` for any command with a write verb or any route other than
    `GET`. Some `read` entries hide fields that work as credentials: the
    `webhook_id` of `webhook/list` (anyone who knows it can trigger the
    automation without authenticating; its value is also hidden wherever
    it repeats in the answer, whole or inside a text, such as the `name`
    that ONVIF sets to the id, and an entry without a readable
    `webhook_id` keeps only its domain, `local_only` and methods; every
    answer that redacts by key hides a `webhook_id` value the same way),
    the `client_secret` and the
    credential id of the application credentials, and the `thumbnail` of
    `media_source/browse_media` and `search_media` (some media sources sign
    it with `authSig`, a temporary credential); `media_source/resolve_media`,
    which returns a signed URL, is denied.
  - **App store repositories** (`sv_add_store_repository`): adding a
    repository to the Supervisor app store brings in third-party code that
    neither Home Assistant nor Hermes reviews, so it takes two steps. The
    preview shows the exact URL that will be sent and a third-party code
    warning, and Hermes downloads nothing for it (the Supervisor clones the
    repository only when the token is confirmed). The whole user part of a
    URL with credentials (`user:password@`, `user@` or `token@`) is
    replaced by `***REDACTED***` in previews, answers and errors, including
    the Supervisor's own error text; only the real request carries the full
    URL, and the confirmation token is bound to it, so a different
    credential cannot confirm the preview. The log records only the
    repository slug, never the URL. Repository names, URLs and maintainers are marked as third-party
    text (`_third_party_text`). Removing a repository also takes two steps;
    a built-in one, or one with installed apps, is refused without a token,
    and the token is bound to the repository and its installed apps read
    in the preview.
  - **Sending a sentence to Assist** (`ha_process_conversation`): it executes
    the sentence as if it were spoken (it can open a lock, disarm an alarm or
    run an automation with a sentence trigger), so it always takes two steps,
    although the WebSocket command it uses, `conversation/process`, does not
    go through the service denylist (which only guards actions such as
    `conversation.process`). The preview says which agent gets the text and,
    with Home Assistant's built-in agent, what it recognizes, without
    executing anything; with any other agent it warns that the text is sent
    to it, maybe to a cloud service, and that Hermes cannot predict what it
    will do. The token is bound to the text, the agent, the language, the
    conversation and the device, and stores only their hash: the sentence is
    never written to `/data`. If Home Assistant does not answer in time, the
    answer says the sentence may have run anyway and the token is spent. The
    generic tools cannot reach `conversation/process` (`dedicated`). The log
    never records sentences, answers, conversation ids or agent ids.
  - **Assist audio URLs**: Home Assistant serves `/api/tts_proxy/<token>`
    without authentication, so anyone with that URL can download the audio.
    The generic tools hide any such URL in their answers (for example in
    `assist_pipeline/pipeline_debug/get`).
  - **Resetting a dashboard** (`ha_reset_lovelace_dashboard_config`):
    deletes the stored config of a dashboard, in two steps. The main
    dashboard and the default panel are always refused, with or without a
    token, and nothing is reset if the default panel cannot be read. The
    token is bound to the dashboard and to the config read in the preview:
    if it changes before the confirmation, nothing is reset. The log never
    carries the dashboard config.
  - **Marketplace maintenance** (`marketplace_manage`): acknowledging a
    critical repository, ignoring a removed one, removing a custom one and
    refreshing one all take two steps, and the token is bound to what the
    preview read (the critical or removed entry, the repository name,
    category, `custom` and `installed`). The preview states that the
    repository is third-party code that neither Home Assistant nor Hermes
    reviews. Uninstalling also takes two steps; an integration with config
    entries is refused without a token, and on confirmation Hermes first
    asks the Supervisor for a partial backup of the Home Assistant
    configuration without the database (not encrypted, with a generic name
    that does not include the repository) and sends nothing to Home
    Assistant if it fails. Only `marketplace/*` commands from a closed list are sent;
    Hermes never accepts the Marketplace risk warning nor connects GitHub,
    and it has no tool to install, pin versions, show betas or add
    repositories: Home Assistant requires the risk warning accepted by the
    user that sends the command, and Hermes connects as the Supervisor user.
    The log records the tool, the outcome and the category, never
    repository names, ids or third-party text.
  - **Tool families** (`tool_families_disabled`): whole groups of tools can
    be left unregistered. An unknown family name, or `base`, stops the add-on
    from starting rather than silently leaving tools on.
  - `/config` filesystem: anti-traversal (resolve + boundary check), secret
    blacklist, *default-deny* allowlist for `.storage/`, *managed paths* that are
    never writable, automatic backup before every write.
  - Identifier validation (slug, `entry_id`, …) before interpolating them into
    URLs, plus a central anti path-injection guard in the HA client.
- **Home Assistant's backup encryption key** (1.2.0). Hermes reads it from
  Home Assistant (`backup/config/info`) only when it is about to use it: to
  encrypt a safety backup (`safety_backup_encryption`) or a backup made with
  `ha_create_backup`, or to restore a protected backup without `password`. It
  is sent to the Supervisor or to Home Assistant in that same call and then
  dropped: it is never written to disk (safety backup state, retention
  ledger, pending jobs, confirmation tokens), never kept in memory between
  calls, never returned in a preview, answer or error (an error that quoted
  it is masked) and never logged. Tests plant a sentinel key and check every
  one of those outputs. Hermes never changes the key; that stays in the Home
  Assistant UI, which hands out the emergency kit.
- **Secret redaction** in all logs, both Hermes's own and those of other add-ons.
- **Network redaction** in the log (`log_redact_network`, on by default): the
  configured `public_hostname`, the hosts of Home Assistant's `external_url`
  and `internal_url` (read from `/api/config` on every connection), any
  `*.ts.net` name and every IP address except loopback, also when written as
  `ip-a-b-c-d` (cloud hostnames like `ip-10-0-0-5.ec2.internal`), are replaced
  with placeholders. IPs become a pseudonym with
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
6. **Reconfigure and re-authentication flows are recognised by what Hermes
   can see.** Every step of an integration's reconfigure flow and of a
   re-authentication (`reauth`) flow needs a preview and a
   `confirmation_token`, because both can change the credentials of an
   integration. Home Assistant does not say which kind of flow a `flow_id`
   is when it is continued, so Hermes fails closed:
   - a reconfigure is recognised only because Hermes opened it
     (`ha_start_reconfigure_flow`) and keeps its `flow_id` in memory;
   - a re-authentication is recognised because Home Assistant lists it, with
     its source, among the flows in progress;
   - `ha_continue_config_entry_flow` only continues a flow that
     `ha_start_config_entry_flow` opened in the same Hermes session (also
     kept in memory, for an hour since its last use) or that Home Assistant
     lists among the flows in progress. Any other `flow_id` (a flow opened
     before Hermes restarted or from the Home Assistant UI, or a reconfigure)
     is refused without sending anything, and so is every flow while the
     list of flows in progress cannot be read.

   The cost: after Hermes restarts, a flow that was half-way has to be
   started again.

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
