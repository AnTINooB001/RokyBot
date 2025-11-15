# bot/middlewares/admin_check.py

from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
# --- ИЗМЕНЕНИЕ ---
# Импортируем Message и CallbackQuery, чтобы проверять оба
from aiogram.types import TelegramObject, Message, CallbackQuery

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
        Работает и для Message, и для CallbackQuery.
        """
        
        # --- ИЗМЕНЕНИЕ ---
        # Мы будем искать user_id и в сообщениях, и в нажатиях на кнопки
        user_id: int | None = None
        
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        # Если мы не смогли определить пользователя (не тот тип события)
        # ИЛИ пользователь не в списке админов
        if user_id is None or user_id not in config.admin_ids:
            # Если это нажатие кнопки, вежливо ответим, чтобы она "отвисла"
            if isinstance(event, CallbackQuery):
                await event.answer("У вас нет прав для этого действия.", show_alert=True)
            # Прекращаем обработку
            return
        
        # Если проверка пройдена, вызываем следующий обработчик
        return await handler(event, data)