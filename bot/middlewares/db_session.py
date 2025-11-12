# bot/middlewares/db_session.py

from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from bot.db.repository import Repository
import logging


class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_pool: async_sessionmaker):
        super().__init__()
        self.session_pool = session_pool

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """
        'Прокидывает' сессию и репозиторий в хендлеры,
        а также управляет транзакциями.
        """
        async with self.session_pool() as session:
            try:
                # Добавляем сессию и репозиторий в данные, доступные в хендлере
                data["session"] = session
                data["repo"] = Repository(session)
                
                # Вызываем следующий обработчик в цепочке
                result = await handler(event, data)
                
                # Если обработчик завершился без ошибок, коммитим транзакцию
                await session.commit()
                
                return result

            except SQLAlchemyError as e:
                # Если произошла любая ошибка SQLAlchemy, откатываем транзакцию
                await session.rollback()
                logging.error(f"Database error during request: {e}")
                # Здесь можно также отправить сообщение пользователю об ошибке
                # (но пока просто логируем)
                raise # Поднимаем исключение дальше, чтобы aiogram его обработал
            
            finally:
                # Сессия закроется автоматически при выходе из `async with`
                pass