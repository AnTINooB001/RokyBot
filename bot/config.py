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
    
    # --- НОВЫЕ ПОЛЯ ДЛЯ ВИДЕО ---
    # Ожидается строка с путями, разделенными запятой, например: "media/video1.mp4,media/video2.mp4"
    video_paths_str: str = Field(alias="VIDEO_PATHS", default="")

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
    def video_paths(self) -> list[str]:
        """Парсит строку с путями в список."""
        if self.video_paths_str:
            return [path.strip() for path in self.video_paths_str.split(',')]
        return []

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )

config = Settings()