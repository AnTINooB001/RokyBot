# bot/middlewares/ban_check.py

import logging
from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from cachetools import TTLCache
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.db.models import User

# Кэш хранит ID пользователей и их статус бана.
# maxsize=10000: помним до 10 тысяч пользователей
# ttl=300: забываем запись через 5 минут (чтобы подтянуть изменения из БД, если забанили через БД напрямую)
# Если вы баните только через бота, TTL можно сделать больше.
cache = TTLCache(maxsize=10_000, ttl=300)

class BanCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        
        # Получаем пользователя из события
        user = None
        if isinstance(event, (Message, CallbackQuery)):
            user = event.from_user
            
        if not user:
            return await handler(event, data)

        # 1. БЫСТРАЯ ПРОВЕРКА: Смотрим в кэш
        # Если мы точно знаем, что он забанен - сразу стоп.
        is_banned_cached = cache.get(user.id)
        
        if is_banned_cached is True:
            # Пользователь в кэше как забаненный - игнорируем
            return

        # Если в кэше записи нет (или False), или срок истек - проверяем базу.
        # Но чтобы не долбить базу каждым сообщением "чистого" юзера,
        # мы должны кэшировать и "чистых" тоже!
        
        if is_banned_cached is None:
            session_maker: async_sessionmaker = data.get("session_maker")
            async with session_maker() as session:
                # Делаем быстрый запрос, выбираем только поле is_banned
                result = await session.execute(
                    select(User.is_banned).where(User.tg_id == user.id)
                )
                is_banned_db = result.scalar()
                
                # Если пользователя вообще нет в базе - он не забанен (None -> False)
                if is_banned_db is None:
                    is_banned_db = False
                
                # Сохраняем результат в кэш
                cache[user.id] = is_banned_db
                
                if is_banned_db:
                    return

        # Если мы здесь, значит пользователь не забанен
        return await handler(event, data)