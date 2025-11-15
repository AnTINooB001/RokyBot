# bot/middlewares/ban_check.py

import logging
from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.db.repository import Repository


class BanCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """
        Проверяет, заблокирован ли пользователь.
        Самостоятельно создает КОРОТКОЖИВУЩУЮ сессию для проверки.
        """
        user = data.get("event_from_user")
        session_maker: async_sessionmaker = data.get("session_maker")
        
        # Если это событие не от пользователя, или нет фабрики сессий - пропускаем
        if not user or not session_maker:
            return await handler(event, data)
        
        is_banned = False
        # --- ОТКРЫЛ БАЗУ ---
        async with session_maker() as session:
            repo = Repository(session)
            db_user = await repo.get_user_by_tg_id(user.id)
            if db_user and db_user.is_banned:
                is_banned = True
        # --- СРАЗУ ЖЕ ЗАКРЫЛ БАЗУ ---
        
        if is_banned:
            logging.info(f"Ignoring update from banned user {user.id}")
            return
        
        # Если пользователь не забанен, просто вызываем следующий обработчик.
        # Этот следующий обработчик (например, start_handler) уже сам откроет
        # СВОЕ СОБСТВЕННОЕ, НОВОЕ соединение, когда оно ему понадобится.
        return await handler(event, data)