# bot/config.py

from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Telegram Bot ---
    bot_token: SecretStr

    # --- Webhook Settings ---
    webhook_secret: str
    webhook_domain: str
    webhook_path: str
    webapp_port: int
    webapp_host: str

    # --- Database ---
    db_user: str
    db_pass: SecretStr
    db_host: str
    db_port: int
    db_name: str

    # --- Admin and Channel ---
    admin_ids_str: str = Field(alias="ADMIN_IDS")
    channel_id: str

    # --- Payouts ---
    wallet_mnemonic: SecretStr
    min_payout_amount: float
    
    # --- Registration Videos ---
    registration_videos_file_ids_str: str = Field(alias="REG_VIDEO_IDS", default="")

    # --- Redis ---
    redis_host: str = "localhost"
    redis_port: int = 6379

    @property
    def admin_ids(self) -> list[int]:
        if self.admin_ids_str:
            return [int(admin_id.strip()) for admin_id in self.admin_ids_str.split(',')]
        return []

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://"
            f"{self.db_user}:{self.db_pass.get_secret_value()}@"
            f"{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_domain}{self.webhook_path}"
        
    @property
    def registration_videos(self) -> list[str]:
        """Парсит строку с file_id в список."""
        if self.registration_videos_file_ids_str:
            return [file_id.strip() for file_id in self.registration_videos_file_ids_str.split(',')]
        return []

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )

config = Settings()