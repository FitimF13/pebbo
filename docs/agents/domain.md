# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

This repo is **single-context**: one `GLOSSARY.md` at the repo root for all of Pebbo (`core/`, `apps/`, `packages/`, `hardware/`). Pebbo is one product, so the pnpm workspaces do not get their own glossaries.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root.
- **`docs/decisions.md`**: the numbered decision log. Read the decisions that touch the area you're about to work in.
- **`docs/vision.md`**, **`docs/architecture.md`** and **`docs/roadmap.md`**, as `AGENTS.md` requires.

If `GLOSSARY.md` doesn't exist yet, **proceed silently**. Don't flag its absence; don't suggest creating it upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates it lazily when terms actually get resolved.

## Decisions instead of ADRs

This repo has no `docs/adr/` directory. Wherever a skill says "ADR", use `docs/decisions.md`:

- **Read an ADR**: read the row in the decision table, referred to as "decision 42".
- **Record an ADR**: append a new numbered row to the table (Topic, Decision, Why, Rejected alternatives). Keep it as short as an ADR would be.
- **Supersede an ADR**: a decision changes only by adding a new row that replaces the old one. Mark the old row, as existing rows do with "(replaced by #N)".

Do not create `docs/adr/`.

## File structure

```
/
├── GLOSSARY.md
├── docs/decisions.md
├── core/
├── apps/
├── packages/
└── hardware/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag decision conflicts

If your output contradicts an existing decision, surface it explicitly rather than silently overriding:

> _Contradicts decision 23 (rejected base projects), but worth reopening because…_
