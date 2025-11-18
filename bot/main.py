# bot/main.py

import asyncio
import logging
import os
import sys
from functools import partial

from aiohttp import web
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text  # <-- ДОБАВЛЕН ИМПОРТ

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from bot.config import config
from bot.db.models import Base
from bot.middlewares.ban_check import BanCheckMiddleware
from bot.handlers.admin_handlers import admin_router
from bot.handlers.user_handlers import user_router



async def on_startup(bot: Bot, engine) -> None:

    logging.info("Warming up database connection pool...")
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logging.info("Database connection pool is ready.")
    except Exception as e:
        # --- НАЧАЛО ИЗМЕНЕНИЯ ---
        logging.critical(f"FATAL: Could not connect to the database on startup: {e}", exc_info=True)
        logging.critical("Application is shutting down due to a critical database connection error.")
        # Немедленно останавливаем приложение с кодом ошибки 1
        sys.exit(1)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    await bot.delete_webhook(drop_pending_updates=True)
    
    await bot.set_webhook(
        url=config.webhook_url,
        secret_token=config.webhook_secret.get_secret_value()
    )
    logging.info("Webhook has been set. Pending updates dropped.")


async def on_shutdown(bot: Bot) -> None:
    await bot.delete_webhook()
    logging.info("Webhook has been deleted.")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        stream=sys.stdout,
    )

    # ВОЗВРАЩАЕМ НАСТРОЙКИ ПУЛА СОЕДИНЕНИЙ ДЛЯ POSTGRESQL
    engine = create_async_engine(
        config.database_url,
        echo=False,
        pool_size=20,
        max_overflow=10,
        pool_recycle=3600
    )
    
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    bot = Bot(token=config.bot_token.get_secret_value(), parse_mode=ParseMode.HTML)
    dp = Dispatcher()
    
    dp["session_maker"] = session_maker

    user_router.message.middleware(BanCheckMiddleware())
    user_router.callback_query.middleware(BanCheckMiddleware())
    
    dp.startup.register(partial(on_startup, engine=engine))
    dp.shutdown.register(on_shutdown)
    
    dp.include_router(admin_router)
    dp.include_router(user_router)
    
    app = web.Application()
    
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=config.webhook_secret.get_secret_value(),
    )
    
    webhook_requests_handler.register(app, path=config.webhook_path)
    
    setup_application(app, dp, bot=bot)
    
    logging.info(f"Starting web server on {config.webapp_host}:{config.webapp_port}")
    web.run_app(app, host=config.webapp_host, port=config.webapp_port)


if __name__ == "__main__":
    main()