"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows, base_rows = pr.get("rows") or [], base.get("rows") or []
    man, base_man = pr.get("manifest") or {}, base.get("manifest") or {}

    # 1. Metric values must be finite numbers, and must be what the rows say (no hand-edited summary).
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (NaN/inf drops out of every comparison)")
        elif isinstance(v, (int, float)) and rows and k in rows[0]:
            vals = [r.get(k) for r in rows if r.get(k) is not None]
            if vals:
                want = sum(vals) if k in SAFETY_COUNTS else sum(vals) / len(vals)
                if abs(float(v) - float(want)) > 1e-3:
                    problems.append(f"metric {k} = {v} but its rows give {round(want, 4)} (summary edited by hand?)")

    # 2. Coverage: every (item, seed) exactly once, the same set as the baseline.
    want_n = (man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want_n:
        problems.append(f"{len(rows)} rows, manifest says {man.get('items')} items x "
                        f"{len(man.get('seeds') or [])} seeds = {want_n}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = sorted({k for k in keys if keys.count(k) > 1})
    if dups:
        problems.append(f"duplicated rows: {', '.join(f'{i}@{s}' for i, s in dups[:5])}")
    pr_set, base_set = set(keys), {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if pr_set != base_set:
        problems.append(f"(item, seed) set differs from baseline: {len(base_set - pr_set)} missing, "
                        f"{len(pr_set - base_set)} extra (cherry-picked seeds/items?)")
    for f in ("items", "seeds"):
        if man.get(f) != base_man.get(f):
            problems.append(f"manifest {f} {man.get(f)} != baseline {base_man.get(f)}")

    # 3. Graders must have run on every row, on the PR and on the baseline.
    for name, rep in (("PR", pr), ("baseline", base)):
        if rep.get("evaluator_failures"):
            problems.append(f"{name} has {len(rep['evaluator_failures'])} evaluator failure(s): "
                            f"{str(rep['evaluator_failures'][0])[:80]}")
    graded = [m["id"] for m in spec.get("metrics", []) if any(m["id"] in r for r in base_rows + rows)]
    for m in graded:
        missing = [f"{r.get('item_id')}@{r.get('seed')}" for r in rows if r.get(m) is None]
        if missing:
            problems.append(f"{len(missing)} row(s) have no value for {m} (crashed grader?): {', '.join(missing[:3])}")
        if any(isinstance(r.get(m), float) and not math.isfinite(r[m]) for r in rows):
            problems.append(f"row(s) have NaN/inf for {m}")

    # 4. Slice tags come from the labels, so they must match the baseline item for item.
    pt = {r.get("item_id"): sorted(r.get("slices") or []) for r in rows}
    bt = {r.get("item_id"): sorted(r.get("slices") or []) for r in base_rows}
    moved = sorted(i for i in pt.keys() & bt.keys() if pt[i] != bt[i])
    if moved:
        problems.append(f"slice tags differ from baseline on {', '.join(moved[:5])}")

    # 5. Ratchet: on the same eval-set version the spec may only get stricter.
    if base_spec is not None:
        problems += ratchet(spec, base_spec)
    return problems


SAFETY_COUNTS = {"secret_leak", "approval_bypass"}   # summed, not averaged (lab9.eval.aggregate)
LOWER_IS_STRICTER = ("max", "max_increase", "max_new_failing_trials")
HIGHER_IS_STRICTER = ("min",)
FLAGS = ("no_significant_drop", "blocking")


def _looser(where: str, new: dict, old: dict) -> list[str]:
    out = []
    for k in LOWER_IS_STRICTER:
        if k in old and (k not in new or new[k] > old[k]):
            out.append(f"ratchet: {where} {k} {old[k]} -> {new.get(k, 'removed')}")
    for k in HIGHER_IS_STRICTER:
        if k in old and (k not in new or new[k] < old[k]):
            out.append(f"ratchet: {where} {k} {old[k]} -> {new.get(k, 'removed')}")
    for k in FLAGS:
        if old.get(k) and not new.get(k):
            out.append(f"ratchet: {where} {k} dropped")
    return out


def ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Thresholds on the same eval-set version may only get stricter."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []                                     # new eval set: new baseline, thresholds restart
    out = [f"ratchet: {k} changed on the same eval-set version"
           for k in ("eval_set", "labels", "seeds", "adversarial_pack") if base_spec.get(k) != spec.get(k)]
    new_m = {m["id"]: m for m in spec.get("metrics", [])}
    for m in base_spec.get("metrics", []):
        n = new_m.get(m["id"])
        if n is None:
            out.append(f"ratchet: metric {m['id']} removed")
            continue
        out += _looser(f"metric {m['id']}", {**n.get("threshold", {}), "blocking": n.get("blocking")},
                       {**m.get("threshold", {}), "blocking": m.get("blocking")})
    new_s = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
    for sl in base_spec.get("slices") or []:
        key = (sl["name"], sl["metric"])
        if key not in new_s:
            out.append(f"ratchet: slice {key[0]}/{key[1]} removed")
            continue
        out += _looser(f"slice {key[0]}/{key[1]}", new_s[key], sl)
    if (spec.get("bootstrap") or {}).get("confidence", 0.95) < (base_spec.get("bootstrap") or {}).get("confidence", 0.95):
        out.append("ratchet: bootstrap confidence lowered")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        val = round(sum(a.values()) / len(a), 4) if a else None
        verdict, note = "ok", f"{len(a)} item(s)"
        if val is None:
            verdict = "missing"                      # an empty slice proves nothing: never a silent pass
        elif "min" in sl and val < sl["min"]:
            verdict = "fail"
        if sl.get("no_significant_drop") and a:
            keys = sorted(set(a) & set(b))
            if keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<38} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if "max_new_failing_trials" in th and val is not None:
            # A mean (and pass^k averaged over items) lets a new 1-in-5 failure hide behind failures the
            # PR happened to fix. Trials are deterministic per (item, seed) on MockLLM, so count trials
            # that passed on main and fail on the PR. With a real LLM, set the bound from the A/A run.
            passed = {(r["item_id"], r["seed"]) for r in base["rows"] if r.get("pass_rate")}
            new_bad = sorted(f"{r['item_id']}@{r['seed']}" for r in pr["rows"]
                             if (r["item_id"], r["seed"]) in passed and not r.get("pass_rate"))
            note = f"{len(new_bad)} new failing trial(s)" + (f": {', '.join(new_bad[:3])}" if new_bad else "")
            if len(new_bad) > th["max_new_failing_trials"]:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
