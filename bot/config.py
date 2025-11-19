# bot/config.py

from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import logging


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
    super_admin_ids_str: str = Field(alias="SUPER_ADMIN_IDS", default="") 
    channel_id: str

    # --- Payouts ---
    wallet_mnemonic: SecretStr
    min_payout_amount: float
    payout_per_video: float
    
    # --- Registration Videos ---
    registration_videos_file_ids_str: str = Field(alias="REG_VIDEO_IDS", default="")
    
    # --- Notifications ---
    # Интервал проверки очереди видео (в минутах). По умолчанию 60.
    notification_interval: int = Field(alias="NOTIFICATION_INTERVAL", default=60)

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
    
    @property
    def super_admin_ids(self) -> list[int]:
        if self.super_admin_ids_str:
            return [int(id_.strip()) for id_ in self.super_admin_ids_str.split(',') if id_.strip()]
        return []

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )

config = Settings()
logging.info(f"password: {config.amvera_pg_password.get_secret_value()}")