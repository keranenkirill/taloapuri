"""Asian tilakone.

Puhdas Python-moduuli ilman tietokantaa, jotta säännöt ovat helposti testattavissa.
Palvelin tarkistaa jokaisen siirtymän; käyttöliittymä vain näyttää sallitut toiminnot.
"""

from dataclasses import dataclass
from enum import StrEnum

from taloapuri.domain.roles import Role


class CaseStatus(StrEnum):
    DRAFT = "draft"
    AWAITING_INFO = "awaiting_info"
    IN_REVIEW = "in_review"
    ESCALATED = "escalated"
    APPROVED = "approved"
    SENT = "sent"
    SEND_FAILED = "send_failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    CLOSED = "closed"


STATUS_LABELS_FI: dict[CaseStatus, str] = {
    CaseStatus.DRAFT: "Luonnos",
    CaseStatus.AWAITING_INFO: "Odottaa tietoja",
    CaseStatus.IN_REVIEW: "Tarkistettavana",
    CaseStatus.ESCALATED: "Eskaloitu asiantuntijalle",
    CaseStatus.APPROVED: "Hyväksytty",
    CaseStatus.SENT: "Lähetetty",
    CaseStatus.SEND_FAILED: "Lähetys epäonnistui",
    CaseStatus.REJECTED: "Hylätty",
    CaseStatus.CANCELLED: "Peruttu",
    CaseStatus.CLOSED: "Suljettu",
}


class CaseAction(StrEnum):
    SUBMIT = "submit"  # lähetä tarkistettavaksi
    REQUEST_INFO = "request_info"  # pyydä lisätietoja
    PROVIDE_INFO = "provide_info"  # lisätiedot annettu
    ESCALATE = "escalate"  # pyydä asiantuntija-arvio
    RETURN_FROM_EXPERT = "return_from_expert"
    APPROVE = "approve"
    REJECT = "reject"
    REVISE = "revise"  # muokkaus hyväksynnän jälkeen mitätöi hyväksynnän
    MARK_SENT = "mark_sent"
    MARK_SEND_FAILED = "mark_send_failed"
    RETRY_SEND = "retry_send"
    CLOSE = "close"
    CANCEL = "cancel"
    REOPEN = "reopen"  # uudelleen avaus kirjataan tapahtumana, ei omana tilana


_MANAGERS = frozenset({Role.PROPERTY_MANAGER, Role.BOARD_CHAIR})
_BOARD = frozenset({Role.PROPERTY_MANAGER, Role.BOARD_CHAIR, Role.BOARD_MEMBER, Role.TREASURER})
_ANY_MEMBER = frozenset(Role) - {Role.EXTERNAL_EXPERT}


@dataclass(frozen=True)
class Transition:
    action: CaseAction
    source: CaseStatus
    target: CaseStatus
    allowed_roles: frozenset[Role]
    # Asian luoja saa tehdä siirtymän roolistaan riippumatta
    # (esim. osakas lähettää oman luonnoksensa).
    creator_allowed: bool = False


S = CaseStatus
A = CaseAction

TRANSITIONS: tuple[Transition, ...] = (
    Transition(A.SUBMIT, S.DRAFT, S.IN_REVIEW, _BOARD, creator_allowed=True),
    Transition(A.REQUEST_INFO, S.IN_REVIEW, S.AWAITING_INFO, _BOARD),
    Transition(A.PROVIDE_INFO, S.AWAITING_INFO, S.IN_REVIEW, _BOARD, creator_allowed=True),
    Transition(A.ESCALATE, S.IN_REVIEW, S.ESCALATED, _MANAGERS),
    Transition(A.RETURN_FROM_EXPERT, S.ESCALATED, S.IN_REVIEW, _MANAGERS),
    Transition(A.APPROVE, S.IN_REVIEW, S.APPROVED, _MANAGERS),
    Transition(A.REJECT, S.IN_REVIEW, S.REJECTED, _MANAGERS),
    Transition(A.REVISE, S.APPROVED, S.DRAFT, _MANAGERS),
    Transition(A.MARK_SENT, S.APPROVED, S.SENT, _MANAGERS),
    Transition(A.MARK_SEND_FAILED, S.APPROVED, S.SEND_FAILED, _MANAGERS),
    Transition(A.RETRY_SEND, S.SEND_FAILED, S.APPROVED, _MANAGERS),
    Transition(A.CLOSE, S.SENT, S.CLOSED, _MANAGERS),
    Transition(A.CLOSE, S.REJECTED, S.CLOSED, _MANAGERS),
    Transition(A.CANCEL, S.DRAFT, S.CANCELLED, _MANAGERS, creator_allowed=True),
    Transition(A.CANCEL, S.AWAITING_INFO, S.CANCELLED, _MANAGERS, creator_allowed=True),
    Transition(A.CANCEL, S.IN_REVIEW, S.CANCELLED, _MANAGERS),
    Transition(A.CANCEL, S.ESCALATED, S.CANCELLED, _MANAGERS),
    Transition(A.REOPEN, S.CLOSED, S.IN_REVIEW, _MANAGERS),
    Transition(A.REOPEN, S.CANCELLED, S.DRAFT, _MANAGERS),
)

_INDEX: dict[tuple[CaseAction, CaseStatus], Transition] = {
    (t.action, t.source): t for t in TRANSITIONS
}


class TransitionError(Exception):
    """Siirtymä ei ole sallittu nykyisessä tilassa."""


class TransitionForbidden(Exception):
    """Käyttäjän roolilla ei ole oikeutta siirtymään."""


def _role_permits(t: Transition, roles: frozenset[Role], is_creator: bool) -> bool:
    return bool(roles & t.allowed_roles) or (
        t.creator_allowed and is_creator and bool(roles & _ANY_MEMBER)
    )


def resolve_transition(
    status: CaseStatus, action: CaseAction, roles: frozenset[Role], *, is_creator: bool
) -> Transition:
    transition = _INDEX.get((action, status))
    if transition is None:
        raise TransitionError(f"Toiminto {action} ei ole sallittu tilassa {status}")
    if not _role_permits(transition, roles, is_creator):
        raise TransitionForbidden(f"Roolilla ei ole oikeutta toimintoon {action}")
    return transition


def available_actions(
    status: CaseStatus, roles: frozenset[Role], *, is_creator: bool
) -> list[CaseAction]:
    return [
        t.action for t in TRANSITIONS if t.source == status and _role_permits(t, roles, is_creator)
    ]
