# bot/middlewares/ban_check.py

import logging
from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

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
        Если да, то просто прекращает обработку события.
        """
        # Получаем пользователя из данных, которые aiogram любезно предоставляет
        user = data.get("event_from_user")
        
        # Если это событие не от пользователя, или нет репозитория - пропускаем
        if not user or "repo" not in data:
            return await handler(event, data)
            
        repo: Repository = data["repo"]
        db_user = await repo.get_user_by_tg_id(user.id)
        
        # Если пользователь есть в БД и он забанен
        if db_user and db_user.is_banned:
            logging.info(f"Ignoring update from banned user {user.id}")
            # Просто возвращаем None, чтобы остановить цепочку обработки
            return
        
        # Если все в порядке, вызываем следующий обработчик
        return await handler(event, data)