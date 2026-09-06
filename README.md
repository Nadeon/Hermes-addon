# Hermes — all of Home Assistant, from Claude

> Read this in: [English](README.md) | [Español](README.es.md)

[![Tests](https://github.com/Nadeon/Hermes-addon/actions/workflows/tests.yml/badge.svg)](https://github.com/Nadeon/Hermes-addon/actions/workflows/tests.yml)
[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-blue)](LICENSE)

Hermes is a **Home Assistant add-on** that exposes your installation to Claude as
an **MCP** server (Model Context Protocol, the standard Claude uses to talk to
external systems). It ships **185 tools**: turn on lights, write automations,
edit files under `/config`, manage add-ons, create backups, query history.

In practice: you ask Claude to "turn off the living room lights", or "write me an
automation that raises the blind at sunrise, but not on Sundays", and it does —
showing you what it is about to touch whenever the action is destructive.

You install it by adding this repository to the Home Assistant add-on store:
[how to do that](#installation). First you need to expose Home Assistant to the
internet; that is covered below too.

## What it can do — 185 tools

These are the names Claude sees. You do not need to learn them: a tool called
`hermes_guide` explains them to Claude on demand.

| Family | # | What it covers |
|---|---:|---|
| **States and services** | 7 | Read states, list and call services, fire events, render Jinja templates |
| **Automations and scripts** | 14 | Create, edit, delete, enable, disable and run |
| **Scenes** | 7 | Including capturing the current state of the house as a new scene |
| **Helpers** | 59 | `input_boolean`, `input_number`, `input_select`, `input_text`, `input_button`, `input_datetime`, `counter`, `timer`, `schedule` |
| **Zones and people** | 10 | Geographic zones and person tracking |
| **Registries** | 13 | Entities, devices and areas: rename, move, hide, disable |
| **Integrations** | 13 | Config entries and their config flows, options flows included |
| **`/config` files** | 11 | Read, write, move, delete, search, manage `secrets.yaml` and restore backups |
| **Lovelace** | 10 | Dashboards and resources |
| **Add-ons** | 12 | List, install, start, stop, update, read logs and statistics |
| **Backups** | 10 | Full and partial, create and restore |
| **Supervisor and system** | 6 | Host and core info, validate configuration, restart |
| **History and statistics** | 4 | History, logbook and long-term statistics |
| **HACS** | 4 | Query repositories and available updates |
| **Event waiting** | 3 | Wait for something to happen, with filters |
| **Utilities** | 2 | `ping` and `hermes_guide` |

There is one more, auxiliary, tool that is only registered with `HERMES_DEV=1`
and does not exist in a normal installation.

On their first call, destructive tools return a preview and a
`confirmation_token`. They do nothing until they are called again with that
token. That is what stops a misunderstanding from restarting your house.

## What you need

- **Home Assistant OS or Supervised.** Hermes is an add-on and needs the
  Supervisor: it does not work on HA Container or HA Core.
- **Home Assistant exposed to the internet**, so Claude can reach it. Hermes does
  not do this for you; the next section covers the three ways to get there.
- **A paid Claude plan.** Custom Connectors, which is how Hermes connects, are
  not available on the free plan.
- `amd64` or `aarch64` architecture, and Home Assistant **2024.1.0** or newer.

## How Hermes is exposed to the internet

Hermes **does not speak TLS**: it listens for plain HTTP on a local port and
assumes something in front terminates TLS and proxies to it. That "something" is
your job, and the **`network_mode`** option tells Hermes which one to expect:

| `network_mode` | Who publishes the hostname | Ports opened on your router |
|---|---|---|
| `tailscale` *(default)* | Tailscale add-on with Funnel | None |
| `reverse_proxy` | Cloudflare Tunnel, Nginx Proxy Manager, Caddy… | None with a tunnel; **443** with a classic proxy |

Whichever you pick, all Hermes needs is:

1. A **public hostname over HTTPS** that reaches it (`public_hostname`).
2. That proxy forwarding to **`mcp_bind`:8765** over plain HTTP.

> [!IMPORTANT]
> Hermes ends up reachable from the internet, and its only barrier is the
> `auth_password` password. Generate a long, random one. A tunnel (Tailscale or
> Cloudflare) is safer than opening port 443 on your router, because it exposes
> no port of your network at all.

### Option A — Tailscale Funnel *(the simplest)*

Opens no router port, and Tailscale manages the certificate. This is the option
Hermes is most thoroughly tested against.

1. Install the **official Tailscale add-on** on HAOS.
2. Set **`userspace_networking: false`**. This is mandatory: without it the
   `tailscale0` interface is never created and, under `network_mode: tailscale`,
   Hermes waits for it and never starts.
3. Enable **Funnel** and point it at the Hermes port:
   ```
   tailscale funnel --bg 8765
   ```
4. In the Hermes options:
   - `network_mode`: `tailscale`
   - `public_hostname`: the hostname Funnel gives you (e.g.
     `homeassistant.tailXXXX.ts.net`), **with no scheme and no path**
   - `mcp_bind`: `127.0.0.1` (the Tailscale add-on shares the host network, so it
     can reach the loopback)

---

### Option B — Cloudflare Tunnel *(recommended if you do not use Tailscale)*

Same model as Funnel — no open ports — but with your own domain. It is free, and
it also lets you put Cloudflare Access in front as a second barrier.

1. Install a **Cloudflared** add-on on HAOS and set it up with your domain.
2. Add an *ingress rule* pointing at Hermes. The address depends on the network
   the Cloudflared add-on runs in:
   - If it shares the host network (`host_network: true`) → `http://127.0.0.1:8765`
   - If it runs on the HAOS bridge network → `http://172.30.32.1:8765`
3. In the Hermes options:
   - `network_mode`: `reverse_proxy`
   - `public_hostname`: your domain (e.g. `hermes.yourdomain.com`)
   - `mcp_bind`: **`127.0.0.1`** if the tunnel shares the host network, or
     **`172.30.32.1`** if it runs on the bridge network

> [!WARNING]
> This is where most people get stuck. With `mcp_bind: 127.0.0.1` the port only
> exists on the *host loopback*: an add-on running on the bridge network **cannot
> reach it**, and you will see connection-refused errors in the tunnel. If your
> proxy does not share the host network, use `172.30.32.1`.

---

### Option C — Classic reverse proxy (Nginx Proxy Manager, Caddy…)

Valid if you already own a domain and run a proxy. In exchange it **requires
opening port 443** on your router: your Home Assistant is then directly exposed
to the internet, so this is the option with the largest attack surface.

1. Set up the proxy (the **Nginx Proxy Manager** or **Caddy** add-on, or an
   external one) with a valid certificate for your domain (Let's Encrypt,
   DuckDNS…).
2. Create a host that proxies **every** path (`/`) to `http://<mcp_bind>:8765`.
   Do not restrict it to `/mcp`: Hermes also serves the OAuth and discovery
   endpoints (`/.well-known/…`, `/authorize`, `/token`, `/register`, `/revoke`),
   and without them the client cannot authenticate.
3. Make sure the proxy **does not rewrite the `Host` header**: Hermes validates
   it against `public_hostname` as DNS-rebinding protection.
4. Forward port 443 on your router to the proxy.
5. In the Hermes options:
   - `network_mode`: `reverse_proxy`
   - `public_hostname`: your domain
   - `mcp_bind`: whichever address your proxy can reach (`127.0.0.1` if it shares
     the host network; `172.30.32.1` from the bridge network)

> [!CAUTION]
> Do not set `mcp_bind: 0.0.0.0` unless you know exactly what you are doing: that
> publishes Hermes **over plain HTTP** across your whole local network,
> unencrypted, bypassing the proxy's TLS.

---

## Installation

1. In Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**,
   and paste:

   ```
   https://github.com/Nadeon/Hermes-addon
   ```

2. Close the dialog. Hermes shows up in the store under its own section. Open it
   and press **Install**.

   > The image is prebuilt for `amd64` and `aarch64`, so installing takes
   > seconds: nothing is compiled on your machine.

3. Fill in the configuration:
   - **`auth_password`** *(required)*: the password you will use to authorize
     Claude. Minimum 12 characters, and Hermes also checks that it is not
     guessable: it rejects repetitive ones, keyboard runs, ones from the
     most-used lists, and ones containing "hermes" or your own hostname.
     Generate it with your password manager, or with `openssl rand -base64 18`.
     It is the only secret protecting your home.
   - **`public_hostname`** *(required)*: the public hostname, with no `https://`
     and no trailing path.
   - **`network_mode`**: `tailscale` or `reverse_proxy`, matching the option you
     set up above.
   - **`mcp_bind`**: `127.0.0.1` by default; change it only if your proxy does
     not share the host network.

4. Start the add-on and check the log. If all is well you will see a
   `hermes_started` line with the chosen mode:
   ```json
   {"event": "hermes_started", "network_mode": "tailscale", "mcp_bind": "127.0.0.1", ...}
   ```

When a new version ships, Home Assistant notifies you in the store itself and
updates with one click.

<details>
<summary>Installing it by hand, without adding the repository</summary>

If you would rather not add a third-party repository to your Home Assistant, copy
**the contents of the `hermes/` folder** (not the repository root) to
`/addons/hermes` on the host, over Samba or SSH. It will appear under **Local
add-ons** after a *Check for updates*.

Installed this way you get no new-version notifications: every update means
copying the files again.

This is also the route if you want to **build the image yourself** instead of
downloading the published one: delete the `image:` line from `config.yaml` and
the Supervisor will build from the `Dockerfile`. On Alpine that is five to ten
minutes on x86, and considerably longer on a Raspberry Pi, because
`pydantic-core`, `aiohttp` and `cryptography` are compiled from source.

</details>

### If it does not start

| Symptom in the log | Likely cause |
|---|---|
| `No Tailscale CGNAT IP … found` | You are on `network_mode: tailscale` without the Tailscale add-on ready, or with `userspace_networking: true`. Fix it or switch to `reverse_proxy`. |
| `auth_password no está configurado` | The password is missing. |
| `auth_password no es lo bastante fuerte` | It is short, repetitive, a keyboard run, one of the most-used ones, or it contains "hermes" or your own hostname. The message says which of the six. |
| `public_hostname no está configurado` | The hostname is missing. |
| `public_hostname inválido` | You wrote it with `https://` in front, a path behind, or slashes. The hostname alone goes there. |
| `mcp_bind no puede estar vacío` | You left the option blank. Set it to `127.0.0.1` or `172.30.32.1`. |
| `SUPERVISOR_TOKEN no está disponible` | You are not on Home Assistant OS or Supervised. Hermes is an add-on and needs the Supervisor. |
| `network_mode inválido` | Only `tailscale` and `reverse_proxy` are accepted. |
| The tunnel reports *connection refused* | `mcp_bind` is not reachable from your proxy. If it runs on the bridge network, use `172.30.32.1`. |

> [!NOTE]
> Startup error messages are emitted in Spanish. They are reproduced above
> verbatim so you can match them against your log.

> [!IMPORTANT]
> **Per-IP rate limiting behaves differently in each mode.** uvicorn only honours
> `X-Forwarded-For` when the connection arrives from `127.0.0.1`. Under
> `tailscale`, tailscaled proxies from the loopback and rewrites that header with
> the client's real IP, so the per-IP limit genuinely works (you can check it in
> the log: internet scanners show up with their public IP, and a hand-forged
> header is ignored).
>
> Under `reverse_proxy` with `mcp_bind` on the bridge network, the connection no
> longer arrives from the loopback: uvicorn ignores the header and **every**
> request looks like it came from the proxy, so the per-IP bucket becomes a
> global ceiling. This is not a vulnerability — nothing in the system authorizes
> by IP, the IP only feeds the rate limit and the logs, and the login
> anti-brute-force throttle is global on purpose — but it is worth knowing: if
> your proxy already rate-limits per IP, let it do the job.

## Connecting Claude

1. In Claude, mobile or desktop: **Settings → Connectors → Add custom
   connector**.
2. Paste your server URL:

   ```
   https://<your_public_hostname>/mcp
   ```

3. Claude opens the Hermes authorization page. Enter the `auth_password` you set
   in the add-on configuration.

4. Done. From there, just ask for things in plain language.

> [!IMPORTANT]
> The authorization screen tells you **which client** is asking for access and
> **which address** the code will be sent to. Read it before accepting: it is the
> only defence against someone sending you an authorization link pointing at
> their own destination.

What happens underneath, if you are curious: Claude discovers the OAuth endpoints
from the `401` Hermes returns, registers a client automatically (RFC 7591), sends
you to the login, and in exchange for your password receives a token. There are
no keys to copy and paste.

**What to expect the first time.** On connecting, Hermes hands Claude a summary of
the available tool families. When it needs detail about a specific area, Claude
queries `hermes_guide` on its own — you do not have to do anything.

## Configuration options

| Option | Default | Description |
|--------|---------|-------------|
| `auth_password` | _(required)_ | OAuth flow password. Minimum 12 characters, and checked for guessability: Hermes will not start with a weak one |
| `public_hostname` | _(required)_ | Public hostname Hermes is reached at, with no scheme and no path |
| `network_mode` | `tailscale` | Who publishes the hostname: `tailscale` (Funnel) or `reverse_proxy` (Cloudflare Tunnel, Nginx, Caddy…) |
| `mcp_bind` | `127.0.0.1` | Address Hermes listens on. Use `172.30.32.1` if your proxy runs on the HAOS bridge network |
| `log_level` | `info` | Log level (`debug`/`info`/`warning`/`error`) |
| `safety_backup_enabled` | `false` | Automatic **full** HAOS backup before writing to `/config`. Off by default (it produces several GB). The per-file backup always happens |
| `mcp_max_requests_per_minute` | `120` | Global post-auth rate limit |
| `mcp_preauth_max_requests_per_minute_per_ip` | `20` | Pre-auth per-IP rate limit. Applies only to the public surface (OAuth and discovery): protected routes are governed by `mcp_max_requests_per_minute` once the token is validated |
| `response_max_bytes` | `1048576` | Per-tool response cap (1 MB) |
| `ha_ws_max_msg_size_bytes` | `4194304` | WS message cap towards HA (4 MB). A larger result closes the whole WebSocket, not just that call: raise it if you use `ha_get_history` over wide ranges |
| `max_request_body_bytes` | `4194304` | Body cap for an authenticated HTTP request (4 MB). The public OAuth endpoints have their own fixed 64 KiB cap, independent of this option |
| `max_concurrent_requests` | `64` | Simultaneous requests the server accepts. Bounds the maximum in-flight memory (`max_concurrent_requests × max_request_body_bytes`). Claude fires bursts of ~24 calls, so 64 leaves headroom |
| `wait_for_event_max_seconds` | `90` | Maximum timeout allowed for `ha_wait_for_event` (10–300) |
| `wait_for_event_max_concurrent` | `5` | Maximum simultaneous `ha_wait_for_event` calls (1–20) |
| `safety_backup_window_minutes` | `30` | If a full backup newer than this already exists, another one is skipped |
| `file_backup_max_per_path` | `20` | Copies kept of each file before overwriting it |
| `file_backup_max_total_mb` | `200` | Total cap for the per-file backup directory |
| `config_write_min_interval_seconds` | `5` | Minimum seconds between two writes to `/config` |
| `config_write_max_per_minute` | `10` | Maximum writes per minute to `/config` |
| `health_startup_grace_seconds` | `120` | Startup grace before the watchdog decides Hermes is not coming up |
| `health_reconnect_tolerance_seconds` | `300` | How long the WebSocket to HA may stay down before reporting `unhealthy` |

### Security levers

These change **what Claude can do without asking you**. Worth reading:

| Option | Default | Description |
|--------|---------|-------------|
| `call_service_denylist_extra` | `[]` | Additional services that will require explicit confirmation, on top of the ~40 Hermes already ships. Format `domain.service`, wildcards allowed (`shell_command.*`) |
| `call_service_restricted_entities` | `[]` | Specific entities that will require confirmation even when the service is not denylisted. Useful for `script.open_garage` and friends |
| `fire_event_allowlist` | `[]` | Event types `ha_fire_event` is allowed to fire. Empty means the tool is disabled: every permitted event must be named explicitly |
| `call_service_auto_classify_dangerous` | `true` | On startup and on save, Hermes reads your scripts and automations and automatically marks as restricted the ones invoking dangerous services. Disable it only if you want to manage the list by hand |

See `config.yaml` for the full schema with valid ranges.

## Security

- **OAuth 2.1 with mandatory PKCE** (no static bearer): opaque tokens stored
  hashed (SHA-256), single-use auth codes, revocation (RFC 7009).
- **Strong password enforced**: `auth_password` ≥ 12 characters, quality filter,
  plus exponential-backoff throttling on failed attempts (anti-brute-force).
- **Hardened DCR**: `redirect_uris` validation and a client cap.
- **Confirmation tokens** for every destructive action.
- **`/config` filesystem**: anti-traversal, secret blacklist, *default-deny*
  allowlist under `.storage/`, *managed paths*, backup before every write.
- **Anti path-injection validation** of identifiers (slug, `entry_id`…) plus a
  central guard in the HA client.
- **Security headers** (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, CSP) and a body size limit (`chunked` included).
- **Secret redaction** across all logs.
- **Rate limiting** globally after authentication, plus a separate ceiling for the
  public surface (OAuth and discovery). Authentication failures get their own
  bucket, so someone without credentials cannot burn through yours.
- **CORS closed** (no `Access-Control-Allow-Origin`).
- **Listens only where you tell it to** (`mcp_bind`, `127.0.0.1` by default): it
  is never published on the network directly, there is always a proxy in front.

Threat model, assumptions and known limitations: see [SECURITY.md](SECURITY.md).
The rules all of this is written under: [docs/PRINCIPIOS.md](docs/PRINCIPIOS.md)
*(Spanish)*.

## Known limitations

- **No event streaming.** `ha_wait_for_event` waits for **one** event with a
  timeout; there is no continuous subscription pushing events to Claude.
- **Schema caching in MCP clients.** Some clients (the Claude mobile and desktop
  apps) cache the tool list after the first `initialize` and do not notice server
  changes between versions. Symptom: after updating Hermes, the client keeps
  listing the old tools. Fix: disconnect the connector, delete it and add it
  again. There is no possible server-side fix.
- **Single user.** The authorization model assumes one owner. Several concurrent
  MCP clients share the same request quota.
- **`network_mode: reverse_proxy` is less battle-tested than `tailscale`.** It has
  its tests, but sees far less real-world use. If something breaks, an issue with
  the startup log is much appreciated.

## Architecture

```
Claude (mobile/desktop)
    │
    │ HTTPS  (TLS is terminated by the proxy, never by Hermes)
    ▼
Tailscale Funnel          ─┐
Cloudflare Tunnel          ├─►  <mcp_bind>:8765  ──►  Hermes (plain HTTP)
Nginx Proxy Manager/Caddy ─┘                              │
                                                          ├── OAuth 2.1 (/.well-known/*, /oauth/*)
                                                          ├── MCP Streamable HTTP (/mcp)
                                                          └── WS to HA core + REST to Supervisor
```

- **TLS**: always terminated by the proxy in front; Hermes speaks plain HTTP and
  never handles certificates. Which of the three it is comes from `network_mode`.
- **Bind**: `mcp_bind` (`127.0.0.1` by default). Reachable only from the host
  itself, unless pointed at the HAOS bridge network (`172.30.32.1`) for proxies
  that do not share the host network.
- **Host header**: validated against `public_hostname` (anti DNS-rebinding), so
  the proxy must not rewrite it.
- **Auth**: OAuth 2.1 with PKCE, DCR, short-lived tokens, revocation.
- **Health**: separate endpoint on `172.30.32.1:8766` for the Supervisor
  watchdog.

## Development

The suite runs without deploying anything and without a Home Assistant in front:

```bash
python -m venv .venv
.venv/bin/pip install -r hermes/requirements.txt
.venv/bin/pip install pytest pytest-asyncio aioresponses httpx
.venv/bin/pytest
```

On Windows, `.venv\Scripts\` instead of `.venv/bin/`.

Test dependencies are kept separate on purpose: `hermes/requirements.txt` is what
the add-on needs to **run**, not to be tested. `pytest.ini` fixes the import
paths, so there is no need to export `PYTHONPATH`.

**Layout**: the root is a Home Assistant add-on repository (`repository.yaml`),
and the whole add-on lives in `hermes/`. The Python code is under
`hermes/src/hermes/`, and the tests under `tests/` at the root.

**Testing changes against a real Home Assistant**: copy the contents of `hermes/`
to `/addons/hermes` on the host and **delete the `image:` line** from the
`config.yaml` you leave there — otherwise the Supervisor downloads the published
image instead of building your changes. Then:

- `ha apps rebuild local_hermes` if you touched the `Dockerfile` or dependencies
- `ha apps restart local_hermes` if you only touched Python
- `ha apps logs local_hermes -f` to watch the log

**`HERMES_DEV=1`** registers an auxiliary diagnostic tool that is not exposed in a
normal installation.

More detail, and the conventions a pull request is expected to follow, in
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

**PolyForm Noncommercial 1.0.0**. © 2026 Nadeon.

**You may** use, study, modify and share Hermes, and build on it, for any
**non-commercial** purpose: at home, to learn, for research, or inside a
non-profit organization.

**You must** keep the attribution notice from [LICENSE](LICENSE) in any copy you
distribute, so whoever receives it knows where it came from. That is the
attribution the license requires. A mention in a README, an article or a video is
appreciated, but what the license mandates is that the notice travels with the
code.

**You may not** make money from it: not by selling it, not by offering it as a
paid service, not by folding it into a commercial product. For commercial use,
ask.

This is not an open source license: it does not meet the OSI definition, purely
because of that restriction, and that is deliberate.

Full text in [LICENSE](LICENSE).

## Contributing

Improvements are welcome: issues and pull requests. By opening a pull request you
agree to your contribution being published under this same license.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before you start — it covers the branch
and PR workflow, how to report an issue, and the three conventions that get
review comments most often. Participation is governed by our
[Code of Conduct](CODE_OF_CONDUCT.md).

To report a **security** flaw, do not open an issue: use the
[private advisory form](../../security/advisories/new). See
[SECURITY.md](SECURITY.md).
