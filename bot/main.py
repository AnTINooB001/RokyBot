# bot/main.py

import asyncio
import logging
import sys
from functools import partial

from aiohttp import web
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from bot.config import config
from bot.db.models import Base
from bot.middlewares.db_session import DbSessionMiddleware
# Импортируем только ГЛАВНЫЕ роутеры
from bot.handlers.admin_handlers import admin_router
from bot.handlers.user_handlers import user_router


async def on_startup(bot: Bot, engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await bot.set_webhook(
        url=config.webhook_url,
        secret_token=config.webhook_secret
    )
    logging.info("Webhook has been set. Database tables created.")


async def on_shutdown(bot: Bot) -> None:
    await bot.delete_webhook()
    logging.info("Webhook has been deleted.")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        stream=sys.stdout,
    )

    engine = create_async_engine(config.database_url, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    bot = Bot(token=config.bot_token.get_secret_value(), parse_mode=ParseMode.HTML)
    dp = Dispatcher()

    dp.update.middleware(DbSessionMiddleware(session_pool=session_maker))

    dp.startup.register(partial(on_startup, engine=engine))
    dp.shutdown.register(on_shutdown)

    # --- ИЗМЕНЕНИЕ: Регистрируем только главные роутеры ---
    dp.include_router(admin_router)
    dp.include_router(user_router) # user_router уже содержит в себе throttled_router
    
    app = web.Application()
    
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=config.webhook_secret,
    )
    
    webhook_requests_handler.register(app, path=config.webhook_path)
    
    setup_application(app, dp, bot=bot)
    
    logging.info(f"Starting web server on {config.webapp_host}:{config.webapp_port}")
    web.run_app(app, host=config.webapp_host, port=config.webapp_port)


if __name__ == "__main__":
    main()