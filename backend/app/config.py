from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_name: str = "RideX API"
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    frontend_url: str = "http://localhost:5173"
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    mongodb_uri: str = ""
    mongodb_database: str = "ridex"
    demo_mode: bool = True
    seed_demo_data: bool = True
    seed_admin_email: str = "admin@example.com"
    seed_admin_password: SecretStr = SecretStr("")
    seed_super_admin_email: str = "owner@example.com"
    seed_super_admin_password: SecretStr = SecretStr("")
    seed_customer_email: str = "ridex.customer@mailinator.com"
    seed_customer_password: SecretStr = SecretStr("")
    seed_driver_email: str = "ridex.driver@mailinator.com"
    seed_driver_password: SecretStr = SecretStr("")

    secret_key: str = "development-only-change-me"
    access_token_minutes: int = 480

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_api_url: str = "https://api.razorpay.com/v1"
    allow_test_payments: bool = False

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "support@ridex.example"
    smtp_from_name: str = "RideX"
    smtp_use_tls: bool = True
    email_delivery_enabled: bool = True
    email_test_redirect_to: str = ""
    email_redirect_disposable_domains: bool = True
    email_worker_interval_seconds: int = 5

    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_production(self) -> "Settings":
        if self.app_env == "production":
            if self.demo_mode or not self.mongodb_uri:
                raise ValueError("Production requires MongoDB Atlas and DEMO_MODE=false")
            if self.secret_key == "development-only-change-me":
                raise ValueError("Production requires a strong SECRET_KEY")
            if self.seed_demo_data:
                raise ValueError("Production must not seed test accounts")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
