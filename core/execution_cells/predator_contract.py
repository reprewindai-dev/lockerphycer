"""Canonical foundational Predator contract.

This module freezes test identifiers and their semantic meaning so evidence cannot
be inflated by renumbering historical tests.  It contains no mocks and performs
no proof by itself; it defines the contract that real L2/L3 runtime harnesses must
satisfy before Foundational v1 can be sealed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class PredatorID(str, Enum):
    A00 = "A00"  # positive governed consequence
    A01 = "A01"  # capability widening
    A02 = "A02"  # resource widening / aliasing
    A03 = "A03"  # expired authority
    A04 = "A04"  # identity substitution
    A05 = "A05"  # tenant/workspace substitution
    A06 = "A06"  # audience/runtime-instance substitution
    A07 = "A07"  # effect/image/request-digest mutation
    A08 = "A08"  # nonce/lease replay
    A09 = "A09"  # target-state TOCTOU
    A10 = "A10"  # credential extraction
    A11 = "A11"  # network escape
    A12 = "A12"  # host/process escape
    A13 = "A13"  # device/sysfs escape
    A14 = "A14"  # resource exhaustion
    A15 = "A15"  # kill / post-dispatch ambiguity
    A16 = "A16"  # positive teardown + post-death non-reuse
    A17 = "A17"  # exact PGL consequence binding
    A18 = "A18"  # evidence tamper / forgery
    A19 = "A19"  # fan-in / synthesis creates no authority


@dataclass(frozen=True)
class PredatorCase:
    test_id: PredatorID
    property_name: str
    foundational_invariant: str
    required_observation: str


CASES: tuple[PredatorCase, ...] = (
    PredatorCase(PredatorID.A00, "positive governed consequence", "consequence authority", "one authorized consequence; exact target before/after evidence"),
    PredatorCase(PredatorID.A01, "capability widening", "authority cannot widen", "widened capability rejected before consequence"),
    PredatorCase(PredatorID.A02, "resource widening / aliasing", "authority cannot widen", "non-canonical or widened resource rejected before consequence"),
    PredatorCase(PredatorID.A03, "expired authority", "fail closed", "expired signed authority rejected"),
    PredatorCase(PredatorID.A04, "identity substitution", "identity attribution", "substituted principal rejected"),
    PredatorCase(PredatorID.A05, "tenant/workspace substitution", "identity attribution", "cross-tenant/workspace substitution rejected"),
    PredatorCase(PredatorID.A06, "audience/runtime-instance substitution", "authority audience binding", "authority for another host/audience rejected"),
    PredatorCase(PredatorID.A07, "effect/image/request-digest mutation", "exact semantic binding", "any bound digest mutation rejected"),
    PredatorCase(PredatorID.A08, "nonce/lease replay", "singular finality", "redelivery cannot create another consequence"),
    PredatorCase(PredatorID.A09, "target-state TOCTOU", "last-boundary validation", "stale target precondition rejected at mutation boundary"),
    PredatorCase(PredatorID.A10, "credential extraction", "credential non-possession", "untrusted workload cannot obtain usable provider/host credential"),
    PredatorCase(PredatorID.A11, "network escape", "containment", "no unauthorized IPv4/IPv6/DNS/metadata egress"),
    PredatorCase(PredatorID.A12, "host/process escape", "containment", "host/sibling processes cannot be enumerated, signalled, or attached"),
    PredatorCase(PredatorID.A13, "device/sysfs escape", "containment", "no unauthorized host device/sysfs/runtime-socket reach"),
    PredatorCase(PredatorID.A14, "resource exhaustion", "resource boundedness", "CPU/RAM/PID/output/wall-time ceilings hold"),
    PredatorCase(PredatorID.A15, "kill / post-dispatch ambiguity", "truthful uncertainty", "ambiguous physical outcome remains OUTCOME_UNKNOWN until reconciliation"),
    PredatorCase(PredatorID.A16, "positive teardown + post-death non-reuse", "disposable execution", "cell/VMM/process/state/route/authority cannot survive or be reused"),
    PredatorCase(PredatorID.A17, "exact PGL consequence binding", "continuous verifiable evidence", "exact consequence persisted, read back, hash-bound, chain-verified"),
    PredatorCase(PredatorID.A18, "evidence tamper / forgery", "truthful evidence", "altered receipt/details/signature cannot verify or promote success"),
    PredatorCase(PredatorID.A19, "fan-in / synthesis creates no authority", "composition must not create authority", "combining branches cannot produce an ungranted consequence"),
)

CASE_BY_ID = {case.test_id: case for case in CASES}
CANONICAL_IDS = tuple(case.test_id.value for case in CASES)


def assert_canonical_result_ids(ids: Iterable[str], *, require_complete: bool = False) -> tuple[str, ...]:
    """Reject unknown, duplicate, or incomplete evidence identifiers.

    Runtime harnesses use this before writing an evidence index.  Passing this
    function is only schema validation; it is never a conformance promotion.
    """
    observed = tuple(ids)
    if len(observed) != len(set(observed)):
        raise ValueError("Predator evidence contains duplicate test IDs")
    unknown = sorted(set(observed) - set(CANONICAL_IDS))
    if unknown:
        raise ValueError(f"Predator evidence contains non-canonical test IDs: {unknown}")
    if require_complete:
        missing = [test_id for test_id in CANONICAL_IDS if test_id not in observed]
        if missing:
            raise ValueError(f"Predator profile is incomplete; missing: {missing}")
    return observed
