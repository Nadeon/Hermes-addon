# Hermes — all of Home Assistant, from Claude

> Read this in: [English](README.md) | [Español](README.es.md)

[![Tests](https://github.com/Nadeon/Hermes-addon/actions/workflows/tests.yml/badge.svg)](https://github.com/Nadeon/Hermes-addon/actions/workflows/tests.yml)
[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-blue)](LICENSE)

Hermes is a **Home Assistant add-on** that exposes your installation to Claude as
an **MCP** server (Model Context Protocol, the standard Claude uses to talk to
external systems). It ships **326 tools**: turn on lights, write automations,
edit files under `/config`, manage add-ons, create backups, query history.

> Since Home Assistant 2026.2 the interface calls add-ons **apps**. This guide
> keeps the term "add-on", as do the repository name and the Supervisor API.

In practice: you ask Claude to "turn off the living room lights", or "write me an
automation that raises the blind at sunrise, but not on Sundays", and it does —
showing you what it is about to touch whenever the action is destructive.

You install it by adding this repository to the Home Assistant add-on store:
[how to do that](#installation). First you need to expose Home Assistant to the
internet; that is covered below too.

## What it can do — 326 tools

These are the names Claude sees. You do not need to learn them: a tool called
`hermes_guide` explains them to Claude on demand.

| Family | # | What it covers |
|---|---:|---|
| **States and services** | 7 | Read states, list and call services, fire events, render Jinja templates |
| **Automations and scripts** | 14 | Create, edit, delete, enable, disable and run. Since 1.2.0 the preview of a create or edit is validated by Home Assistant (triggers, conditions and actions, also through a blueprint) and gives no confirmation token if Home Assistant would reject it |
| **Scenes** | 7 | Including capturing the current state of the house as a new scene |
| **Helpers** | 59 | `input_boolean`, `input_number`, `input_select`, `input_text`, `input_button`, `input_datetime`, `counter`, `timer`, `schedule` |
| **Zones and people** | 10 | Geographic zones and person tracking |
| **Registries** | 26 | Entities, devices, areas, floors, labels and categories: rename, move, hide, disable, delete. Deleting a floor or a label previews which automations and scripts use it as a target and will stop matching, apart from those only related to it |
| **Integrations** | 13 | Config entries and their config flows, options flows included |
| **`/config` files** | 11 | Read, write, move, delete, search, manage `secrets.yaml` and restore backups |
| **Lovelace** | 10 | Dashboards and resources |
| **Add-ons** | 12 | List, install, start, stop, update, read logs (also from previous boots) and statistics |
| **Backups** | 13 | Full and partial, create (optionally on a chosen backup mount) and restore. Also, read-only, the backups of Home Assistant's `backup` integration (HA 2025.1 or later) in every location (local, network, cloud), and its configuration without the encryption password |
| **Supervisor and system** | 6 | Host and core info, validate configuration, restart |
| **Mounts** | 9 | Supervisor network mounts (CIFS and NFS) and local disk mounts for backups, media and share: list, create, edit, delete, re-check and choose the default backup mount, always with a preview. Also the Supervisor's backup settings (when backups count as stale) and re-reading the backups of every location. CIFS credentials go in but never come out (not in responses, previews, errors or logs) |
| **Core and Supervisor control** | 7 | Start Home Assistant Core when it is stopped, rebuild it (also in safe mode) and change its Supervisor options (boot, watchdog, audio…); reload, restart and repair the Supervisor and change its options (time zone, country, logging, auto-update, diagnostics). Everything that interrupts something shows what stops, for how long and what happens to Hermes, and asks for confirmation (reloading does not); options go through closed lists. Family `system_control`, new in 1.2.0 |
| **System diagnostics** | 11 | Read only: Home Assistant Core, Supervisor, plugin (`dns`, `audio`, `multicast`) and host journal logs, also from previous boots, with secrets redacted; the journal's identifiers and boots; host services, what fills the disk, Home Assistant OS version and slots, swap and data disk candidates |
| **System updates** | 8 | What has an update (Core, OS, Supervisor, apps and plugins), check for updates and update Core, the OS and the Supervisor: the preview gives versions, backup, what restarts (an OS update only applies when the host reboots), system health and, for Core, the configuration check, and gives no token if the Supervisor would refuse it. Update entities (device firmware, integrations, HACS): list them, read their release notes and install them with versions, notes and backup in the preview; Core, OS, Supervisor and app entities are sent to their tools, and Hermes never updates itself |
| **History and statistics** | 4 | History, logbook and long-term statistics |
| **Diagnostics** | 8 | Repairs issues (list, with their title and description as the UI shows them, and ignore), automation and script traces, what is related to an item, and the Supervisor resolution center (read, and dismiss issues and suggestions; applying one is the next row) |
| **Resolution fixes** | 1 | Apply a Supervisor resolution suggestion after a preview that explains what it does (what it interrupts, whether it can be undone, which full backups it would delete, which automatic fixes the Supervisor applies on the way), always with confirmation. Suggestions with no fix, that Hermes cannot explain, that touch the data disks or that act on Hermes itself are refused. Family `resolution_fixes`, new in 1.2.0 |
| **Marketplace (formerly HACS)** | 11 | Read-only: status, repositories, available updates, published versions, critical and removed repositories. Detects on every call whether Home Assistant has the built-in Marketplace (2026.11 or later) or HACS 2.x. Updates are installed through the `update` entity, with confirmation. The 4 `ha_hacs_*` tools remain as deprecated aliases until 1.3.0 |
| **Marketplace maintenance** | 4 | Acknowledge a critical repository, ignore the removal of a repository taken off the catalogue, remove a custom repository that is not installed and refresh a repository from GitHub, each in two steps with a preview (installs nothing; the repository is third-party code nobody reviewed). Installing, pinning a version, showing betas and adding repositories are not possible: Home Assistant requires the Marketplace risk warning accepted by the Home Assistant user Hermes connects as (the Supervisor user), who cannot accept it, and Hermes never accepts it. Family `marketplace_manage`, new in 1.2.0 |
| **Event waiting** | 3 | Wait for something to happen, with filters |
| **Utilities** | 2 | `ping` and `hermes_guide` |
| **System status** | 5 | Read only: the system health report (what Settings > System > Repairs > System information shows), whether Home Assistant or the host needs a restart, how long each integration took to set up, and integration manifests. Family `system_status`, new in 1.2.0 |
| **Recorder** | 8 | Whether the recorder is recording (and whether one entity is recorded), the problems Home Assistant finds in long-term statistics and the metadata of the statistics you name (read only); and statistics maintenance with a preview and confirmation: clear statistics (whole or a time range), convert their unit, fix their stored unit, adjust a sum, import hourly statistics. Family `recorder`, new in 1.2.0 |
| **Energy** | 2 | Read the energy dashboard configuration (sources, electricity devices and water devices) and save it with a preview and confirmation: each list you pass replaces that list, the others are kept, and the preview shows what goes in and out. Family `energy`, new in 1.2.0 |
| **Core diagnostics** | 12 | Home Assistant's system log (grouped errors, and clear it), the raw error log when HA writes one, log levels (read them, and raise an integration to DEBUG to troubleshoot it), validating automations and scripts before saving them, testing a condition, integration and device diagnostics, and persistent notifications (list and dismiss) |
| **Integration flows** | 12 | Discovered integrations (list and ignore), the domains that can be set up with a config flow, an integration's title and system options (polling and new entities; disabling them asks for confirmation), config subentries (add, reconfigure, rename; deleting asks for confirmation) and reconfiguring an integration (every step asks for confirmation) |
| **Repair flows** | 4 | One Repairs issue with its internal data (redacted), and its fix flow: open it, submit each step (every step asks for confirmation) or abort it |
| **App store** | 9 | The Supervisor app store repositories: list them (with their apps and which are installed), add one (third-party code: two steps, the exact URL in the preview, the credentials in the URL hidden), remove one (two steps; refused if it is built-in or has installed apps), repair one and reload the store. The changelog and documentation of the store version of an app (third-party text, redacted, in chunks), whether it can be installed on this system, and rebuilding an installed app (two steps). Installing, updating and changing options now check first: availability, the changelog and the Supervisor's validation of the options. Family `app_store`, new in 1.2.0 |
| **Blueprints** | 5 | List the automation, script and template blueprints, preview the config a blueprint gives with some inputs, save a blueprint you write, import one from a URL (Home Assistant downloads it; the preview shows the whole YAML and it is saved only if it has not changed) and delete one nobody uses (saving, importing and deleting, with confirmation). Family `blueprints`, new in 1.2.0 |
| **Automation assist** | 9 | Read only: the device triggers, conditions and actions a device offers (ready to paste into an automation, with their extra fields), what a target (entities, devices, areas, floors, labels) really covers and why, the names of the triggers, conditions and actions that apply to it, and waiting once for a trigger to fire (only triggers known to just listen). Family `automation_assist`, new in 1.2.0 |
| **Generic commands** | 4 | `ha_read_ws_command`, `ha_call_ws_command`, `sv_read_api` and `sv_call_api`: what no other tool covers, and only what Hermes' command table allows (writes always in two steps) |

There is one more, auxiliary, tool that is only registered with `HERMES_DEV=1`
and does not exist in a normal installation.

If your client struggles with this many tools, switch off whole groups with
the `tool_families_disabled` option (for example `lovelace` or
`marketplace`); see [DOCS.md](hermes/DOCS.md) for the list of families. `ping`
and `hermes_guide` are always on, and switching off the families new in 1.2.0
(`generic_commands`, `system_diagnostics`, `system_status`, `recorder`,
`core_diagnostics`, `integration_flows`, `repair_flows`, `mounts`,
`system_updates`, `app_store`, `blueprints`, `automation_assist`, `energy`,
`system_control`, `resolution_fixes` and `marketplace_manage`)
gives you exactly the tool list of 1.1.2.

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
- `amd64` or `aarch64` architecture, and Home Assistant **2024.10.0** or newer. Hermes saves automations
  with the plural keys (`triggers`, `actions`) that Home Assistant only
  understands since 2024.10. The add-on declares it, so on an older Home
  Assistant the Supervisor refuses to install or update Hermes.

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

1. Install the **Tailscale add-on** on HAOS. It is the community add-on (Home
   Assistant Community Add-ons repository, `a0d7b954`), not an official one,
   although the store lists it by default.
2. Set **`userspace_networking: false`**. This is mandatory: without it the
   `tailscale0` interface is never created and, under `network_mode: tailscale`,
   Hermes waits for it and never starts.
3. Enable **Funnel** and point it at the Hermes port. The command runs
   **inside the Tailscale add-on's container**: that is where the `tailscale`
   binary and the `tailscaled` socket live, and since that add-on shares the
   host network, `127.0.0.1:8765` from inside it is Hermes. No add-on option
   does this: `share_homeassistant` only publishes Home Assistant, and
   `services` exposes other ports only within the tailnet (Serve), not to the
   internet (Funnel).

   The Tailscale add-on has no terminal in the HA UI. The most direct way in:
   1. Install **Advanced SSH & Web Terminal** (the community one; the official
      "Terminal & SSH" gives no Docker access).
   2. On its **Info** tab, disable **Protection mode**. Without that there is
      no `docker` command. You can turn it back on when done.
   3. From its web terminal:
      ```
      docker exec -it addon_a0d7b954_tailscale tailscale funnel --bg --https=8443 8765
      docker exec -it addon_a0d7b954_tailscale tailscale funnel status
      ```
      If the container name does not match, `docker ps | grep tailscale`
      gives it. `funnel status` must list `https://<hostname>:8443` pointing
      at `http://127.0.0.1:8765`.

   **Why 8443 and not 443.** Funnel only accepts ports 443, 8443 and 10000.
   The Tailscale add-on's `share_homeassistant: funnel` option publishes Home
   Assistant on 443 by default, at the same path `/`, and a second Funnel on
   the same port and path replaces the first: whichever was set up last wins
   and the other stops answering. With Hermes on 8443 (or 10000) the two never
   collide, now or if you enable that option later. If you do not use
   `share_homeassistant: funnel`, 443 still works: `tailscale funnel --bg 8765`
   and a `public_hostname` with no port.

   Four things to know:
   - **Funnel must be allowed on your tailnet**: HTTPS enabled and the
     `funnel` attribute in the access policy. If it is not, the command prints
     a link to the Tailscale admin panel to enable it; it does not fail
     silently.
   - **The Funnel lives in `tailscaled`'s state, not in the add-on options**,
     so the HA UI does not show it. It survives add-on restarts and updates,
     but not a reinstall. If Hermes ever becomes unreachable after touching
     Tailscale, check `tailscale funnel status` first.
     One exception on updates: the first time a Tailscale add-on 0.14.0 or
     later starts, it runs `tailscale serve reset` once, which erases every
     Serve and Funnel setting, this one included. If you set up the Funnel on
     an older version and then updated, run the `funnel --bg --https=8443 8765`
     command again. It does not happen a second time.
   - `--bg` is what makes it persistent. Without it, the Funnel lasts only as
     long as the foreground command.
   - **Hermes and `share_homeassistant: funnel` must be on different ports.**
     That option publishes Home Assistant with `tailscale funnel
     --https=<share_on_port> --set-path=/`, and `share_on_port` defaults to
     `443`. With Hermes on 8443, leave it at 443 (or use 10000); just do not
     set it to 8443. You can tell they collided when `tailscale funnel status`
     shows `/` on Hermes' port pointing at Home Assistant's port (`8123` by
     default) instead of `http://127.0.0.1:8765`.
4. In the Hermes options:
   - `network_mode`: `tailscale`
   - `public_hostname`: the hostname Funnel gives you **followed by the
     port** (e.g. `homeassistant.tailXXXX.ts.net:8443`), **with no scheme and
     no path**. With the Funnel on 443, the hostname alone.
   - `mcp_bind`: `127.0.0.1` (the Tailscale add-on shares the host network, so it
     can reach the loopback)

   The connector URL in Claude will be
   `https://homeassistant.tailXXXX.ts.net:8443/mcp`.

**Moving an existing setup from 443 to 8443.** The port is part of the
address Claude uses and of the OAuth URLs Hermes announces, so the connector
has to be added again:

1. Remove the old Funnel and create the new one, from the same terminal:
   ```
   docker exec -it addon_a0d7b954_tailscale tailscale funnel --https=443 off
   docker exec -it addon_a0d7b954_tailscale tailscale funnel --bg --https=8443 8765
   ```
   If Home Assistant is also published with `share_homeassistant: funnel`, skip
   the first line: 443 now belongs to Home Assistant. Restart the Tailscale
   add-on so it publishes it again.
2. In the Hermes options, change `public_hostname` to
   `homeassistant.tailXXXX.ts.net:8443` and restart the add-on.
3. In Claude, remove the Hermes connector and add it again with
   `https://homeassistant.tailXXXX.ts.net:8443/mcp`. Authorize it with your
   `auth_password`.

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

1. In Home Assistant: **Settings → Apps → Install app → ⋮ → Repositories**
   (before HA 2026.2: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**),
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
     guessable: it rejects repetitive ones, alphabet, digit and keyboard runs,
     ones from the most-used lists, and ones containing "hermes",
     "homeassistant" or your own hostname.
     Generate it with your password manager, or with `openssl rand -base64 18`.
     It is the only secret protecting your home.
   - **`public_hostname`** *(required)*: the public hostname, with no `https://`
     and no trailing path. If it is not served on 443, add the port
     (`homeassistant.tailXXXX.ts.net:8443`).
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
apps** (**Local add-ons** in older versions) after a *Check for updates*.

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
| `auth_password no es lo bastante fuerte` | It is short, repetitive, an alphabet, digit or keyboard run, one of the most-used ones, or it contains "hermes", "homeassistant", "hassio", "supervisor" or your own hostname. The message says which rule it broke. |
| `public_hostname no está configurado` | The hostname is missing. |
| `public_hostname inválido` | You wrote it with `https://` in front, a path behind, or slashes. The hostname alone goes there. |
| `trusted_proxy_ips contiene un valor que no es una IP ni una red` | A typo in that list. Write single IPs (`172.30.32.2`) or CIDR ranges (`172.30.32.0/23`). |
| `SUPERVISOR_TOKEN no está disponible` | You are not on Home Assistant OS or Supervised. Hermes is an add-on and needs the Supervisor. |
| `network_mode inválido` | Only `tailscale` and `reverse_proxy` are accepted. |
| `HA core … < minimum supported 2024.10.0` | Your Home Assistant is too old. Update it. |
| `No se puede escuchar el health en …` | Something else holds port 8766, or the HAOS bridge network is missing. The message ends with a hint about which. |
| `Crash loop detectado` | Hermes started 10 times in 5 minutes and stopped itself. Fix the cause shown earlier in the log, then start the add-on by hand. Manual restarts count too. |
| The tunnel reports *connection refused* | `mcp_bind` is not reachable from your proxy. If it runs on the bridge network, use `172.30.32.1`. A blank `mcp_bind` silently becomes `127.0.0.1`. |

`ha_core_version_untested` is only a warning: your Home Assistant is newer than
the last version Hermes was checked against. Hermes keeps working.

> [!NOTE]
> Most startup error messages are emitted in Spanish; the Tailscale IP and
> Home Assistant version ones are in English. They are reproduced above
> verbatim so you can match them against your log.

### Calls that fail in bursts (502)

Measured in September 2026 against a real installation, from Claude Code, with
Hermes 1.0.5 and 1.0.8:

- When a client fires **6 or more tool calls in parallel**, between 15 % and
  30 % of them come back as a `502` generated by Cloudflare for
  `api.anthropic.com` ("origin returned an invalid or incomplete response"), in
  the same second as the calls that do get through.
- Those calls **never reach Hermes**: they are absent from its log, and the
  Tailscale log shows no proxy error for them.
- Single calls, and bursts of up to 4, never failed. Hermes answers each call in
  3 to 15 ms.

So this is not a Hermes bug and not your network: the loss happens between
Anthropic's connector proxy and the Funnel ingress. In claude.ai, which makes
one call at a time, it does not show. How to tell it apart from a real problem:
a failed call that **is** in Hermes' log is Hermes'; a failed call that is
**not** in the log never arrived. Look for an `http_request` line with a 4xx/5xx
status, and also for `auth_rejected`, `rate_limit_pre_auth`,
`rate_limit_post_auth`, `auth_failure_flood` and `body_too_large`: those
rejections happen before the request reaches the `http_request` logger. To
isolate the Funnel side, run 8 `curl` in parallel from outside your network against
`https://<public_hostname>/.well-known/oauth-protected-resource`, staying under
the pre-auth limit of 20 per minute: if they fail, it is Funnel; if not, it is
upstream.

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
> global ceiling. The login anti-brute-force throttle is hit harder: it locks
> each IP after 5 failed passwords, and with every request seen as the proxy,
> **5 failures from anyone lock the login for everyone, you included**, with a
> backoff that grows up to 5 minutes per step. This is not a vulnerability —
> nothing in the system authorizes by IP, the IP only feeds the rate limits and
> the logs — but it is a denial of service anyone can trigger. Set
> `trusted_proxy_ips` (below) and it goes away.
>
> **`trusted_proxy_ips` restores the per-IP limits in that mode.** List there
> the address of your proxy, or the range it sits on (`172.30.32.0/23` is the
> whole HAOS bridge network), and Hermes trusts its `X-Forwarded-For` again, so
> the pre-auth bucket, the auth-failure bucket and the login throttle go back to
> counting one client at a time. Trust as little as you can: anybody inside a
> range you trust can forge the client IP — which only skews the rate limits and
> the logs, never authorization.

### Claude Code cuts slow calls at 60 s

Claude Code drops a call if it receives no byte for 60 seconds. Hermes answers
in streaming and sends a *ping* every 15 s, so a long `ha_wait_for_event` is not
cut. If the proxy in front buffers the whole response before forwarding it, the
pings arrive too late: raise the limit in Claude Code with the
`MCP_TOOL_TIMEOUT` environment variable (milliseconds) or with `timeout` in the
server entry.

## Connecting Claude

1. In Claude, mobile or desktop: **Settings → Connectors → Add custom
   connector**.
2. Paste your server URL:

   ```
   https://<your_public_hostname>/mcp
   ```

   `public_hostname` includes the port when there is one: with the Tailscale
   Funnel on 8443 it is `https://homeassistant.tailXXXX.ts.net:8443/mcp`.

3. Claude opens the Hermes authorization page. Enter the `auth_password` you set
   in the add-on configuration.

4. Done. From there, just ask for things in plain language.

> [!IMPORTANT]
> The authorization screen tells you **which client** is asking for access and
> **which address** the code will be sent to. Read it before accepting: it is the
> only defence against someone sending you an authorization link pointing at
> their own destination.

What happens underneath, if you are curious: Claude discovers the OAuth endpoints
from the `401` Hermes returns, identifies itself, sends you to the login, and in
exchange for your password receives a token. There are no keys to copy and
paste. Clients that publish a metadata document (CIMD), such as Claude Code,
identify themselves with that document's URL: Hermes downloads it, checks it,
and the authorization screen shows the host of that URL. The rest register a
client automatically (RFC 7591), as before. Every redirect back to the client
carries the `iss` parameter (RFC 9207), so the client can tell the answer comes
from Hermes.

**How long it lasts.** Each authorization is good for **7 days**: Claude renews
its access every hour within that week, but once it runs out the connector asks
for your password again. Up to 5 authorizations can be alive at once (phone,
desktop…); a sixth closes the one that has gone longest without use.

**Closing every session.** Change `auth_password` and restart the add-on: on
startup Hermes notices the new password and closes every open session, so each
client has to authorize again with it. The log shows
`oauth_sessions_revoked_password_changed`. Since 1.0.11; on earlier versions
the sessions kept working until their 7 days ran out.

**What to expect the first time.** On connecting, Hermes hands Claude a summary of
the available tool families. When it needs detail about a specific area, Claude
queries `hermes_guide` on its own — you do not have to do anything.

## Configuration options

The configuration page of the app shows a name and a short description of
each option, in English or Spanish (`hermes/translations/`). The full detail
is below.

| Option | Default | Description |
|--------|---------|-------------|
| `auth_password` | _(required)_ | OAuth flow password. Minimum 12 characters, and checked for guessability: Hermes will not start with a weak one |
| `public_hostname` | _(required)_ | Public hostname Hermes is reached at, with no scheme and no path. With a port other than 443, include it (`host:8443`) |
| `network_mode` | `tailscale` | Who publishes the hostname: `tailscale` (Funnel) or `reverse_proxy` (Cloudflare Tunnel, Nginx, Caddy…) |
| `mcp_bind` | `127.0.0.1` | Address Hermes listens on. Use `172.30.32.1` if your proxy runs on the HAOS bridge network |
| `trusted_proxy_ips` | `[]` | Proxies whose `X-Forwarded-For` is trusted, as plain IPs or CIDR ranges (`172.30.32.0/23` is the HAOS bridge network). Empty means only `127.0.0.1` is trusted, which under `reverse_proxy` turns every per-IP limit into a single global bucket. Anybody inside a trusted range can forge the client IP (rate limits and logs only — never authorization) |
| `log_level` | `info` | Log level (`debug`/`info`/`warning`/`error`) |
| `tool_families_disabled` | `[]` | Tool families Hermes does not register, so the client loads fewer tools: `services`, `automations`, `helpers`, `events`, `data`, `registries`, `diagnostics`, `config_entries`, `filesystem`, `supervisor`, `backups`, `lovelace`, `marketplace`, `generic_commands`, `system_diagnostics`, `system_status`, `recorder`, `core_diagnostics`, `integration_flows`, `repair_flows`, `mounts`, `system_updates`, `app_store`, `blueprints`, `automation_assist`, `energy`, `system_control`, `resolution_fixes` and `marketplace_manage`. `base` (`ping` and `hermes_guide`) cannot be switched off. An unknown name, or `base`, stops the app from starting and the log names the wrong value and the valid ones |
| `log_redact_network` | `true` | Replaces your `public_hostname`, the hosts of Home Assistant's `external_url` and `internal_url`, any `*.ts.net` name and every non-loopback IP (also when written as `ip-a-b-c-d`) in the log with placeholders, so you can paste it when asking for help. Turn it off only to debug networking: the log says so with `log_network_redaction_disabled`. Secrets are always redacted |
| `oauth_cimd_enabled` | `true` | Accepts clients that identify themselves with a metadata URL (CIMD), such as Claude Code. Turn it off only if a client fails with CIMD: dynamic registration (DCR) keeps working the same |
| `oauth_cimd_allowed_hosts` | `[]` | Hosts whose CIMD documents Hermes accepts (e.g. `claude.ai`, where Claude Code publishes its own). Empty means **any public host**: every download leaves from your home IP towards a host that anyone can pick without the password. List only the hosts you use; see `SECURITY.md` |
| `safety_backup_enabled` | `false` | Automatic **full** HAOS backup before writing to `/config`. Off by default (it produces several GB). The per-file backup always happens. If the backup fails, or Hermes cannot tell whether it finished, the write is not made (`safety_backup_job_failed`, `safety_backup_state_unknown`) |
| `mcp_max_requests_per_minute` | `120` | Global post-auth rate limit |
| `mcp_preauth_max_requests_per_minute_per_ip` | `20` | Pre-auth per-IP rate limit. Applies to the public surface (OAuth and discovery), and the same value caps per IP the requests to protected routes that carry a missing or invalid token. Valid requests are governed by `mcp_max_requests_per_minute` |
| `response_max_bytes` | `131072` | Response cap for every tool (128 KiB); above it the answer is cut and flagged with `truncated: true`. Effective maximum `524288` (512 KiB): a larger saved value is clamped. Raise it up to that if your answers come back truncated |
| `ha_ws_max_msg_size_bytes` | `16777216` | WS message cap towards HA (16 MiB). A larger result closes the whole WebSocket, not just that call, and logs `ha_ws_message_too_big`. A saved `4194304` (the previous default) is treated as not customised and becomes 16 MiB |
| `max_request_body_bytes` | `4194304` | Body cap for an authenticated HTTP request (4 MB). The public OAuth endpoints have their own fixed 64 KiB cap, independent of this option |
| `max_concurrent_requests` | `64` | Simultaneous requests the server accepts. Bounds the maximum in-flight memory (`max_concurrent_requests × max_request_body_bytes`). Claude fires bursts of ~24 calls, so 64 leaves headroom |
| `wait_for_event_max_seconds` | `90` | Maximum timeout allowed for `ha_wait_for_event` (10–220; a saved value above 220 is clamped) |
| `wait_for_event_max_concurrent` | `5` | Maximum simultaneous `ha_wait_for_event` calls (1–20) |
| `safety_backup_keep` | `3` | Retention of the automatic safety backups (0–50). After each successful one, Hermes keeps this many most recent and deletes the rest, at most 5 at a time. A safety backup that finished with errors in its sub-jobs (an app that could not be saved) is incomplete: it does not count among those kept and is deleted first. It only deletes backups it recorded itself when creating them: never one of yours, even if it is called `hermes-safety-…`, nor a password-protected or partial one, or one copied to another location. `0` turns it off. It only applies with `safety_backup_enabled` |
| `safety_backup_window_minutes` | `30` | If Hermes made its own safety backup more recently than this, another one is skipped. Backups made by hand or by other tools do not count. While the backup runs, the write waits up to 5 minutes, and it is cancelled if the backup fails |
| `file_backup_max_per_path` | `20` | Copies kept of each file before overwriting it |
| `file_backup_max_total_mb` | `200` | Total cap for the per-file backup directory |
| `config_write_min_interval_seconds` | `5` | Minimum seconds between two writes to `/config` |
| `config_write_max_per_minute` | `10` | Maximum writes per minute to `/config` |
| `health_startup_grace_seconds` | `120` | Startup grace **per boot step**, not total: steps 4 (Tailscale), 6 (`/core/info`) and 8 (HA WebSocket) may each use the full budget |
| `health_reconnect_tolerance_seconds` | `300` | How long the WebSocket to HA may stay down before `/health` reports `degraded_long` instead of `degraded`. It never returns 503: a restart does not help with a Core outage, and the reconnect loop recovers on its own |

> [!NOTE]
> **If you had saved values.** The add-on UI stores the default even if you
> never touched it, so a `response_max_bytes` of `1048576` (the old 1 MiB
> default) is treated as untouched and becomes `131072`. A value above
> `524288`, or a `wait_for_event_max_seconds` above `220`, is clamped to the
> maximum. The add-on starts anyway and logs `config_legacy_default_replaced`
> or `config_value_clamped` with the saved and the applied value. These limits
> match what Claude's clients accept.

### Security levers

These change **what Claude can do without asking you**. Worth reading:

| Option | Default | Description |
|--------|---------|-------------|
| `call_service_denylist_extra` | `[]` | Additional services that will require explicit confirmation, on top of the ~70 Hermes already ships. Format `domain.service`, wildcards allowed (`shell_command.*`) |
| `call_service_restricted_entities` | `[]` | Specific entities that will require confirmation even when the service is not denylisted. Useful for `script.open_garage` and friends |
| `fire_event_allowlist` | `[]` | Event types `ha_fire_event` is allowed to fire. Empty means the tool is disabled: every permitted event must be named explicitly |
| `call_service_auto_classify_dangerous` | `true` | On startup and after a scripts or automations reload made through Hermes, Hermes reads your scripts and automations and automatically marks as restricted the ones invoking dangerous services (the built-in list plus `call_service_denylist_extra`). Disabling it stops only those two scans: scripts and automations saved through Hermes (`ha_create_or_update_script`, `ha_create_or_update_automation`) are always checked and restricted if dangerous, even with this option off |

See `config.yaml` for the full schema with valid ranges.

## Security

- **OAuth 2.1 with mandatory PKCE** (no static bearer): opaque tokens stored
  hashed (SHA-256), single-use auth codes, revocation (RFC 7009).
- **Strong password enforced**: `auth_password` ≥ 12 characters, quality filter,
  plus exponential-backoff throttling on failed attempts (anti-brute-force).
- **Hardened DCR**: `redirect_uris` validation and a client cap.
- **Confirmation tokens** for every destructive action.
- **Generic tools governed by a fail-closed table**: `ha_read_ws_command`,
  `ha_call_ws_command`, `sv_read_api` and `sv_call_api` run only the commands
  and routes Hermes' command table allows; anything else, the Supervisor's Core
  proxy and any route aimed at Hermes itself are refused before reaching Home
  Assistant. Writes always go through a preview and a token.
- **`/config` filesystem**: anti-traversal, secret blacklist, *default-deny*
  allowlist under `.storage/`, *managed paths*, backup before every write.
- **Anti path-injection validation** of identifiers (slug, `entry_id`…) plus a
  central guard in the HA client.
- **Security headers** (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, CSP) and a body size limit (`chunked` included).
- **Secret redaction** across all logs.
- **Network redaction** in the log (`log_redact_network`, on by default): your
  hostname and IPs are replaced with placeholders, so the log can be shared.
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
- **Supervisor suggestions are applied only with a preview and confirmation.**
  Up to 1.1.x Hermes never applied them. Since 1.2.0
  `sv_apply_resolution_suggestion` does, but only after a preview that says
  what the fix does (some delete an app or old full backups, or reboot the
  host) and with a confirmation token tied to the suggestion and to the
  automatic fixes the Supervisor would apply on the way. It refuses, without
  a token, suggestions with no fix, that it cannot explain, that touch the
  data disks or that act on Hermes itself. Switch off the `resolution_fixes`
  family if you do not want this at all.
- **Safety backups are not encrypted.** They are full HAOS backups without a
  password. For an encrypted one, use `sv_create_backup_full` with `password`.
- **Safety backups made before 1.1.0 are not pruned.** Hermes did not record
  them, so retention cannot tell them apart from yours: delete them with
  `sv_delete_backup` if you no longer need them.

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

- `ha apps rebuild local_hermes` after any change, Python included: the code is
  copied into the image, so a plain restart keeps running the old one
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
