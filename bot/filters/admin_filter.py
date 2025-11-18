from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery, TelegramObject
from bot.config import config

class IsAdmin(BaseFilter):
    """
    Проверяет, является ли пользователь администратором (обычным ИЛИ супер-админом).
    """
    async def __call__(self, obj: TelegramObject) -> bool:
        user_id = None
        if isinstance(obj, Message):
            user_id = obj.from_user.id
        elif isinstance(obj, CallbackQuery):
            user_id = obj.from_user.id
            
        if user_id is None:
            return False
            
        # Человек админ, если он есть В ЛЮБОМ из двух списков
        is_admin_or_super = (user_id in config.admin_ids) or (user_id in config.super_admin_ids)
        
        return is_admin_or_super

class IsSuperAdmin(BaseFilter):
    """
    Проверяет, является ли пользователь СУПЕР-администратором (только список super_admin_ids).
    """
    async def __call__(self, obj: TelegramObject) -> bool:
        user_id = None
        if isinstance(obj, Message):
            user_id = obj.from_user.id
        elif isinstance(obj, CallbackQuery):
            user_id = obj.from_user.id
            
        if user_id is None:
            return False
            
        return user_id in config.super_admin_ids