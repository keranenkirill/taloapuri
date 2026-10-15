from enum import StrEnum


class Role(StrEnum):
    """Yhtiökohtainen rooli. Yksi käyttäjä voi olla eri roolissa eri yhtiöissä."""

    PROPERTY_MANAGER = "property_manager"  # isännöitsijä
    BOARD_CHAIR = "board_chair"  # hallituksen puheenjohtaja
    BOARD_MEMBER = "board_member"  # hallituksen jäsen
    TREASURER = "treasurer"  # rahastonhoitaja
    SHAREHOLDER = "shareholder"  # osakas
    RESIDENT = "resident"  # asukas (esim. vuokralainen)
    EXTERNAL_EXPERT = "external_expert"  # ulkopuolinen asiantuntija (tapauskohtainen, myöhemmin)


ROLE_LABELS_FI: dict[Role, str] = {
    Role.PROPERTY_MANAGER: "Isännöitsijä",
    Role.BOARD_CHAIR: "Hallituksen puheenjohtaja",
    Role.BOARD_MEMBER: "Hallituksen jäsen",
    Role.TREASURER: "Rahastonhoitaja",
    Role.SHAREHOLDER: "Osakas",
    Role.RESIDENT: "Asukas",
    Role.EXTERNAL_EXPERT: "Ulkopuolinen asiantuntija",
}

# Isännöitsijän oikeudet: jäsenten ja huoneistojen hallinta. Sama lista on migraatiossa 0002.
MANAGER_ROLES: frozenset[Role] = frozenset({Role.PROPERTY_MANAGER, Role.BOARD_CHAIR})

# Roolit, joita isännöitsijä voi lisätä ja päättää (muut roolit kutsuketjulla myöhemmin).
MANAGEABLE_ROLES: frozenset[Role] = frozenset({Role.SHAREHOLDER, Role.RESIDENT})

# Roolit, jotka näkevät kaikki yhtiön asiat. Muut näkevät vain itse luomansa.
# Sama lista on RLS-politiikassa (migrations/versions/0001_tenancy_core.py) – pidä ne samana.
ROLES_SEEING_ALL_CASES: frozenset[Role] = frozenset(
    {Role.PROPERTY_MANAGER, Role.BOARD_CHAIR, Role.BOARD_MEMBER, Role.TREASURER}
)
