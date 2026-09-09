# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/antnardo/liveboxapi/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/antnardo/liveboxapi/releases/tag/v0.1.0
