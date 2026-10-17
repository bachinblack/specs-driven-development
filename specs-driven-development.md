# Agentic Specs Driven Development (SDD)

The goal of this doc is to explain how a project can be developed by an AI agent, from the specs to the code.
It is centered around the `docs/` directory, which contains both the business rules and the technical architecture, and keeps the relations between business docs, technical docs, code and tests as clear as possible.

What we want from it:
- **Productivity**: the agent finds what it needs without exploring blindly.
- **Lower token cost**: lookups instead of reading whole files or directories.
- **Traceability**: from a rule to its code and tests, and back.
- **Safety**: regressions are caught by tests, not by luck.

The development process itself (new project, updating a rule, bug fix) is described in `project-flow.md`. This doc describes the conventions and the tools.

## Principles

- A tag is an **entry point, not a perimeter**. It tells the agent where to start. The agent still has to follow the callers and callees of what it modifies, and the tests are the safety net against regressions.
- Lookups and checks are done by scripts (cheap and deterministic). We don't rely on an agent to notice inconsistencies.
- No redundancy: whatever can be generated (feature list, reverse links) is generated, not written by hand.

## Entry point for agents

A short `CLAUDE.md` / `AGENTS.md` at the root of the project contains the conventions (prefix, tag, `@` syntax), the scripts (`tag-ls`, `tag-lookup`, `tag-check`), a summary of the workflow and a pointer to `docs/`.
It points to the docs, it doesn't copy them.

## Specs (rules)

The specs are stored in `docs/business/`, one file per feature, named after its prefix: `docs/business/PL-pokemon-list.md`.
Finding the file of a feature from its prefix is then just `ls docs/business/PL-*`.

Each feature has a prefix (ex.: PL) and each rule has a tag (ex.: PL-001).
The meaning of the tag is not that important, but:
- tags must be unique across `docs/business/`;
- tags must be **stable**: a tag is never renamed, and never reused once its rule is deleted or split.

### Feature file format

```
---
prefix: PL
description: Pokemon list: ordering, filtering, pagination
next_tag: 8
---

# Pokemon list

- PL-001: The list contains 5 elements per page.
- PL-003: By default the list is ordered by id.
- PL-004: The list can be ordered by name, type or level.
- PL-005: The list can be ordered by several criteria, applied in the given order.
- PL-006 [to-do]: The list can be filtered by type.
- PL-007 [draft]: A pokemon can be added to favorites from the list.
```

- **One rule per line**, so a lookup can output a whole rule on a single line.
- `description` is the one-liner shown by `tag-ls`.
- `next_tag` is the number to use for the next new rule. It is incremented every time a rule is added, so a deleted number is never reused.
- A rule has at most one marker, which gives its status:
  - `[draft]`: not validated by the product owner yet. Agents don't implement it.
  - `[to-do]`: validated by the product owner, not implemented yet. This is what agents pick their work from.
  - no marker: validated and implemented (code and tagged tests exist).
- A rule goes `[draft]` → `[to-do]` when the product owner validates it, then loses its marker in the commit that brings its code and tests.

### Granularity

One rule = one testable assertion.
"The list can be ordered by id (default), name, type, level" is too coarse: it mixes a default and several criteria, and the tests quickly go beyond it (ordering by name *and* level). Split it, as in the example above.

### Referencing a rule

Rules are referenced with `@PL-001`, in docs, code and tests.

#### docs

A rule or feature can reference another, for instance a button leading to another page: `@PL-001`.
When a rule is modified, the rules that reference it must be checked (they appear in `tag-lookup`).

#### code

Each component of the code should either have:
- a prefix, corresponding to a feature (files, classes: entities, pages), ex.: `@PL`;
- one or more tags, corresponding to rules (methods, properties, utils), ex.: `@PL-003 @PL-004`.

Either can be followed by a short description of how it is linked to the rule or feature.
A method that implements several rules lists them all. A shared utility lists every rule it serves, and is a risk zone when modified: all its callers must be checked.

```php
/** @PL-003 @PL-004 Orders the list from the requested criteria */
public function order(array $criteria): array
```

#### tests

Business rules are **not a new test layer**: there is no `tests/business/` directory.
We keep the usual layers (unit, functional, integration) and tag the existing tests that prove a rule.

- Tag a rule at the lowest level that really verifies it:
  - pure logic (ordering, computation, validation) → unit;
  - behaviour visible from outside (API route, Symfony command) → functional. This is the best protection against regressions, since it survives refactoring;
  - persistence or external services → integration.
