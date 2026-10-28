#!/usr/bin/env python3
"""Benchmark Claude Code on the same tasks, with and without SDD.

    bench.py prepare suite.json            build the snapshots of every (task, variant), check them
    bench.py run suite.json [--runs N]     run Claude Code on every (task, variant), N times, interleaved
    bench.py judge suite.json              optional: blind LLM grading of the diffs against the reference
    bench.py report suite.json             aggregate the metrics (results/report.md, results/runs.csv)

Only needs python3, git and the claude CLI. See README.md for the protocol.
"""
import argparse, csv, fnmatch, json, os, random, re, shlex, shutil, statistics, subprocess, sys, tempfile, time
from pathlib import Path

# ---------------------------------------------------------------- config

def load_suite(path):
    path = Path(path).resolve()
    suite = json.loads(path.read_text())
    base = path.parent
    suite["_base"] = base
    suite["project"]["repo"] = str((base / suite["project"]["repo"]).resolve())
    suite.setdefault("results_dir", "results")
    suite["_results"] = (base / suite["results_dir"]).resolve()
    suite.setdefault("runs", 5)
    suite.setdefault("timeout_s", 2400)
    suite.setdefault("claude_bin", "claude")
    suite.setdefault("claude_args", ["--permission-mode", "bypassPermissions"])
    for name, v in suite["variants"].items():
        if v.get("claude_md"):
            v["claude_md"] = str((base / v["claude_md"]).resolve())
    for t in suite["tasks"]:
        if t.get("inject_patch"):
            t["inject_patch"] = str((base / t["inject_patch"]).resolve())
        t["variant_patches"] = {v: str((base / f).resolve()) for v, f in t.get("variant_patches", {}).items()}
    return suite


def sh(cmd, cwd, env=None, timeout=None, check=False):
    """Runs a shell command, returns (exit code, combined output)."""
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, env=env, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    except subprocess.TimeoutExpired as e:
        return 124, (e.stdout or "") if isinstance(e.stdout, str) else "timeout"
    if check and p.returncode:
        sys.exit(f"command failed ({p.returncode}) in {cwd}: {cmd}\n{p.stdout[-3000:]}")
    return p.returncode, p.stdout


def git(args, cwd, check=True):
    return sh("git " + args, cwd, check=check)[1]


