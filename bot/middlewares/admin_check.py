# bot/middlewares/admin_check.py

from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message

from bot.config import config


class AdminCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """
        Проверяет, является ли пользователь администратором.
        Работает только для типа Message, чтобы не блокировать callback-запросы
        от админов, которые уже вошли в панель.
        """
        # Убеждаемся, что event - это Message и у него есть from_user
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
            # Если ID пользователя нет в списке админов, прекращаем обработку
            if user_id not in config.admin_ids:
                return
        
        # Если проверка пройдена или событие не Message, вызываем следующий обработчик
        return await handler(event, data)