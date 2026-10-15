"""Asiatyyppikohtaiset lomaketiedot (tallennetaan cases.details-kenttään)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Details(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DamageDetails(_Details):
    """Vahinkoilmoitus."""

    location_text: str = Field(default="", max_length=200)  # esim. "keittiö, tiskipöydän alla"
    ongoing: Literal["yes", "no", "unknown"] = "unknown"  # jatkuuko vahinko yhä


class TenderDetails(_Details):
    """Tarjouspyyntö. budget_note on vain hallituksen sisäinen eikä mene luonnokseen."""

    target: str = Field(min_length=1, max_length=200)  # esim. "Porrashuoneiden maalaus"
    scope: str = Field(min_length=1, max_length=4000)
    location_text: str = Field(default="", max_length=200)
    schedule_start: date | None = None
    schedule_end: date | None = None
    offers_due: date | None = None
    requirements: str = Field(default="", max_length=2000)
    budget_note: str = Field(default="", max_length=500)
    draft_text: str = Field(default="", max_length=20000)
    draft_saved_by: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _schedule_order(self) -> "TenderDetails":
        if self.schedule_start and self.schedule_end and self.schedule_end < self.schedule_start:
            raise ValueError("Työn päättymispäivä ei voi olla ennen aloituspäivää.")
        return self


class EmptyDetails(_Details):
    pass


DETAILS_MODELS: dict[str, type[_Details]] = {
    "damage": DamageDetails,
    "tender_request": TenderDetails,
    "maintenance_responsibility": EmptyDetails,
    "renovation_notice": EmptyDetails,
}