def variant_env(variant, workdir, home):
    """Clean environment: empty HOME (no user CLAUDE.md, settings, memory, MCP), variant PATH."""
    env = {k: v for k, v in os.environ.items() if k in (
        "PATH", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN", "LANG", "TERM",
        "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
        "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "IS_SANDBOX")}
    env["HOME"] = str(home)
    env["DISABLE_AUTOUPDATER"] = "1"
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    extra = [str(Path(workdir) / p) for p in variant.get("path", [])]
    env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    env.update(variant.get("env", {}))
    return env

# ---------------------------------------------------------------- snapshots

def prefixes_of(root):
    """Feature prefixes declared in docs/business front matters."""
    out = set()
    for f in (Path(root) / "docs" / "business").glob("*.md"):
        m = re.search(r"^---\n(.*?)\n---", f.read_text(errors="replace"), re.S)
        if m:
            p = re.search(r"^prefix:\s*(\w+)", m.group(1), re.M)
            if p:
                out.add(p.group(1))
    return out


DEFAULT_STRIP_LINES = [
    r"^\s*#\[Group\(['\"]{tag}['\"]\)\]\s*$",          # PHPUnit attribute
    r"^\s*\*\s*@group\s+{tag}\s*$",                    # PHPUnit docblock
    r"^\s*@pytest\.mark\.\w*{tag_us}\w*\s*$",          # pytest marker (PL_003)
    r"^\s*(//|#|\*|/\*\*?)\s*(@?{tag}|@{feature})(\s+(@?{tag}|@{feature}))*\s*(\*/)?\s*$",  # only tags
]


def strip_tags(root, prefixes, extra_line_patterns):
    """Removes rule and feature tags from code and tests, so the plain variant carries no SDD hint."""
    if not prefixes:
        return 0
    alt = "|".join(sorted(prefixes))
    tag = rf"(?:{alt})-\d+"
    line_res = [re.compile(p.format(tag=tag, tag_us=rf"(?:{alt})_\d+", feature=rf"(?:{alt})\b"))
                for p in DEFAULT_STRIP_LINES + list(extra_line_patterns)]
    token_re = re.compile(rf"@?\b{tag}\b[ \t]?|@(?:{alt})\b[ \t]?")
    changed = 0
    files = git("ls-files -z", root).split("\0")
    for rel in filter(None, files):
        f = Path(root) / rel
        if not f.is_file():
            continue
        try:
            text = f.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        lines = []
        for l in text.splitlines(keepends=True):
            if any(r.search(l.rstrip("\n")) for r in line_res):
                continue
            stripped = token_re.sub("", l)
            if stripped != l:  # drop the comment marker left empty: "x = 1  # @PL-001" -> "x = 1"
                stripped = re.sub(r"[ \t]+(#|//)[ \t]*(\n?)$", r"\2", stripped)
            lines.append(stripped)
        new = "".join(lines)
        if new != text:
            f.write_text(new)
            changed += 1
    return changed


def snapshot_dir(suite, task, vname):
    return suite["_results"] / "snapshots" / task["id"] / vname


def prepare(suite, task, vname, force=False):
    """Builds the starting point of a run: base_ref without history, variant applied, set up, committed."""
    variant = suite["variants"][vname]
    proj = suite["project"]
    dest = snapshot_dir(suite, task, vname)
    if (dest / ".git").exists() and not force:
        return dest
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    sh(f"git -C {shlex.quote(proj['repo'])} archive {shlex.quote(task['base_ref'])} | tar -x -C {shlex.quote(str(dest))}",
       dest, check=True)
    git("init -q", dest)
    git("add -A", dest)  # temporary index, used by strip_tags to list the files
    for patch in filter(None, [task.get("inject_patch"), task["variant_patches"].get(vname)]):
        git(f"apply {shlex.quote(patch)}", dest)
    prefixes = prefixes_of(dest)
    for pattern in variant.get("remove", []):
        for p in sorted(dest.glob(pattern), reverse=True):
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    git("add -A", dest)
    if variant.get("strip_tags"):
        n = strip_tags(dest, prefixes, variant.get("strip_line_regex", []))
        print(f"  {task['id']}/{vname}: tags stripped in {n} files")
    if variant.get("claude_md"):
        shutil.copy(variant["claude_md"], dest / "CLAUDE.md")
    home = Path(tempfile.mkdtemp())
    env = variant_env(variant, dest, home)
    if proj.get("setup_cmd"):
        sh(proj["setup_cmd"], dest, env=env, check=True)
    shutil.rmtree(dest / ".git")
    git("init -q -b main", dest)
    git("config user.name bench", dest)  # HOME is empty during the runs, the agent may commit
    git("config user.email bench@localhost", dest)
    git("add -A", dest)
    git("commit -q -m snapshot", dest)
    git("tag snapshot", dest)

    # sanity checks: the suite passes, and the plain variant leaks no tag
    code, out = sh(proj["test_cmd"], dest, env=env, timeout=suite["timeout_s"])
    print(f"  {task['id']}/{vname}: snapshot test suite {'OK' if code == 0 else f'FAILED ({code})'}")
    if code:
        (dest.parent / f"{vname}.sanity.log").write_text(out)
    git("checkout -q -- .", dest)  # leave no file of the sanity run in the agent's diff (ignored ones stay)
    git("clean -q -fd", dest)
    if variant.get("strip_tags") and prefixes:
        leak = git(f"grep -n -E '\\b({'|'.join(prefixes)})-[0-9]+\\b'", dest, check=False)
        if leak.strip():
            print(f"  {task['id']}/{vname}: WARNING, tags still present:\n" + "\n".join(leak.splitlines()[:10]))
    shutil.rmtree(home, ignore_errors=True)
    return dest

# ---------------------------------------------------------------- one run

def run_one(suite, task, vname, i):
    variant = suite["variants"][vname]
    proj = suite["project"]
    snap = prepare(suite, task, vname)
    out = suite["_results"] / "runs" / task["id"] / vname / f"{i:02d}"
    if (out / "metrics.json").exists():
        print(f"  skip {task['id']}/{vname}/{i} (done)")
        return
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix="bench-")) / "project"
    shutil.copytree(snap, work, symlinks=True)
    home = Path(tempfile.mkdtemp(prefix="bench-home-"))
    env = variant_env(variant, work, home)

    prompt = task.get("prompts", {}).get(vname, task["prompt"])
    cmd = [suite["claude_bin"], "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--strict-mcp-config", "--no-session-persistence"]
    if suite.get("model"):
        cmd += ["--model", suite["model"]]
    if suite.get("max_budget_usd"):
        cmd += ["--max-budget-usd", str(suite["max_budget_usd"])]
    cmd += variant.get("claude_args", suite["claude_args"])

    print(f"  run {task['id']}/{vname}/{i} ...", flush=True)
    t0 = time.time()
    with open(out / "stream.jsonl", "w") as stream, open(out / "stderr.log", "w") as err:
        try:
            p = subprocess.run(cmd, cwd=work, env=env, stdout=stream, stderr=err, timeout=suite["timeout_s"])
            exit_code = p.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
    wall = time.time() - t0

    m = {"task": task["id"], "kind": task.get("kind", ""), "variant": vname, "run": i,
         "exit_code": exit_code, "wall_s": round(wall, 1)}
    m.update(parse_stream(out / "stream.jsonl"))

    # the diff of the agent, before hidden tests are added
    git("add -A", work)
    diff = git("diff --cached snapshot", work)
    (out / "diff.patch").write_text(diff)
    m.update(diff_stats(git("diff --cached --numstat snapshot", work)))

    # success checks
    checks = {}
    if task.get("answer_regex"):
        answer = m.pop("_answer", "")
        checks["answer"] = all(re.search(r, answer, re.I | re.M) for r in task["answer_regex"])
    m.pop("_answer", None)
    if task.get("run_suite", True):
        code, log = sh(proj["test_cmd"], work, env=env, timeout=suite["timeout_s"])
        (out / "suite.log").write_text(log)
        checks["suite"] = code == 0
    if task.get("hidden_tests"):
        for rel in task["hidden_tests"]:
            content = subprocess.run(["git", "-C", proj["repo"], "show", f"{task['reference_ref']}:{rel}"],
                                     stdout=subprocess.PIPE, check=True).stdout
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            (work / rel).write_bytes(content)
        code, log = sh(task["accept_cmd"], work, env=env, timeout=suite["timeout_s"])
        (out / "accept.log").write_text(log)
        checks["accept"] = code == 0
    for name, c in variant.get("checks", {}).items():   # variant specific, reported apart (ex.: tag-check)
        code, log = sh(c, work, env=env, timeout=600)
        (out / f"check-{name}.log").write_text(log)
        m[f"check_{name}"] = code == 0
    m["checks"] = checks
    m["success"] = bool(checks) and all(checks.values()) and exit_code == 0 and not m.get("is_error")
    (out / "metrics.json").write_text(json.dumps(m, indent=1))
    print(f"    {'OK' if m['success'] else 'KO'} {checks} cost=${m.get('cost_usd')} "
          f"turns={m.get('turns')} {m['wall_s']}s perm_rules={m.get('perm_rules')}")
    if not suite.get("keep_workdirs"):
        shutil.rmtree(work.parent, ignore_errors=True)
    shutil.rmtree(home, ignore_errors=True)

