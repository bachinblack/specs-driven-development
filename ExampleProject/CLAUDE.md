# Pokemon app

## Docs

- `docs/business/`: one file per feature, named after its prefix (`PL-pokemon-list.md`). One rule per line: `- PL-001 [marker]: text`.
- `docs/technical/`: `stack.md` (stack, test layers, commands), `database/` (DDL and diagram, generated), `dependencies/` (external services).
- Conventions: `../specs-driven-development.md`. Workflow: `../project-flow.md`.

## Conventions

- A rule is referenced with `@PL-001`, a feature with `@PL`, in docs, code and tests.
- Code: tag the methods with the rules they implement (`/** @PL-008 ... */`), the classes with their feature (`@PL`).
- Tests: tag the test proving a rule with `#[Group('PL-008')]`, at the lowest layer that really verifies it.
- Markers: `[draft]` is not validated, don't implement it. `[to-do]` is validated, implement it. No marker: implemented.
- Tags are never renamed nor reused: a new rule takes `next_tag` from the front matter, which is then incremented.

## Scripts

- `tag-ls [prefix]`, `tag-ls --todo`, `tag-ls --draft`: list the features, the rules, the work to do.
- `tag-lookup <tag>`: docs, code and tests of a rule. `tag-lookup <prefix>`: coverage of a feature.
- `tag-check`: consistency of docs, code and tests. Must pass before each commit.

## Workflow

`[to-do]` rules → tagged tests (red) → code → tests green → remove `[to-do]` → `tag-check` → commit `PL-008: ...`.
Before modifying code, check its callers and the rules referencing the tag (`docs:ref` lines of `tag-lookup`).
