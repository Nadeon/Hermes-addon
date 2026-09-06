# Contributing to Hermes

> Read this in: [English](CONTRIBUTING.md) | [Español](CONTRIBUTING.es.md)

Thanks for being here. Hermes hands a language model administrator-level control
over someone's home, so contributions are read with that in mind: the bar is less
about style and more about *what happens when this is wrong*.

By opening a pull request you agree that your contribution is published under the
project's license, [PolyForm Noncommercial 1.0.0](LICENSE). Participation is
governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

**Never report a security flaw through an issue or a pull request.** Use the
[private advisory form](../../security/advisories/new); see
[SECURITY.md](SECURITY.md).

---

## Before you write code

Two things about this codebase that are not obvious from the outside:

- **Comments, docstrings and startup error messages are written in Spanish.**
  Identifiers, tool names, log event names and the MCP-facing tool descriptions
  are in English. Keep new code consistent with the file you are editing rather
  than converting it; a pull request that translates existing comments will be
  asked to drop that part, because it buries the actual change in noise.
- **The project has a written constitution**: [docs/PRINCIPIOS.md](docs/PRINCIPIOS.md)
  *(Spanish)*. When a design question comes up in review, that document is what
  settles it. Reading the first two principles is enough to understand most
  review comments.

For anything larger than a bug fix, open an issue first and describe the
approach. It is cheaper to redirect a plan than a finished branch.

## Reporting an issue

Open a [new issue](../../issues/new). What makes a report actionable:

- **The Hermes version** (Settings → Add-ons → Hermes, or the `version:` field in
  `hermes/config.yaml`).
- **`network_mode`** and how you expose Hermes (Tailscale Funnel, Cloudflare
  Tunnel, classic reverse proxy).
- **The Home Assistant version** and whether you run HAOS or Supervised.
- **The relevant log lines**, including the `hermes_started` line from startup.
  Set `log_level: debug` if the default level does not show the failure.
- **The `X-Request-ID`** from the failing response, if you have it. It ties the
  request to its log lines.

> [!CAUTION]
> Logs redact known secrets, but redaction is not a guarantee for values Hermes
> has never seen. Read what you paste before you paste it, especially anything
> around `secrets.yaml`, tokens, or hostnames you would rather not publish.

If the report is about a tool doing the wrong thing, include the tool name and
the arguments Claude used. Both appear in the log.

## Development setup

The suite runs with no Home Assistant in front and nothing deployed:

```bash
python -m venv .venv
.venv/bin/pip install -r hermes/requirements.txt
.venv/bin/pip install pytest pytest-asyncio aioresponses httpx
.venv/bin/pytest
```

On Windows, `.venv\Scripts\` instead of `.venv/bin/`.

`pytest.ini` sets the import paths, so `PYTHONPATH` does not need exporting, and
`pytest` and `python -m pytest` behave identically. Test dependencies are
deliberately not in `hermes/requirements.txt`: that file is what the add-on needs
to **run**, and it ends up in the image.

**Layout**: the repository root is a Home Assistant add-on repository
(`repository.yaml`); the add-on lives entirely in `hermes/`, the Python package
under `hermes/src/hermes/`, and the tests in `tests/` at the root.

To try changes against a real Home Assistant, copy the contents of `hermes/` to
`/addons/hermes` on the host and **delete the `image:` line** from the
`config.yaml` you leave there — otherwise the Supervisor downloads the published
image instead of building your changes. Then `ha apps rebuild local_hermes`
(after touching the `Dockerfile` or dependencies), `ha apps restart local_hermes`
(Python only), and `ha apps logs local_hermes -f`.

## The three conventions that matter

Almost every review comment on this project comes back to one of these.

### 1. A security fix ships with a test that fails without the fix

A regression test that passes whether or not the guard is in place protects
nothing. Before opening the pull request, undo your fix, run the suite, and check
that your test actually goes red. Say so in the PR description — "with the guard
removed, N tests fail" — because that sentence is what a reviewer would otherwise
have to reproduce by hand.

This applies to the tests themselves: several tests in this repository were found
to be asserting the old, weak behaviour rather than the correct one.

### 2. Tool docstrings are the contract, not decoration

The docstring of an MCP tool is what Claude reads to decide whether to call it. A
docstring that overstates what a tool does, or omits that it is destructive, is a
bug even when the code is perfect — it will cause the wrong tool to be called on
someone's house.

If you change what a tool does, change its docstring and its `ToolAnnotations`
(`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) in the same
commit.

### 3. Secrets never reach a log, an error message or a return value

Everything Hermes can touch — its own password, another add-on's, an
integration's — is treated as if it will end up in a log, in a model's context
and in a transcript, because that is exactly what happens. Error messages
describe the rule that failed, never the value that failed it.

## Pull requests

1. **Branch from `main`** with a descriptive name: `fix/…`, `feat/…`, `docs/…`,
   `test/…`.
2. **Keep it to one subject.** A PR that fixes a bug and reformats four files
   cannot be reviewed properly, and cannot be reverted cleanly either.
3. **Write the *why* in the commit message.** What changed is visible in the
   diff; why it had to change is not, and that is what a reader six months from
   now needs. Include the measurement if the change is based on one.
4. **Run the full suite before pushing.** CI runs it on Python 3.12 and 3.13, and
   the Linux-only tests — symlink-escape checks that depend on `O_NOFOLLOW` —
   are skipped on Windows, so CI covers paths your machine may not.
5. **CI must be green.** Two required checks: `Tests` and `SAST (Semgrep)`
   (`CodeQL` joins them on the public repository, where it is free).
   Semgrep runs in blocking mode; if it flags a line you have reviewed and
   consider a false positive, suppress it with `# nosemgrep` on the exact line
   plus one line of justification, not by weakening the rule.
6. **Update the docs in the same PR** when behaviour changes: `README.md` and
   `README.es.md`, `hermes/DOCS.md` if it affects installation or configuration,
   and an entry in `hermes/CHANGELOG.md`.

Both READMEs are kept in sync. If you only speak one of the two languages, change
that one and say so in the PR description — a maintainer will handle the other
side rather than let the change wait.

### Version bumps

`hermes/config.yaml` carries the add-on version, and the image-publishing
workflow refuses to run when a `v*.*.*` tag does not match it. Bumping the
version is a release decision: leave it to a maintainer unless your PR is the
release.

## Review

Expect questions about failure modes rather than about style. There is no
formatter gate; match the file you are editing.

A pull request may be asked to shrink. That is not a rejection of the work — it
usually means two good changes are fighting for one review, and they will both go
in faster apart.

## Questions

For anything that is not an issue or a pull request, write to `nadeon@gmail.com`.
Security reports do **not** go there; they go to the
[private advisory form](../../security/advisories/new).
