# bot/filters/admin_filter.py

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery, TelegramObject
from bot.config import config
from cachetools import TTLCache
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy import select
from bot.db.models import User

# Кэш для админов (хранит True/False). TTL 5 минут.
admin_cache = TTLCache(maxsize=1000, ttl=300)

class IsAdmin(BaseFilter):
    async def __call__(self, obj: TelegramObject, session_maker: async_sessionmaker = None) -> bool:
        user_id = None
        if isinstance(obj, (Message, CallbackQuery)):
            user_id = obj.from_user.id
        
        if user_id is None: return False

        # 1. Сначала проверяем Супер-Админов (из конфига)
        if user_id in config.super_admin_ids:
            return True
        
        cached_status = admin_cache.get(user_id)
        if cached_status is not None:
            return cached_status

        # Если в кэше нет - идем в базу
        if session_maker:
            async with session_maker() as session:
                result = await session.execute(select(User.is_admin).where(User.tg_id == user_id))
                is_admin_db = result.scalar() or False
                admin_cache[user_id] = is_admin_db
                return is_admin_db
        
        return False

class IsSuperAdmin(BaseFilter):
    async def __call__(self, obj: TelegramObject) -> bool:
        user_id = obj.from_user.id if isinstance(obj, (Message, CallbackQuery)) else None
        return user_id in config.super_admin_ids