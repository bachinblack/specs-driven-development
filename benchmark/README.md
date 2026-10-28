# Benchmark: Claude Code with and without SDD

A reproducible protocol to compare the same tasks done by Claude Code on the same project, **with** the SDD docs and tooling and **without** them, on four axes:

1. **Permissions**: which tool permissions the agent needs, and how many prompts a user would get.
2. **Tokens and cost**: tokens consumed (input, output, cache), peak context, cost.
3. **Duration**: agent time, API time, wall time, turns.
4. **Success** (optional, harder): hidden acceptance tests, full suite, blind LLM grading.

`bench.py` runs it. It only needs `python3`, `git` and the `claude` CLI.

## 1. Principle

```
project repo ──git archive base_ref──► snapshot (no history) ──variant──► sdd   ┐
                                                                       └──► plain ┘── N runs each, interleaved
                                                     claude -p "<task>" --output-format stream-json
                                                                    │
            stream.jsonl ─► tokens, cost, duration, tool calls ─► permissions
            diff.patch   ─► full suite, hidden tests of reference_ref ─► success ─► blind judge (optional)
```

A task is a past change of one of your SDD projects: `base_ref` is the commit before it, `reference_ref` the commit that made it (with its tests). The agent starts from `base_ref`, the tests of `reference_ref` are hidden and only added after the run to grade it. This is SWE-bench applied to your own history, and your commit convention (`PL-006: ...`) makes the candidates easy to find:

```
git log --oneline -E --grep '^[A-Z]+-[0-9]+'
git show --stat <commit>   # the tests it added or modified are the hidden tests
```

## 2. Variants

| variant | what the agent gets |
|---|---|
| `sdd` | the project at `base_ref` as is: `CLAUDE.md`, `docs/`, the `tag-*` scripts on the `PATH`, tags in code and tests |
| `plain` | the same code, minus `docs/`, the SDD `CLAUDE.md`, the scripts and **every tag** in code and tests (`strip_tags`), plus a baseline `CLAUDE.md` |

The baseline is not "nothing": a team without SDD has a `CLAUDE.md` with the stack and the commands. Generate it once with `/init` on the plain snapshot, review it (no business rule, no tag), and use the same file for every task (template in `example/baseline-CLAUDE.md`). Comparing with an empty project would flatter SDD.

`strip_tags` reads the prefixes from `docs/business/` before deleting it, removes the lines holding only tags (`#[Group('PL-003')]`, `* @group PL-003`, `// @PL-003`, pytest markers) and the remaining `@PL-003`/`@PL` tokens. Add patterns for your frameworks in `strip_line_regex` (`{tag}` = a rule tag, `{feature}` = a prefix). `prepare` runs the test suite on each snapshot and warns if a tag is still present: the plain snapshot must be green and clean before any run.

Optional third variant, to know where the gain comes from: `docs-only` (keep `docs/business/`, remove the scripts and the tags from the code). Variants are just configuration, add as many as needed.

Remove from the plain variant anything else that is SDD: `.claude/` skills or commands, pre-commit configs calling `tag-check`.

## 3. Choosing the tasks

6 to 10 tasks over 2 or 3 projects, of four kinds, because SDD should not help them equally:

| kind | example | success check |
|---|---|---|
| `question` | "which code and tests implement the ordering?" (read only) | `answer_regex` on the final answer |
| `feature` | implement a `[to-do]` rule | hidden tests of `reference_ref` + full suite |
| `update` | change an existing rule, with impact on other rules | hidden tests + full suite (regressions) |
| `bug` | a bug report written as a user would (symptom, not cause) | regression test of the fix commit + full suite |

Rules for a fair task:

