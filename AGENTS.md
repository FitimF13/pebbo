# Pebbo agent rules

- Read the [vision](docs/vision.md), [architecture](docs/architecture.md), [decisions](docs/decisions.md) and [roadmap](docs/roadmap.md) before changing behaviour. Record new decisions in `docs/decisions.md`.
- Keep repository documentation, code comments and commit messages in English. Update the documentation together with every change to behaviour, setup or decisions.
- Verify every change with the checks in [docs/development.md](docs/development.md): `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` and `uv run pytest` in `core/`, and `pnpm typecheck`, `pnpm test` and `pnpm build` at the root.
- Local first: no code may contact a host outside the local network unless the owner enabled the feature and the host is documented. Audit every new dependency, model and tool for telemetry, geo-IP, weather or cloud defaults before use, and disable them.
- Tests must pass with the network guard active. Never weaken or bypass it.
- Only add dependencies that have been public for at least 7 days (enforced by `minimumReleaseAge` in pnpm and `exclude-newer` in uv). Prefer Apache-2.0, MIT or BSD licences. Do not bundle GPL code.
- Keep credentials, recordings, voice fingerprints and real household or business data out of the repository, model context and logs. Use synthetic people, devices and data in tests and demos.
- Check people, permissions and approvals in the service that executes an action, never only in the client.

## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues of `FitimF13/pebbo`, used through the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The canonical roles map to `needs-triage`, `needs-info`, `agent:ready`, `needs-human` and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one root `GLOSSARY.md`, and decisions in `docs/decisions.md` instead of `docs/adr/`. See `docs/agents/domain.md`.
