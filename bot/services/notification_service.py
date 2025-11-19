# bot/services/notification_service.py

import asyncio
import logging
from aiogram import Bot
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import config
from bot.db.repository import Repository

async def notification_worker(bot: Bot, session_maker: async_sessionmaker):
    """
    Фоновая задача, которая периодически проверяет очередь видео
    и уведомляет всех администраторов, если есть работа.
    """
    logging.info(f"Notification worker started. Interval: {config.notification_interval} minutes.")
    
    while True:
        # 1. Ждем указанный интервал (переводим минуты в секунды)
        await asyncio.sleep(config.notification_interval * 60)
        
        try:
            async with session_maker() as session:
                repo = Repository(session)
                
                # 2. Проверяем количество видео в очереди
                queue_count = await repo.get_queue_count()
                
                # Если очередь пуста - ничего не делаем, ждем дальше
                if queue_count == 0:
                    continue
                
                # 3. Если видео есть, собираем список получателей
                
                # Получаем обычных админов из БД
                db_admins = await repo.get_all_admins()
                db_admin_ids = [admin.tg_id for admin in db_admins]
                
                # Получаем супер-админов из конфига
                super_admin_ids = config.super_admin_ids
                
                # Объединяем списки и убираем дубликаты (используем set)
                all_admin_ids = set(db_admin_ids + super_admin_ids)
                
                # 4. Отправляем уведомления
                text = (
                    f"🔔 <b>Напоминание для администрации</b>\n\n"
                    f"В очереди на проверку висит <b>{queue_count}</b> видео.\n"
                    f"Пожалуйста, зайдите в админку и проверьте их!"
                )
                
                success_count = 0
                for admin_id in all_admin_ids:
                    try:
                        await bot.send_message(admin_id, text)
                        success_count += 1
                    except Exception as e:
                        # Админ мог заблокировать бота, это нормально
                        logging.warning(f"Failed to send notification to {admin_id}: {e}")
                
                if success_count > 0:
                    logging.info(f"Sent queue notification to {success_count} admins.")

        except Exception as e:
            logging.error(f"Error in notification worker: {e}", exc_info=True)
            # Ждем немного перед повтором, если произошла ошибка (чтобы не спамить логами)
            await asyncio.sleep(60)