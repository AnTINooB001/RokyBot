# bot/config.py

from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Telegram Bot ---
    bot_token: SecretStr

    # --- Webhook Settings ---
    webhook_secret: SecretStr
    webhook_domain: str
    webhook_path: str = "/webhook"
    webapp_port: int = 8081
    webapp_host: str = "" # Пустая строка для лучшей совместимости

    # --- Database (переменные от Amvera) ---
    amvera_pg_host: str
    amvera_pg_port: int
    amvera_pg_db_name: str
    amvera_pg_user: str
    amvera_pg_password: SecretStr

    # --- Admin and Channel ---
    admin_ids_str: str = Field(alias="ADMIN_IDS")
    channel_id: str

    # --- Payouts ---
    wallet_mnemonic: SecretStr
    min_payout_amount: float
    
    # --- Registration Videos ---
    registration_videos_file_ids_str: str = Field(alias="REG_VIDEO_IDS", default="")

    @property
    def admin_ids(self) -> list[int]:
        if self.admin_ids_str:
            return [int(admin_id.strip()) for admin_id in self.admin_ids_str.split(',')]
        return []

    @property
    def database_url(self) -> str:
        # Возвращаем URL для подключения к PostgreSQL
        return (
            f"postgresql+asyncpg://"
            f"{self.amvera_pg_user}:{self.amvera_pg_password.get_secret_value()}@"
            f"{self.amvera_pg_host}:{self.amvera_pg_port}/{self.amvera_pg_db_name}"
        )

    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_domain}{self.webhook_path}"
        
    @property
    def registration_videos(self) -> list[str]:
        if self.registration_videos_file_ids_str:
            return [file_id.strip() for file_id in self.registration_videos_file_ids_str.split(',')]
        return []

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )

config = Settings()