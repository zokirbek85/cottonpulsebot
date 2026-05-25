from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    BOT_TOKEN: str
    ADMIN_IDS: str = ""
    LOG_LEVEL: str = "INFO"
    CACHE_TTL: int = 300
    ALERT_CHECK_INTERVAL: int = 60
    USER_RATE_LIMIT: int = 2
    MAX_ALERTS_PER_USER: int = 10
    ALERT_COOLDOWN_MINUTES: int = 30
    HTTP_PROXY: Optional[str] = None

    # === Multi-source API keys (all optional — enables the respective fetcher) ===
    QUANDL_API_KEY: Optional[str] = None
    USDA_API_KEY: Optional[str] = None
    FRED_API_KEY: Optional[str] = None

    # === Scraping settings ===
    ENABLE_SCRAPING: bool = True
    SCRAPING_TIMEOUT: int = 15

    # === Consensus settings ===
    CONSENSUS_MIN_SOURCES: int = 2
    CONSENSUS_MAX_DEVIATION: float = 5.0   # percent; above this, confidence is penalised
    CONSENSUS_TIMEOUT: float = 25.0        # seconds for the parallel fetch

    @field_validator("BOT_TOKEN")
    @classmethod
    def token_must_not_be_placeholder(cls, v: str) -> str:
        if v == "your_bot_token_here" or not v:
            raise ValueError("BOT_TOKEN must be set to a real Telegram bot token")
        return v

    def admin_id_list(self) -> list[int]:
        if not self.ADMIN_IDS:
            return []
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip().isdigit()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