- **Same prompt for both variants**, in natural language, without tags (the plain variant has none). It must contain everything needed to succeed, in particular the interface the hidden tests rely on (route, parameter, class or method name): a hidden test failing because the agent named a method differently measures nothing. Prefer functional tests (HTTP, command) as hidden tests, they don't depend on implementation choices.
- Optionally, a second campaign with SDD-native prompts (`"prompts": {"sdd": "Implement the [to-do] rule PL-006."}`): more realistic, less controlled. Don't mix both in the same report.
- For a `feature` task, the rule must be `[to-do]` in `docs/business/` at `base_ref` (in SDD, the rule is validated before the code). If the rule was added in the implementation commit, give the `sdd` variant the docs change with `"variant_patches": {"sdd": "tasks/PL-006-rule.patch"}`.
- A synthetic bug can be injected in both variants with `"inject_patch": "tasks/bug.patch"` (applied before stripping).
- Skip the tasks where the reference itself fails, and the trivial ones (a one-line change in an obvious file shows nothing).

Format: see `example/suite.json`. Paths are relative to the suite file.

## 4. Reproducibility

The model isn't deterministic and the temperature can't be set in Claude Code: reproducibility comes from a fixed environment and repeated runs.

- **Pin everything** and write it in the report: Claude Code version (`npm i -g @anthropic-ai/claude-code@<version>`), `model` (a full id, not an alias), project commits, toolchain (ideally a Docker image).
- **Isolation**, done by `bench.py`: each run gets a fresh copy of the snapshot, an empty `HOME` (no user `CLAUDE.md`, settings, memory or MCP server), `--strict-mcp-config`, `--no-session-persistence`, auto-updater off. The snapshot has **no git history**: the agent can't `git show` the solution, nor `git log --grep` the tags.
- **Repetition**: at least 5 runs per (task, variant), 10 to conclude. Runs are **interleaved** in a random order (`--seed`), so a slow API period or the prompt cache warming up doesn't favour one variant.
- **Same limits**: `timeout_s` and `max_budget_usd` are the same for both. A run hitting them is a failure, not an excluded run.
- **Bypass mode needs a sandbox**: runs use `--permission-mode bypassPermissions`. Run them in a container or a VM, as a non-root user (or with `IS_SANDBOX=1` in a disposable container).
- Authentication: `ANTHROPIC_API_KEY` (or `CLAUDE_CODE_OAUTH_TOKEN`) is passed through, the rest of the environment is not.

## 5. Metrics

All from the `stream-json` output of `claude -p`, plus the checks.

| metric | source | note |
|---|---|---|
| `cost_usd` | `total_cost_usd` of the result | the best single number: weights cache reads (cheap) and writes |
| `total_tokens`, `output_tokens`, `cache_read_tokens`... | `modelUsage` of the result | sums every model, subagents included |
| `peak_context` | max of input + cache tokens of a main-thread turn | how much the agent had to load: SDD should keep it low |
| `duration_s`, `api_duration_s` | `duration_ms`, `duration_api_ms` | agent time, without the grading |
| `wall_s` | measured around the process | |
| `turns`, `tool_calls`, `subagent_calls` | result, `tool_use` blocks | |
| `perm_calls` | tool calls that would ask for a permission in default mode | see below |
| `perm_rules` | distinct allowlist rules needed (`Edit`, `Bash(composer test:*)`...) | the permissions to grant to run unattended |
| `diff_files`, `diff_added`, `diff_removed` | `git diff` against the snapshot | a much bigger diff often means unrelated changes |
| `success` | all the checks of the task passed | |
| `check_<name>` | variant specific checks (`tag-check` for `sdd`) | reported apart, not in `success`: plain can't pass it |
| `judge` | optional blind grading, 0 to 3 | |

### Permissions

Two complementary measures.

**Offline (always)**: runs are in bypass mode and every tool call is logged. `bench.py` replays them against the default policy: `Read`, `Grep`, `Glob`... and read-only commands (`ls`, `grep`, `git diff`, `tag-lookup`...) need nothing; `Edit`/`Write` need `Edit`; any other command needs a `Bash(<command>:*)` rule, one per sub-command of a pipeline or `&&` chain. The report lists, per variant, the rules needed and in how many runs. Expected: SDD replaces `find | xargs grep` chains by `tag-lookup`, which is read-only and easy to allow. Adjust `READ_ONLY_CMDS` to your own policy.

