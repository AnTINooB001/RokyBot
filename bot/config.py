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
    webapp_host: str = "0.0.0.0"

    # --- Database (SQLite) ---
    # Путь к файлу базы данных SQLite
    db_path: str = "../data/bot.db"

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
        # Генерируем URL для асинхронного подключения к SQLite
        return f"sqlite+aiosqlite:///{self.db_path}"

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