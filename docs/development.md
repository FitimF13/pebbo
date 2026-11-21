# Development

## Repository layout

| Path | Content |
| --- | --- |
| `core/` | Core service in Python: FastAPI, the Pipecat voice pipeline, the network guard and `tools/e2e_voice.py` |
| `apps/web/` | PC app with face and voice client, and web settings (React, Vite) |
| `apps/mobile/` | Native iOS and Android app (Expo, React Native), see [phone app](phone.md) |
| `packages/contracts/` | TypeScript types for the core's API, shared by the apps |
| `hardware/` | Bill of materials, CAD sources and print files, from phase 7 |
| `docs/` | Project documentation |

## Requirements

- [uv](https://docs.astral.sh/uv/) for Python. It installs the right Python version (3.12 or 3.13) itself.
- Node.js 22.13 or newer with Corepack, which provides the pinned pnpm version.

## Setup

```sh
corepack enable        # once, provides pnpm from package.json
pnpm install
cd core && uv sync
```

## Checks

Run all checks before every commit with `pnpm check` at the repository root. Continuous integration runs the same commands.

While the repository is private and has no GitHub Actions budget, CI jobs do not start. Until then, `pnpm check` must pass locally before every push.

```sh
# Core
cd core
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest

# Apps and packages (repository root)
pnpm typecheck
pnpm test
pnpm build
```

## Run locally

See [running Pebbo](running.md) for the voice setup. Without the voice pipeline:

```sh
cd core && uv run uvicorn pebbo.app:create_app --factory --host 127.0.0.1 --port 8100   # health endpoint only
pnpm --filter @pebbo/web dev     # PC app on http://localhost:5173, proxies /api to the core
```

The core deliberately does not use `fastapi[standard]`, because that extra pulls in a cloud deployment CLI.

## Network guard

Tests may only reach loopback addresses. Any other connection fails immediately:

- **Python:** `pytest-socket` with `--allow-hosts=127.0.0.1,::1` (configured in `core/pyproject.toml`). On Windows, asyncio connects and sends datagrams through the IOCP proactor, which pytest-socket does not see, so `core/tests/conftest.py` limits the proactor to loopback as well.
- **TypeScript:** `apps/web/src/test/network-guard.ts` wraps `fetch`, `WebSocket` and Node sockets. The phone app's tests use the same guard.

Each guard has its own test that proves an external connection is rejected.

The running core has its own guard as well (`core/src/pebbo/netguard.py`): it blocks TCP connections and UDP datagrams to public addresses unless a host is explicitly allowed, including those asyncio makes through the Windows IOCP proactor, and `pebbo.runtime` switches off the telemetry of ONNX Runtime and Hugging Face before those libraries load. Never weaken or bypass the guard. If a feature needs an external service, test it against a local fake.

Known gap: on Windows, asyncio's default Proactor event loop opens TCP connections through `ConnectEx` and sends datagrams through the proactor, which bypasses `socket.socket.connect` and `sendto`. Neither `pytest-socket` nor the runtime guard sees those connections. Code that connects with asyncio must check addresses itself (as `pebbo.tools.mcp` does), and tests must never point asyncio clients at public addresses, not even with the guards active.

## Dependency safety

- Only versions that have been public for at least 7 days are installed: `minimumReleaseAge` in `pnpm-workspace.yaml` and `exclude-newer` in `core/pyproject.toml`.
- pnpm does not run install scripts of dependencies unless they are explicitly allowed.
- Lock files (`pnpm-lock.yaml`, `core/uv.lock`) are committed. Dependabot proposes updates with the same 7-day cooldown.
- `core/uv.lock` must resolve for both Windows and Linux on x86-64 (`required-environments` in `core/pyproject.toml`), because the CI runs only on Linux. An update that ships wheels for one of them only fails to lock.
- Check the licence and the outbound behaviour of every new dependency before adding it.

## Agent skills

Skills for coding agents live in `.agents/skills/<name>/` (read by Codex). `.claude/skills/<name>` is a symlink to each of them (read by Claude Code). The skills in there are Matt Pocock's engineering and productivity skills (MIT, see `.agents/skills/LICENSE-mattpocock-skills`), copied from [mattpocock/skills](https://github.com/mattpocock/skills) at commit `abeeaf9` (version 1.3.2) without running its installer. Update them by copying a newer version over them.

The repository configuration the skills read (issue tracker, triage labels, glossary and decision layout) is in [`docs/agents/`](agents/), summarised in the `## Agent skills` section of `AGENTS.md`.

- On Windows without Developer Mode, git checks the symlinks out as small text files. Replace each with a directory junction, which needs no extra rights, and keep git from reporting it:

  ```powershell
  Get-ChildItem .agents\skills -Directory | ForEach-Object { Remove-Item ".claude\skills\$($_.Name)" -ErrorAction SilentlyContinue; cmd /c mklink /J ".claude\skills\$($_.Name)" $_.FullName }
  git ls-files .claude/skills | ForEach-Object { git update-index --skip-worktree $_ }
  Add-Content .git\info\exclude "/.claude/skills/*/*"
  ```

- `code-review` has the same name as a skill built into Claude Code; inside this repository the project skill is used.
- The HTML report of `improve-codebase-architecture` loads Tailwind and Mermaid from public CDNs when opened in a browser. It is a development aid, not part of Pebbo.

