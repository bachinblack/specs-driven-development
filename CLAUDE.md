# Specs-driven project

Business rules: `docs/business/` (one file per feature, `<PREFIX>-<name>.md`, one rule per line, tags like XX-NNN).
Technical docs: `docs/technical/` (stack, dependencies, database).
Details: `docs/specs-driven-development.md` (conventions), `docs/project-flow.md` (process).

## Find things, don't explore blindly
- `tag-ls`: list features. `tag-ls <PREFIX>`: rules of a feature. `tag-ls --todo`: rules to implement.
- `tag-lookup <TAG>`: rule, code, tests, rules mentioning it. `tag-lookup <PREFIX>`: coverage summary.
- `tag-check`: run before every commit.

## Conventions
- Reference rules as `@XX-NNN` in docs, code and tests. Tag existing tests of any layer, no separate business test directory.
- Markers: `[draft]` = not validated, don't implement. `[to-do]` = validated, not implemented. None = done.
- Never rename or reuse a tag. Increment `next_tag` when adding a rule.

## Rules of work
- A tag is an entry point, not a perimeter: check callers and callees of what you change, run the impacted tests, then the full suite.
- Any behaviour change = rule change, committed with code and tests. Never turn `[draft]` into `[to-do]` without the product owner's validation.
- Commit messages start with the tag(s): `XX-NNN: ...`.
- Database: write the migration only. The DDL export and the Mermaid diagram are generated.
- Before updating a rule, fixing a bug or starting a feature, read the matching section of `docs/project-flow.md`.
