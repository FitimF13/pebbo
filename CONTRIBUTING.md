# Contributing to Pebbo

Thank you for helping. Pebbo is a local-first desk assistant, so privacy and reliability come before features.

## Before you start

- Read the [vision](docs/vision.md), [architecture](docs/architecture.md) and [decisions](docs/decisions.md).
- For larger changes, open an issue first and describe the problem and your proposal.
- Follow the [development guide](docs/development.md) for setup and checks.

## Rules for changes

- **Local first.** Code must not contact hosts outside the local network unless the owner enables the feature. Document every external host a feature may contact.
- **No real personal data.** Use synthetic people, devices, voices and data in code, tests, screenshots and issues. Never commit credentials, recordings or voice fingerprints.
- **Tests stay offline.** The network guard must pass. Use local fakes for external services.
- **Dependencies.** Prefer Apache-2.0, MIT or BSD licences, do not bundle GPL code, and only add versions that have been public for at least 7 days. Explain why a new dependency is needed.
- **Documentation.** Update the documentation in English with every change to behaviour, setup or decisions. New decisions go into `docs/decisions.md`.
- **Permissions.** Check people, permissions and approvals in the service that executes an action.

## Pull requests

1. Create a branch from `main`.
2. Keep each pull request focused on one change.
3. Run all checks from the development guide.
4. Describe what changed, why, and how you tested it.

## Developer Certificate of Origin

Contributions are accepted under the [Developer Certificate of Origin](https://developercertificate.org/). Sign off every commit to confirm that you have the right to submit it:

```sh
git commit -s -m "Describe the change"
```

## Licences

By contributing, you agree that your contribution is licensed under the licence of the part you change:

| Part | Licence |
| --- | --- |
| Code | [Apache-2.0](LICENSE) |
| Hardware designs in `hardware/` | [CERN-OHL-P v2](hardware/LICENSE) |
| Documentation in `docs/` and artwork | [CC BY 4.0](docs/LICENSE) |

## Conduct

Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).
