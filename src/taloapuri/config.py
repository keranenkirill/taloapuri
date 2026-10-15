from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TALOAPURI_", env_file=".env", extra="ignore")

    env: Environment = "local"
    database_url: str = "postgresql+psycopg://taloapuri_app:local-dev-only@localhost:5432/taloapuri"
    timezone: str = "Europe/Helsinki"
    # Lakilähteen tarkistus Finlexistä: vähintään näin pitkä tauko saman lain tarkistusten välillä.
    law_check_cooldown_seconds: int = 300

    # Tekoäly (ks. docs/adr/0005). Pois päältä oletuksena. API-avain luetaan .env-tiedostosta
    # tai ympäristöstä nimellä ANTHROPIC_API_KEY (ilman TALOAPURI_-etuliitettä).
    ai_enabled: bool = False
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    ai_model: str = "claude-haiku-5-5"
    ai_effort: Literal["low", "medium", "high"] = "medium"
    ai_timeout_seconds: float = 60.0
    ai_max_output_tokens: int = 2000
    ai_max_output_tokens_long: int = 4000  # tarjousvertailu ja luonnokset
    ai_monthly_budget_usd: float = 5.0  # per taloyhtiö
    ai_daily_messages_per_user: int = 20
    # Hinta-arvio kustannusseurantaan (USD / miljoona tokenia), Claude Haiku 5.5.
    ai_input_usd_per_mtok: float = 0.10
    ai_output_usd_per_mtok: float = 0.50

    @property
    def dev_auth_enabled(self) -> bool:
        """Kehityskirjautuminen on sallittu vain paikallisesti ja testeissä.

        Oikea OIDC-kirjautuminen toteutetaan vaiheessa 1 (ks. docs/adr/0003).
        """
        return self.env in ("local", "test")


@lru_cache
def get_settings() -> Settings:
    return Settings()
