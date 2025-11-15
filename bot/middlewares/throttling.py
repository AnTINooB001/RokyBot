import time
import json
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List

from aiogram import BaseMiddleware
from aiogram.types import Message
from cachetools import TTLCache

# Кэш теперь будет хранить список временных меток (timestamps) для каждого пользователя.
# TTL (Time-To-Live) - 3600 секунд (1 час).
# Это значит, что запись о пользователе будет удалена через час после его ПОСЛЕДНЕГО сообщения.
cache = TTLCache(maxsize=10_000, ttl=3600)

# Загружаем тексты прямо в middleware, чтобы оно могло отправлять сообщения
BASE_DIR = Path(__file__).resolve().parent.parent.parent
with open(BASE_DIR / 'texts.json', 'r', encoding='utf-8') as f:
    texts = json.load(f)


class RateLimiterMiddleware(BaseMiddleware):
    def __init__(self, limit: int = 10, period: int = 3600):
        self.limit = limit  # Максимальное количество сообщений
        self.period = period  # Временной период в секундах (3600 = 1 час)

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        # Проверяем, что событие - это Message и что у него есть пользователь
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
            current_time = time.time()
            
            # Получаем список временных меток пользователя из кэша (или пустой список, если его нет)
            timestamps: List[float] = cache.get(user_id, [])
            
            # Отфильтровываем временные метки, которые старше, чем наш период (1 час)
            # Это реализует "скользящее окно"
            recent_timestamps = [ts for ts in timestamps if current_time - ts < self.period]
            
            # Если количество недавних сообщений превышает или равно лимиту
            if len(recent_timestamps) >= self.limit:
                # Отправляем пользователю сообщение о превышении лимита
                text = texts['user_panel']['rate_limit_exceeded'].format(limit=self.limit)
                await event.answer(text)
                # И не пропускаем сообщение дальше
                return
            
            # Добавляем текущую временную метку в список
            recent_timestamps.append(current_time)
            # Обновляем кэш для этого пользователя
            cache[user_id] = recent_timestamps
            
            # Пропускаем событие дальше, к хендлеру
            return await handler(event, data)
        
        # Если это не сообщение от пользователя, просто пропускаем
        return await handler(event, data)