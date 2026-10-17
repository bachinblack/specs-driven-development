# Project flow

This doc describes the process to develop a project with agents. The conventions (prefixes, tags, test tagging) and the scripts (`tag-ls`, `tag-lookup`, `tag-check`) are described in `specs-driven-development.md`.

The flow is not strictly linear: technical choices can send us back to the business docs (see step 3).

# Starting a new project

## 1. Business docs

A project starts with a list of features stored in `docs/business/`, one file per feature named after its prefix (ex.: `PL-pokemon-list.md`).
Each feature first has a prefix and a description of what it does (front matter of its file).
Then a list of business rules is established for each feature, with one tag per rule. Rules are simple and testable (one rule = one assertion).
New rules start as `[draft]`.

## 2. Challenging the docs

Once the first version of the docs is complete, agents, devs and stakeholders read it and point out missing or contradictory rules.

- An agent goes first: it compares the rules inside a feature and between features (starting from `tag-ls`) and reports contradictions, gaps and ambiguities.
- Humans (devs, stakeholders) then review the docs and the agent's report.
- The result is a list of contradictions and open questions, which are resolved by modifying the rules.
- A rule goes from `[draft]` to `[to-do]` when the product owner validates it. Agents only implement `[to-do]` rules (the markers are described in `specs-driven-development.md`). `tag-ls --draft` lists the rules still waiting for validation.

The docs are ready when every feature has a prefix, a description and rules, there is no open question left, and every rule to implement has been validated by the product owner (`[to-do]`).

## 3. Technical

At this point, a technical stack is chosen and stored in `docs/technical/stack.md` (including the test layers and the commands to run them).
All the required dependencies are identified, and their description and docs stored in `docs/technical/dependencies/<name>.md`. Each dependency lists the feature(s) it serves (`features: PL, EV` in its front matter).
The initial database schema is designed as an SQL DDL in `docs/technical/database/schema.sql`, with a Mermaid diagram generated from it in `docs/technical/database/schema.md`, to be readable by stakeholders and AI agents.

Technical choices can invalidate a business rule (API quota, authentication, formats). When that happens, go back to step 1: modify the rule and have it validated again.

## 4. Bootstrap

Once the docs are written, the project and the database are bootstrapped: the initial migration is created from the DDL. From then on, migrations are the only thing written by hand: the DDL is exported after them and the diagram is generated from the DDL (see `specs-driven-development.md`).
The tooling is part of the bootstrap and must exist **before the first feature**:
- `tag-ls`, `tag-lookup` and `tag-check`, with `tag-check` wired in pre-commit and CI;
- the scripts exporting the DDL and generating the Mermaid diagram, with a CI check that the committed DDL and diagram are up to date;
- `CLAUDE.md` / `AGENTS.md` (conventions, scripts, workflow);
- the test configuration for the three layers (unit, functional, integration) with rule tagging supported by the runner;
- a CI running the full test suite.

## 5. Features, one at a time

Agents start features one at a time, with this loop:

```
[to-do] rules → tagged tests (red) → code → tests green → remove [to-do] → tag-check → commit
```

- The agent picks the rules to implement with `tag-ls --todo`. The `[to-do]` marker is removed in the same commit as the code and the tests.
- A database change is a migration. The exported DDL and the generated diagram are committed with it.
- Connectors to dependencies are developed when a feature requires them: one connector per dependency, with a fake used by the tests. Unit and functional tests never call real services, integration tests cover the real connectors.
- The commit message starts with the tag(s) or prefix it relates to (`PL-003: ...`), so `git log --grep PL-003` gives the history of a rule.

# Updating a rule

A tag is an entry point, not a perimeter: the agent starts from the tag, then follows the code, and the tests have the last word.

1. **Find the rule.** `tag-lookup <tag>` returns the rule, its code, its tests and the other rules that mention it. If the agent only has a description, it uses `tag-ls`, then the feature file (its name starts with the prefix). A `(none)` for code or tests in the output is a gap to look at.
2. **Analyse the impact before changing anything.** List the callers and callees of the symbols involved (search, LSP) and the tags they carry. A shared utility is a risk zone. Add the rules that reference this one (the `docs:ref` lines of `tag-lookup`). This gives the list of potentially impacted rules.
3. **Change the rule.** Modify it (the tag stays), add one (a new tag from `next_tag`), delete it (the tag is retired, never reused), or split it (new tags, the old one retired). Check the neighbouring rules for contradictions. The product owner validates the change before any code is written (the rule diff comes first): until then the rule is `[draft]`, then it becomes `[to-do]`.
4. **Tests first.** Update or add the tagged tests of the rule and see them fail, then change the code and remove the `[to-do]` marker.
5. **Verify.** Run the tests of the impacted rules, then the full suite, then `tag-check`.
6. **Commit.** Docs, code and tests go in one commit (or one PR) referencing the rule or feature that changed. Its description mentions the rules that were checked as impacted.

# Fixing a bug

1. Reproduce it.
2. Find the rule with `tag-lookup`.
3. Decide: is it a code bug (the rule is right) or a gap or ambiguity in the rule? In the second case, update the rule as above.
4. Add a regression test, tagged with the rule.
5. Fix the code, then verify and commit as for a rule update.

# Technical changes

Refactorings, dependency upgrades and other changes that don't alter a business rule update `docs/technical/` only.
The full suite must stay green, and `tag-check` verifies that the paths mentioned in the technical docs still exist.