# ---------------------------------------------------------------- metrics

READ_TOOLS = {"Read", "Glob", "Grep", "LS", "TodoWrite", "Task", "Agent", "TaskOutput", "BashOutput",
              "NotebookRead", "ExitPlanMode", "EnterPlanMode", "Skill", "ToolSearch", "AskUserQuestion"}
EDIT_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}
READ_ONLY_CMDS = {"ls", "cat", "head", "tail", "grep", "rg", "egrep", "find", "wc", "pwd", "echo", "sed -n", "tree",
                  "file", "stat", "diff", "sort", "uniq", "cut", "awk", "which", "true", "test", "[",
                  "git status", "git log", "git diff", "git show", "git grep", "git ls-files", "git blame",
                  "tag-ls", "tag-lookup", "tag-check"}
TWO_WORD = {"git", "npm", "npx", "pnpm", "yarn", "composer", "docker", "make", "cargo", "go", "python", "python3",
            "php", "bin/console", "php bin/console", "symfony", "dotnet", "mvn", "gradle", "sed", "uv", "poetry"}


def bash_rules(command):
    """Allowlist rules ("Bash(git diff:*)") a Bash command needs: one per sub-command."""
    rules = []
    for part in re.split(r"&&|\|\||;|\||\n", command):
        words = [w for w in part.strip().split() if not re.match(r"^\w+=", w)]  # skip VAR=x prefixes
        words = [w for w in words if w not in ("(", ")", "{", "}")]
        if not words or words[0] in ("cd", "2>&1", "do", "done", "then", "fi", "else", "for", "if", "while"):
            continue
        w0 = words[0].split("/")[-1] if words[0].startswith(("./", "/")) and "bin/" not in words[0] else words[0]
        if len(words) > 1 and w0 in TWO_WORD and not words[1].startswith("-"):
            key = f"{w0} {words[1]}"
        elif len(words) > 1 and w0 == "sed" and words[1] == "-n":
            key = "sed -n"
        else:
            key = w0
        rules.append(key)
    return rules


