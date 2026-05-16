from __future__ import annotations

from functools import lru_cache
import os


class Settings:
    def __init__(self) -> None:
        local_dev_origins = [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
        ]
        raw_origins = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost,http://127.0.0.1")
        configured_origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
        self.cors_allow_origins = list(dict.fromkeys([*configured_origins, *local_dev_origins]))
        self.cors_allow_credentials = os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() in {"1", "true", "yes", "on"}
        self.cors_expose_headers = ["Content-Disposition"]

        if self.cors_allow_credentials and "*" in self.cors_allow_origins:
            raise ValueError("Invalid CORS configuration: cannot use wildcard origins with credentials enabled")


@lru_cache
def get_settings() -> Settings:
    return Settings()
