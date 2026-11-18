"""Regression test for docs/trace_case.md: C-014@11, FM-05 pre_deducted.

The agent subtracts the prior 30.000 refund itself (step 5 `proposal` 120.000), then the host
subtracts it again, so the ledger holds 90.000 instead of 120.000.
"""
import json
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.student


def _trial(shape: str, claim_id: str = "C-014", seed: int = 11):
    from lab9 import variants
    from lab9.eval import load_spec, load_world, make_task

    variants.register()
    spec = load_spec()
    world, claims = load_world(spec)
    labels = json.loads(Path(spec["labels"]).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        return make_task(shape, world, claims, labels, Path(tmp))({"claim_id": claim_id, "seed": seed}), labels[claim_id]


def _grade(grader, trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                           duration=0.0, _span_tree=None, attributes={}, metrics={})
    return grader().evaluate(ctx).value


def test_trace_case_c014_pre_deducted_caught():
    from lab9.graders import RefundAmountCorrect

    trial, label = _trial("seeded_regression")
    proposals = [e["payload"]["amount_vnd"] for e in trial["events"] if e["kind"] == "proposal"]
    assert proposals == [120000]                      # first wrong step: agent pre-deducts
    assert trial["snapshot"]["refund_vnd"] == 90000   # host deducts again
    assert _grade(RefundAmountCorrect, trial, label) is False


def test_trace_case_c014_fixed_passes():
    from lab9.graders import RefundAmountCorrect, ReplyMatchesLedger

    trial, label = _trial("fixed")
    assert not [e for e in trial["events"] if e["kind"] == "proposal"]
    assert trial["snapshot"]["refund_vnd"] == 120000
    assert _grade(RefundAmountCorrect, trial, label) is True
    assert _grade(ReplyMatchesLedger, trial, label) is True