def classify(name, inp):
    """(category, allowlist rules needed in default mode, empty when none)."""
    if name in READ_TOOLS:
        return "read", []
    if name in EDIT_TOOLS:
        return "edit", ["Edit"]
    if name == "Bash":
        keys = bash_rules(inp.get("command", ""))
        need = sorted({k for k in keys if k not in READ_ONLY_CMDS})
        if not need:
            return "bash:read", []
        return "bash:exec", [f"Bash({k}:*)" for k in need]
    if name == "WebFetch":
        dom = re.sub(r"^https?://([^/]+).*", r"\1", inp.get("url", ""))
        return "web", [f"WebFetch(domain:{dom})"]
    if name == "WebSearch":
        return "web", ["WebSearch"]
    return "other", [name]


def parse_stream(path):
    m = {"tool_calls": 0, "calls_by_category": {}, "rules": {}, "peak_context": 0, "subagent_calls": 0}
    result = {}
    for line in open(path, errors="replace"):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            msg = ev.get("message", {})
            u = msg.get("usage") or {}
            if not ev.get("parent_tool_use_id"):
                ctx = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                m["peak_context"] = max(m["peak_context"], ctx)
            for block in msg.get("content", []):
                if block.get("type") != "tool_use":
                    continue
                m["tool_calls"] += 1
                if ev.get("parent_tool_use_id"):
                    m["subagent_calls"] += 1
                cat, rules = classify(block.get("name", ""), block.get("input", {}) or {})
                m["calls_by_category"][cat] = m["calls_by_category"].get(cat, 0) + 1
                for r in rules:
                    m["rules"][r] = m["rules"].get(r, 0) + 1
        elif ev.get("type") == "result":
            result = ev
    # one prompt per call needing a permission, "Edit" counted once (accepted for the session)
    m["perm_calls"] = sum(v for k, v in m["calls_by_category"].items() if k not in ("read", "bash:read"))
    m["perm_rules"] = len(m["rules"])
    u = result.get("usage") or {}
    mu = result.get("modelUsage") or {}
    if mu:  # includes subagents and the small models used by Claude Code
        tok = {k: sum(v.get(k, 0) for v in mu.values())
               for k in ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")}
        m.update(input_tokens=tok["inputTokens"], output_tokens=tok["outputTokens"],
                 cache_read_tokens=tok["cacheReadInputTokens"], cache_write_tokens=tok["cacheCreationInputTokens"])
    else:
        m.update(input_tokens=u.get("input_tokens", 0), output_tokens=u.get("output_tokens", 0),
                 cache_read_tokens=u.get("cache_read_input_tokens", 0),
                 cache_write_tokens=u.get("cache_creation_input_tokens", 0))
    m["total_tokens"] = m["input_tokens"] + m["output_tokens"] + m["cache_read_tokens"] + m["cache_write_tokens"]
    m.update(cost_usd=result.get("total_cost_usd"), duration_s=round(result.get("duration_ms", 0) / 1000, 1),
             api_duration_s=round(result.get("duration_api_ms", 0) / 1000, 1), turns=result.get("num_turns"),
             is_error=result.get("is_error", True), result_subtype=result.get("subtype", "missing"),
             permission_denials=len(result.get("permission_denials") or []),
             models=sorted(mu.keys()), _answer=result.get("result", ""))
    return m


def diff_stats(numstat):
    files, added, removed = 0, 0, 0
    for line in numstat.splitlines():
        a, r, _ = line.split("\t", 2)
        files += 1
        added += int(a) if a.isdigit() else 0
        removed += int(r) if r.isdigit() else 0
    return {"diff_files": files, "diff_added": added, "diff_removed": removed}

# ---------------------------------------------------------------- judge (optional)

JUDGE_PROMPT = """You grade a code change made by an AI agent. You get the task, a reference change written
by the project's developers, and the agent's change. The reference is one valid solution, not the only one.

Score from 0 to 3:
3 = the task is fully done, as well as or better than the reference, no unrelated or risky change;
2 = done, with minor issues (missing edge case or test, a bit of unrelated change);
1 = partially done or with a real defect;
0 = not done, wrong, or breaks something.
Answer with JSON only: {{"score": <0-3>, "rationale": "<two sentences>"}}

# Task
{task}

# Reference change
{ref}

# Agent change
{agent}
"""


def blind(diff, prefixes):
    """Drops the docs hunks and the tags, so the judge can't tell the variant."""
    keep, out = True, []
    for line in diff.splitlines():
        if line.startswith("diff --git"):
            keep = not re.search(r" a/(docs/|CLAUDE\.md|AGENTS\.md)", line)
        if keep:
            out.append(line)
    text = "\n".join(out)
    if prefixes:
        alt = "|".join(prefixes)
        text = re.sub(rf"@?\b(?:{alt})-\d+\b ?|@(?:{alt})\b ?|#\[Group\(['\"]['\"]\)\]", "", text)
    return text[:60000]


def judge(suite, runs=3):
    proj = suite["project"]
    for task in suite["tasks"]:
        if not task.get("reference_ref"):
            continue
        ref_diff = git(f"diff {task['base_ref']} {task['reference_ref']}", proj["repo"])
        with tempfile.TemporaryDirectory() as tmp:
            sh(f"git -C {shlex.quote(proj['repo'])} archive {task['reference_ref']} docs/business | tar -x -C {tmp}", tmp)
            prefixes = prefixes_of(tmp)
        for mf in sorted((suite["_results"] / "runs" / task["id"]).glob("*/*/metrics.json")):
            jf = mf.parent / "judge.json"
            if jf.exists():
                continue
            prompt = JUDGE_PROMPT.format(task=task["prompt"], ref=blind(ref_diff, prefixes),
                                         agent=blind((mf.parent / "diff.patch").read_text(), prefixes))
            scores = []
            for _ in range(runs):
                cmd = [suite["claude_bin"], "-p", "--output-format", "json", "--tools", "",
                       "--model", suite.get("judge_model", suite.get("model", "")) or "opus"]
                p = subprocess.run(cmd, input=prompt, stdout=subprocess.PIPE, text=True,
                                   cwd=tempfile.gettempdir(), timeout=600)
                try:
                    txt = json.loads(p.stdout)["result"]
                    scores.append(json.loads(re.search(r"\{.*\}", txt, re.S).group(0)))
                except Exception as e:  # noqa: BLE001 - a failed grading is just skipped
                    print(f"    judge failed on {mf.parent}: {e}")
            if scores:
                med = statistics.median(s["score"] for s in scores)
                jf.write_text(json.dumps({"score": med, "all": scores}, indent=1))
                print(f"  judged {mf.parent.relative_to(suite['_results'])}: {med}")

# ---------------------------------------------------------------- report

COLS = ["success", "judge", "cost_usd", "total_tokens", "output_tokens", "peak_context", "duration_s",
        "wall_s", "turns", "tool_calls", "perm_calls", "perm_rules", "diff_files"]


def med_ci(values, n=2000):
    """Median and bootstrap 90% interval."""
    if not values:
        return None, None, None
    meds = sorted(statistics.median(random.choices(values, k=len(values))) for _ in range(n))
    return statistics.median(values), meds[int(n * .05)], meds[int(n * .95)]


def report(suite):
    rows = []
    for mf in sorted((suite["_results"] / "runs").glob("*/*/*/metrics.json")):
        m = json.loads(mf.read_text())
        jf = mf.parent / "judge.json"
        m["judge"] = json.loads(jf.read_text())["score"] if jf.exists() else None
        rows.append(m)
    if not rows:
        sys.exit("no run found")
    with open(suite["_results"] / "runs.csv", "w", newline="") as f:
        keys = ["task", "kind", "variant", "run"] + COLS + sorted({k for r in rows for k in r if k.startswith("check_")})
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    variants = list(suite["variants"])
    lines = ["# Benchmark report", "",
             f"Model: `{suite.get('model', 'default')}`. Medians, with a bootstrap 90% interval in brackets. "
             "Success: rate of runs where every check passed.", ""]
    groups = {}
    for r in rows:
        groups.setdefault(r["task"], {}).setdefault(r["variant"], []).append(r)
    groups["ALL"] = {v: [r for r in rows if r["variant"] == v] for v in variants}
    for task, by_v in groups.items():
        lines += [f"## {task}", "", "| metric | " + " | ".join(f"{v} (n={len(by_v.get(v, []))})" for v in variants)
                  + (f" | {variants[1]} / {variants[0]} |" if len(variants) == 2 else " |"),
                  "|---" * (len(variants) + 1 + (len(variants) == 2)) + "|"]
        for c in COLS:
            cells, meds = [], []
            for v in variants:
                vals = [r[c] for r in by_v.get(v, []) if r.get(c) is not None]
                if c == "success":
                    rate = sum(1 for x in vals if x) / len(vals) if vals else None
                    cells.append(f"{rate:.0%}" if rate is not None else "-")
                    meds.append(rate)
                    continue
                med, lo, hi = med_ci([float(x) for x in vals])
                meds.append(med)
                cells.append("-" if med is None else f"{fmt(med)} [{fmt(lo)}-{fmt(hi)}]")
            ratio = ""
            if len(variants) == 2:
                ratio = f"{meds[1] / meds[0]:.2f}" if meds[0] and meds[1] is not None else "-"
            lines.append(f"| {c} | " + " | ".join(cells) + (f" | {ratio} |" if len(variants) == 2 else " |"))
        lines.append("")
    # allowlist needed, aggregated
    lines += ["## Permissions needed (rule: runs using it, per variant)", ""]
    for v in variants:
        counts = {}
        for mf in (suite["_results"] / "runs").glob(f"*/{v}/*/metrics.json"):
            for rule in json.loads(mf.read_text()).get("rules", {}):
                counts[rule] = counts.get(rule, 0) + 1
        lines.append(f"- **{v}**: " + ", ".join(f"`{k}` {n}" for k, n in sorted(counts.items(), key=lambda x: -x[1])))
    (suite["_results"] / "report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def fmt(x):
    if x is None:
        return "-"
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:.2f}"

# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["prepare", "run", "judge", "report"])
    ap.add_argument("suite")
    ap.add_argument("--runs", type=int, help="runs per (task, variant), overrides the suite")
    ap.add_argument("--task", action="append", help="only these task ids")
    ap.add_argument("--variant", action="append", help="only these variants")
    ap.add_argument("--force", action="store_true", help="prepare: rebuild the snapshots")
    ap.add_argument("--seed", type=int, default=0, help="seed of the run order")
    a = ap.parse_args()
    suite = load_suite(a.suite)
    tasks = [t for t in suite["tasks"] if not a.task or t["id"] in a.task]
    variants = [v for v in suite["variants"] if not a.variant or v in a.variant]
    if a.command == "prepare":
        for t in tasks:
            for v in variants:
                prepare(suite, t, v, force=a.force)
    elif a.command == "run":
        rng = random.Random(a.seed)
        for i in range(a.runs or suite["runs"]):
            plan = [(t, v) for t in tasks for v in variants]
            rng.shuffle(plan)  # interleaved, so a slow API period doesn't hit one variant only
            for t, v in plan:
                run_one(suite, t, v, i)
    elif a.command == "judge":
        judge(suite)
    else:
        report(suite)


if __name__ == "__main__":
    main()
