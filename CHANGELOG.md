# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] — 2026-09-12

Robustness, from a conversation with the LiveboxMonitor maintainer: this
firmware sometimes answers with something that is not JSON, and a client built
from scratch does not inherit the repairs older tooling has accumulated.

### Fixed

- Malformed response bodies no longer escape as `json.JSONDecodeError`. Three
  shapes are repaired in the new `transport` module: an error envelope missing
  its opening brace (`,"errors":[…]`), a list left holding only its separator
  (`[,]`), and two objects concatenated instead of arrayed (`}{`). The first one
  matters most: ten `NeMo.Intf` objects on a Livebox W7 answer that way, and the
  caller now gets the `Permission denied` the box meant to send instead of a
  parse error pointing at the wrong culprit.

  Unlike the repairs this borrows from, the body is parsed **first** and repaired
  only if that fails. A valid document is never rewritten, so a device name or a
  Wi-Fi key containing `}{` cannot be corrupted, and a 200 KB introspection
  answer is not scanned three times for nothing.

- Refusals worded as a top-level `error` code are raised like the ones worded as
  an `errors` list. The box uses both spellings depending on the service, and
  reading only the list meant a family of refusals was returned as success.

- `functions()` and `parameters()` accept an introspection answer that is an
  array of objects rather than a single one — which is what a repaired `}{` body
  becomes.

- Response bytes are decoded with `errors="replace"`. Device names come from
  DHCP requests, so they contain whatever the device sent; one bad byte used to
  take down the whole reading.

### Added

- `identify(url)` reads `DeviceInfo.get` **without signing in** — the one
  service the box serves anonymously. Answers "is there a Livebox here, which
  model, which firmware" before a password is fetched from a password manager,
  and returns `None` rather than raising when nothing Livebox-shaped answers.
  The anonymous record is a subset: model name and hardware version need a
  session.

- `MalformedResponseError`, a `LiveboxError`, so one `except` clause still
  covers every way a call can fail. It carries a truncated excerpt of the
  offending body — bodies reach hundreds of kilobytes, and a whole one could
  carry a Wi-Fi key into a log.

- `verify` on `Livebox` and `LiveboxSession`, for the box's own `https`, whose
  certificate no public authority signed. Off by choice, per session, rather
  than off everywhere: clients talking to this box tend to disable verification
  globally, which also disables it the day one is pointed at a remote host.

### Changed

- `introspect()` is annotated `Any` instead of `dict`. It could already return a
  list; the annotation was wrong.

## [0.1.0] — 2026-09-09

First release.

### Added

- `Livebox`, a session grouped by area: `system`, `network`, `dhcp`, `firewall`,
  `wifi`, `schedule`, `voice`. Anything not wrapped stays reachable through
  `call`, `raw` and `batch`.

- Credential resolution from an explicit argument, the environment, or the
  1Password command line, extensible through `credentials.RESOLVERS`. A router
  client that forces its password into source code is unusable in practice, and
  a config file in the home directory is one `chmod` away from a leak.

- Read-only sessions. Writing to a home gateway is disruptive in ways that are
  hard to undo, so monitoring code can make "look, do not touch" explicit and
  have the client refuse writes before they reach the network.

- Errors raised from in-band failures. The box answers HTTP 200 even when it
  refuses, carrying the reason in the body; code that only checks the status
  believes a write succeeded when nothing happened.

- `batch`, running many calls in one session. Twenty readings one process at a
  time are measured in minutes, the same twenty in one session in seconds.

- Datamodel introspection: `functions`, `parameters` and `introspect` ask the
  box to describe itself, signatures included. Firmware differs between models
  more than documentation admits, so the device is the only reliable reference.

- A `livebox` command for the one-off questions — link state, devices, leases,
  redirections, Wi-Fi, missed calls — which opens a read-only session unless the
  subcommand names a change.

### Known gaps

- Writes are exercised against a recorded transport in the test suite, not
  against hardware in continuous integration. The `integration` marker covers
  the reads; a box on the other end is needed for the rest.
- `wifi.set_security` is implemented from the datamodel signature and the
  behaviour of other clients, and is the one method here not confirmed on real
  hardware. Its payload also carries the network name and key, so prefer the web
  interface unless you are rebuilding a box.

[Unreleased]: https://github.com/antnardo/liveboxapi/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/antnardo/liveboxapi/releases/tag/v0.1.1
[0.1.0]: https://github.com/antnardo/liveboxapi/releases/tag/v0.1.0
