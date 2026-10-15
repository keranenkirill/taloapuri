import pytest

from taloapuri.domain.case_states import (
    STATUS_LABELS_FI,
    TRANSITIONS,
    CaseAction,
    CaseStatus,
    TransitionError,
    TransitionForbidden,
    available_actions,
    resolve_transition,
)
from taloapuri.domain.roles import Role

MANAGER = frozenset({Role.PROPERTY_MANAGER})
SHAREHOLDER = frozenset({Role.SHAREHOLDER})
BOARD_MEMBER = frozenset({Role.BOARD_MEMBER})
EXPERT = frozenset({Role.EXTERNAL_EXPERT})


def test_every_status_has_finnish_label() -> None:
    assert set(STATUS_LABELS_FI) == set(CaseStatus)


def test_transitions_are_unique_per_action_and_source() -> None:
    keys = [(t.action, t.source) for t in TRANSITIONS]
    assert len(keys) == len(set(keys))


def test_every_status_is_reachable_from_draft() -> None:
    reachable = {CaseStatus.DRAFT}
    changed = True
    while changed:
        changed = False
        for t in TRANSITIONS:
            if t.source in reachable and t.target not in reachable:
                reachable.add(t.target)
                changed = True
    assert reachable == set(CaseStatus)


def test_shareholder_can_submit_own_draft() -> None:
    t = resolve_transition(CaseStatus.DRAFT, CaseAction.SUBMIT, SHAREHOLDER, is_creator=True)
    assert t.target == CaseStatus.IN_REVIEW


def test_shareholder_cannot_submit_someone_elses_draft() -> None:
    with pytest.raises(TransitionForbidden):
        resolve_transition(CaseStatus.DRAFT, CaseAction.SUBMIT, SHAREHOLDER, is_creator=False)


def test_shareholder_cannot_approve_even_own_case() -> None:
    with pytest.raises(TransitionForbidden):
        resolve_transition(CaseStatus.IN_REVIEW, CaseAction.APPROVE, SHAREHOLDER, is_creator=True)


def test_board_member_cannot_approve_alone() -> None:
    # Hallituksen päätös tehdään kokouksessa; yksittäinen jäsen ei hyväksy klikkauksella.
    with pytest.raises(TransitionForbidden):
        resolve_transition(CaseStatus.IN_REVIEW, CaseAction.APPROVE, BOARD_MEMBER, is_creator=False)


def test_external_expert_has_no_transitions_even_as_creator() -> None:
    for status in CaseStatus:
        assert available_actions(status, EXPERT, is_creator=True) == []


def test_cannot_send_without_approval() -> None:
    for status in CaseStatus:
        if status != CaseStatus.APPROVED:
            with pytest.raises((TransitionError, TransitionForbidden)):
                resolve_transition(status, CaseAction.MARK_SENT, MANAGER, is_creator=False)


def test_revise_after_approval_returns_to_draft() -> None:
    t = resolve_transition(CaseStatus.APPROVED, CaseAction.REVISE, MANAGER, is_creator=False)
    assert t.target == CaseStatus.DRAFT


def test_invalid_transition_raises() -> None:
    with pytest.raises(TransitionError):
        resolve_transition(CaseStatus.CLOSED, CaseAction.APPROVE, MANAGER, is_creator=False)


def test_closed_case_can_be_reopened_by_manager() -> None:
    assert CaseAction.REOPEN in available_actions(CaseStatus.CLOSED, MANAGER, is_creator=False)
