"""Application configuration.

All configuration is sourced from environment variables (or a local ``.env``
file) via :class:`Settings`. Nothing in this repository may hardcode a
credential -- see ``docs/limitations.md`` for the incident that motivated
this rule.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime settings for the Ocean Intelligence Platform backend."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- Application -------------------------------------------------------
    app_name: str = "Ocean Intelligence Platform"
    app_version: str = "0.1.0"
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "console"

    # -- Demo mode ---------------------------------------------------------
    # When true the platform serves clearly-labelled synthetic data so the
    # dashboard is demonstrable without GEE / model credentials. Every payload
    # produced in demo mode carries data_origin="SIMULATED".
    demo_mode: bool = True

    # -- Database ----------------------------------------------------------
    # Anchored to the repository root rather than the working directory, so
    # the same database is used whether the app is started from ``backend/``,
    # the repo root, or a container.
    database_url: str = f"sqlite:///{(REPO_ROOT / 'data' / 'oip.db').as_posix()}"
    db_echo: bool = False

    # -- CORS --------------------------------------------------------------
    # Comma-separated list. Defaults to local dev origins, never "*".
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # -- Google Earth Engine -----------------------------------------------
    gee_enabled: bool = False
    gee_project_id: str | None = None
    gee_service_account: str | None = None
    google_application_credentials: str | None = None

    # -- India water intelligence -----------------------------------------
    # Comma-separated state codes (e.g. "MH,DL") to ingest from CPCB/NWDP at
    # start-up when the water tables are empty. Empty disables it. Exists for
    # ephemeral deployments: a container whose SQLite file is lost on restart
    # rebuilds its water data from the real source instead of serving an empty
    # map. It runs in a background thread so health checks pass immediately.
    water_bootstrap_states: str = ""

    # Where downloaded reference files (boundary GeoJSON) are cached. In the
    # container the repo-root default resolves to an unwritable path, so the
    # image points this at the data volume.
    water_cache_dir: str = str(REPO_ROOT / "data" / "raw")

    # -- Vision ------------------------------------------------------------
    detector_backend: Literal["yolo", "mock"] = "mock"
    yolo_model_path: str | None = None
    detection_confidence_threshold: float = 0.25

    # -- SAR dark-formation detection --------------------------------------
    # Backscatter (dB) below which a cell is treated as a candidate dark
    # formation. -22 dB is a conservative open-ocean threshold; see
    # docs/ai-pipeline.md for the justification and its limitations.
    sar_dark_threshold_db: float = -22.0
    # Wind speed (m/s) below which dark formations are ambiguous because of
    # low-wind look-alikes. Applied only when wind data is available.
    sar_min_wind_speed_ms: float = 3.0

    # -- LLM ---------------------------------------------------------------
    llm_provider: Literal["none", "gemini", "openai", "anthropic"] = "none"
    llm_model: str | None = None
    gemini_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # -- Ingestion ---------------------------------------------------------
    ingest_lookback_days: int = 10
    ingest_scale_m: int = 500

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list, with blanks stripped."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def gee_configured(self) -> bool:
        """True when enough is set to attempt a real Earth Engine session."""
        return bool(
            self.gee_enabled
            and self.gee_project_id
            and self.gee_service_account
            and self.google_application_credentials
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()


settings = get_settings()