- Each rule must have **at least one tagged test**, in any layer.
- Tests that don't prove a rule (technical edge cases, technical error handling) stay untagged. They still run in the full suite, so they still protect against regressions. The tag is for traceability, not to choose what to run.
- A test can carry several tags, but a test carrying many is probably too broad.
- If an existing test already proves the rule, add the tag to it (and rename it if its name doesn't say what is tested about the rule) instead of writing a duplicate.
- Use the test framework's native mechanism when there is one, so the runner can filter by rule. The name of the test should convey what is tested about the rule.

```php
#[Group('PL-003')]
public function testListIsOrderedByIdByDefault()
```

The scripts match tags with word boundaries and only for prefixes declared in the feature files, so `PL-003` is found with or without the `@` (ex.: in a `Group` attribute), and strings like `SHA-256` are never mistaken for tags.

Tests are recognised by their path: a `tests/`, `test/`, `__tests__/` or `spec/` directory, or a file named `*.test.*`, `*.spec.*` or `*Test.*`. Their layer is deduced from a `unit/`, `functional/`, `integration/` or `e2e/` directory in the path (plain `test` if there is none), so organise the tests by layer.

### Finding a rule

#### From a description

An agent shouldn't need to read the code.
`tag-ls` lists the features with their description, then `tag-ls <prefix>` lists the rules of the matching feature (or the agent opens the feature file directly, since its name starts with the prefix).

#### From a tag

The agent uses `tag-lookup` to get everything related to a tag.

### Scripts

Scripts are small and have compact outputs (forward slashes, one line per result, no explanatory text) to keep the token cost low.

Common behaviour:
- They look for `docs/business` from the current directory upwards: the closest parent containing it is the project root, and the printed paths are relative to it. `TAG_DOCS_DIR` overrides the location of the feature files.
- They only need bash, awk and grep. `tag-lookup` uses `git grep` inside a git repository (so `.gitignore` is respected and new untracked files are found). Otherwise it uses `grep -r`, which skips `.git`, `node_modules`, `vendor`, `var`, `dist`, `build`, `coverage`, `.next`, `target` and `docs`.
- A script must be saved with LF line endings, a CRLF script breaks bash (ex.: `tag-ls text eol=lf` in `.gitattributes`).

#### tag-ls (reads the docs only)

`tag-ls` opens the feature files and dumps their description. There is no hand-written index to keep in sync.

```
> tag-ls
PL  docs/business/PL-pokemon-list.md  Pokemon list: ordering, filtering, pagination (6 rules, 1 draft, 1 to-do)
...

> tag-ls PL
PL-001  The list contains 5 elements per page.
PL-003  By default the list is ordered by id.
...
PL-006  [to-do] The list can be filtered by type.
PL-007  [draft] A pokemon can be added to favorites from the list.
```

`tag-ls --todo [prefix]` lists the `[to-do]` rules of all the features (or of one): this is where an agent picks the next rules to implement. `tag-ls --draft [prefix]` lists the `[draft]` rules, the ones still waiting for the product owner's validation.

A file without front matter (a README, for instance) is ignored, a front matter without `prefix` gives a warning on stderr, and an unknown prefix is an error that lists the known ones.

#### tag-lookup (scans docs, code and tests)

`tag-lookup <tag> [dir]` searches the code and the tests from the project root, or only under `dir` when given. Example for PL-003:

```
> tag-lookup PL-003
PL-003 (feature PL)
docs             docs/business/PL-pokemon-list.md:10  By default the list is ordered by id.
docs:ref         docs/business/PF-favorites.md:7  PF-001: A favorite pokemon appears first, then the order of @PL-003 applies.
code             src/Service/PokemonOrder.php:7 PokemonOrder::order  @PL-004 Orders the list from the requested criteria
code             src/util/pokemon-order-filter.js:1 orderPokemons  Orders a list of pokemons depending on arguments.
test:functional  tests/functional/PokemonListControllerTest.php:4 PokemonListControllerTest::testListRouteReturnsOrderedList
test:unit        tests/unit/PokemonOrderTest.php:4 PokemonOrderTest::testListIsOrderedByIdByDefault
test:unit        tests/unit/order.test.js:2 "orders by id by default"
```

- The header gives the tag and its feature prefix once. The tag isn't repeated on each line.
- The match is exact, with word boundaries (`PL-003` doesn't match `PL-0031`).
- The `docs` line is the rule itself, with its marker if it has one. A tag that is used but not defined shows `docs  (not defined in docs/business)`.
- `docs:ref` lines are the other lines of `docs/business` and `docs/technical` that mention the tag, with their text. Other rules mentioning the tag are the declared dependencies of the rule. Other files under `docs/` (like this one) are not scanned.
- Components tagged only at the feature level (`@PL`) are not listed by default. `--feature` adds them as `feature` lines.
- For code, the output gives the enclosing symbol (`Class::method`, a function, a class, or the `"title"` of a JS test) so the agent doesn't need to open the file to know what it is. Line numbers move, the symbol name is more stable.
- The symbol is found with simple heuristics (PHP, JS/TS, Python, Java, C#): a docblock or an annotation right above a declaration belongs to that declaration, a comment inside a body belongs to the enclosing function. It is best-effort: when no symbol is found, only `path:line` is shown. `universal-ctags` or tree-sitter could replace the heuristics later.
- The text after a code line is the comment carrying the tag, without the tag. Other tags on the same line are kept: they tell which other rules this code serves. Test lines have no text, their name says what they test.
- The kind of test (`unit`, `functional`, `integration`) is deduced from its path.
- When a rule has no code or no test, the output says so (`code  (none)`, `test  (none)`), which makes the gap visible, especially for a `[to-do]` rule.
- The tag must belong to a declared prefix (otherwise the error lists the known prefixes). A tag found nowhere, in docs, code or tests, is an error.

Looking up a prefix gives a coverage summary instead of the full output:

```
> tag-lookup PL
PL  Pokemon list: ordering, filtering, pagination  (docs/business/PL-pokemon-list.md)
PL-001  code:1  tests:1  The list contains 5 elements per page.
PL-003  code:2  tests:3  By default the list is ordered by id.
PL-006  code:0  tests:0  [to-do] The list can be filtered by type.
PL-007  code:0  tests:0  [draft] A pokemon can be added to favorites from the list.
PL-009  code:1  tests:0  (not in docs)
```

`--full` expands each rule as a single-tag lookup would.
Tags of the feature found in the code or the tests but not defined in the docs are listed last, as `(not in docs)`: they are orphans, and `tag-check` fails on them.

#### tag-check (pre-commit and CI)

Prints one line per problem (`error  path:line  message`, or `warn` for a warning), then a summary. The exit code is 1 when there is at least one error and 0 otherwise: warnings never fail the check.

Errors:
- feature files: a missing or invalid `prefix` or `description`, a file name that doesn't start with its prefix, a prefix used by two files, a missing `next_tag` or one that isn't greater than the highest tag of the feature;
- rules: a duplicate tag, a tag with another prefix in a feature file, a line that doesn't follow `- PL-001 [marker]: text`, a marker other than `[draft]` and `[to-do]`;
- a rule without marker that has no reference in the code or no tagged test (`[draft]` and `[to-do]` rules are ignored). These are the blind spots where a regression would pass silently;
- a tag used in the code or tests that doesn't exist in the docs, and a reference to an undefined rule in `docs/business/` or `docs/technical/`;
- an `@XX-001` reference whose prefix isn't declared (only the `@` form can be checked, since a prefix can't be recognised otherwise);
- a path written in backticks in `docs/technical/` that doesn't exist anymore;
- a dependency file without `features:` in its front matter, or listing an unknown prefix.

Warnings:
- a `[to-do]` rule that already has code and tagged tests: the marker is probably stale, and the next agent would implement the rule again;
- a file of `docs/business/` without front matter (it is ignored).

Paths are recognised only in backticks and outside fenced code blocks: a relative path with at least one `/`, no space and no `://`, optionally followed by `::symbol`, `#symbol` or `:line`. It is checked only when its first directory exists or its last part has an extension, so API routes (`v1/pokemon`) and placeholders (`<name>.md`) are ignored.

This is a deterministic check. It is cheaper and more reliable than hoping an agent notices these things while working.

### Updating a rule

Any change of behaviour should update, add or delete one or more rules (preferably one), committed along with the code and test changes.
The detailed steps (impact analysis, tests first, validation, commit) are in `project-flow.md`.
Refactorings and other technical changes don't change a business rule: they update `docs/technical/` only.

## Architecture

The technical specs are stored in `docs/technical/`.

- `stack.md` describes the technical stack (language, framework), the architecture (MVC, ...), the test layers (unit, functional, integration) and the commands to run them.
- `database/schema.sql` is the SQL DDL of the database, **exported after the migrations are applied** and never edited by hand. It is the reference description of the schema, for the docs and the agents.
- `database/schema.md` is a Mermaid `erDiagram` **generated** from the DDL by a script, never edited by hand. It is the readable version for stakeholders and agents.

The only thing written by hand when the database changes is the migration. The chain is migration → DDL export → diagram generation, and the three are committed together. The CI applies the migrations to an empty database, exports the DDL, regenerates the diagram, and fails if either committed file differs.

References from technical docs to the code use a file path and a symbol name, never a line number (they rot quickly). `tag-check` verifies that the paths exist.
Technical docs don't have prefixes or tags.

### Dependencies

Relied upon external services are described under `docs/technical/dependencies/<name>.md`, one file per service:
- what it is used for, which endpoints/features are used;
- authentication, limits (quotas, formats);
- the connector class in the code;
- the **feature prefixes it serves**, in the front matter of the file.

```
---
features: PL, EV
---
```

The link is written in one direction only (dependency → features). The reverse (which dependencies a feature uses) can be derived by a script, to avoid two links getting out of sync. `tag-check` fails on a dependency file without `features:` or with an unknown prefix.
