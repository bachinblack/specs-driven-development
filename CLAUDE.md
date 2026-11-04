# Specs-driven project

Business rules: `docs/business/` (one file per feature, `<PREFIX>-<name>.md`, one rule per line, tags like XX-NNN).
Attachments (diagrams, workflows): `docs/business/attachments/<PREFIX>-<name>.md`, referenced by path from the feature, referencing rules with `@XX-NNN`. They illustrate rules, never replace them; code and tests don't reference them.
Glossary: `docs/business/glossary.md`, one term per line (`- Term, Synonym, ...: definition.`). Use the first term in rules, code and tests, synonyms only help to understand requests; a definition is not a rule.
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