**Strict (optional, exact)**: run the same variants with an allowlist and `dontAsk` mode, where anything not allowed is denied instead of prompting. `permission_denials` and the success rate then say whether the agent can do the task unattended with that allowlist. Same allowlist for both variants, plus the `tag-*` scripts for SDD:

```json
"sdd-strict": {
  "path": ["bin"],
  "claude_args": ["--permission-mode", "dontAsk", "--settings",
    "{\"permissions\":{\"allow\":[\"Edit\",\"Bash(vendor/bin/phpunit:*)\",\"Bash(git status:*)\",\"Bash(git diff:*)\",\"Bash(tag-ls:*)\",\"Bash(tag-lookup:*)\",\"Bash(tag-check:*)\"]}}"]
}
```

### Success, in levels

1. **Acceptance**: the hidden tests of `reference_ref` pass (or `answer_regex` matches). Deterministic, cheap: the main criterion.
2. **No regression**: the full suite passes on the agent's result (before the hidden tests are added, so its own tests count).
3. **Quality (optional)**: `bench.py judge` asks a model to grade the agent diff against the reference diff, 0 to 3, three times (median). It is **blind**: docs hunks and tags are removed from both diffs, so the judge can't tell the variant. Use a stronger model than the one tested, and read a sample of the gradings yourself before trusting them.
4. **SDD hygiene**, `sdd` only: `tag-check` passes, the `[to-do]` marker is removed, the new tests are tagged. Reported apart.

Also look at the consistency: a variant that succeeds 5/5 is better than one at 3/5 with a lower median cost.

## 6. Running it

```bash
cp -r example ../bench-myproject && cd ../bench-myproject   # suite.json + baseline-CLAUDE.md
# fill suite.json: repo, setup/test commands, variants, tasks

python3 path/to/bench.py prepare suite.json      # snapshots + sanity checks, read the warnings
python3 path/to/bench.py run suite.json --runs 1 --task <one task>   # smoke test, check results/runs/*/stream.jsonl
python3 path/to/bench.py run suite.json          # the campaign, resumable (finished runs are skipped)
python3 path/to/bench.py judge suite.json        # optional
python3 path/to/bench.py report suite.json       # results/report.md and results/runs.csv
```

Order of magnitude: 8 tasks × 2 variants × 5 runs = 80 runs, so a few hours and, at $0.50 to $3 a run, $40 to $240. Start with 2 tasks and 3 runs to check the setup.

Outputs, per run (`results/runs/<task>/<variant>/<nn>/`): `stream.jsonl` (full transcript), `diff.patch`, `suite.log`, `accept.log`, `metrics.json`, `judge.json`.

## 7. Reading the results

`report.md` gives, per task and overall, the median of each metric with a bootstrap 90% interval, and the `plain / sdd` ratio. A ratio of 1.40 on `cost_usd` means plain costs 40% more.

- Only trust a difference whose intervals don't overlap, and that holds across several tasks. Report per task kind: SDD should help `question` and `update` a lot, `feature` less.
- Compare cost **at equal success**: a cheaper variant that fails more is not cheaper. Look at the cost of the successful runs too (`runs.csv`).
- Read the transcripts of the outliers: a run that got lost tells more than the median.

Known biases, to state with the results:

- The cost of writing and maintaining the docs is not measured, only their use.
- The SDD `CLAUDE.md` and docs add tokens to every request: on very small tasks SDD can cost more.
- Tasks taken from an SDD history were cut by SDD (one rule, one commit), which may suit the `sdd` variant.
- The result depends on the quality of the baseline `CLAUDE.md`, and on the model and Claude Code version: pin and report them.
- Hidden tests written against the reference implementation may reject a valid alternative: check the failed acceptance logs by hand.

Before the real campaign, run one task with `--runs 1` and check `metrics.json`: the parsing of `stream-json` (token fields, subagent events) follows the format of the Claude Code version used to write it, and may need adjusting for yours.
