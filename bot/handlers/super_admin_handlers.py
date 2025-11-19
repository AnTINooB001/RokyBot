# bot/handlers/super_admin_handlers.py

import asyncio
import json
import logging
import csv
import tempfile
import os
from pathlib import Path
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

from bot.db.models import User, Payout, PayoutStatus
from bot.db.repository import Repository
from bot.keyboards import admin_keyboards as kb
from bot.services.coingecko_service import coingecko_service
from bot.services.ton_service import ton_service
from bot.config import config
from bot.filters.admin_filter import IsSuperAdmin, admin_cache
from bot.handlers.admin_handlers import show_admin_panel

BASE_DIR = Path(__file__).resolve().parent.parent.parent
with open(BASE_DIR / 'texts.json', 'r', encoding='utf-8') as f:
    texts = json.load(f)

class BonusFSM(StatesGroup):
    waiting_for_username = State()
    waiting_for_amount = State()

class AddAdminFSM(StatesGroup):
    waiting_for_username = State()

super_admin_router = Router()

if not __debug__ :
    super_admin_router.message.filter(IsSuperAdmin())
    super_admin_router.callback_query.filter(IsSuperAdmin())


# ==============================================================================
# LOGS EXPORT LOGIC
# ==============================================================================

@super_admin_router.callback_query(F.data == "download_logs")
async def download_logs_handler(callback: CallbackQuery, session_maker: async_sessionmaker):
    await callback.answer("⏳ Генерирую отчет...")
    
    async with session_maker() as session:
        repo = Repository(session)
        logs = await repo.get_all_logs()
    
    if not logs:
        await callback.message.answer("Логи пусты.")
        return

    temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', encoding='utf-8-sig', newline='')
    try:
        writer = csv.writer(temp_file, delimiter=';')
        writer.writerow(['ID', 'Time (UTC)', 'Admin ID', 'Admin Username', 'Action', 'Details'])
        for log in logs:
            created_at_str = log.created_at.strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow([log.id, created_at_str, log.actor_tg_id, log.actor_username or "", log.action, log.details or ""])
        temp_file.close()
        
        input_file = FSInputFile(temp_file.name, filename=f"logs_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.csv")
        await callback.message.answer_document(document=input_file, caption="📊 Полный лог действий.")
    except Exception as e:
        logging.error(f"Error exporting logs: {e}", exc_info=True)
        await callback.message.answer("❌ Ошибка при создании файла.")
    finally:
        if os.path.exists(temp_file.name):
            os.remove(temp_file.name)

# ==============================================================================
# ADMIN MANAGEMENT
# ==============================================================================

@super_admin_router.callback_query(F.data == "admin_manage_menu")
async def admin_manage_menu_handler(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "👮 <b>Панель управления администраторами</b>\n\n"
        "Здесь вы можете назначать новых админов или снимать права с существующих.",
        reply_markup=kb.get_admin_management_menu()
    )
    await callback.answer()

@super_admin_router.callback_query(kb.AdminManageCallback.filter(F.action == "list"))
async def list_admins_handler(callback: CallbackQuery, session_maker: async_sessionmaker):
    await callback.message.delete()
    async with session_maker() as session:
        repo = Repository(session)
        admins = await repo.get_all_admins()
    
    if not admins:
        text = "📋 Список назначенных админов пуст."
    else:
        text = "📋 <b>Список назначенных админов:</b>\n<i>Нажмите на кнопку с пользователем, чтобы лишить его прав.</i>"
        
    await callback.message.answer(text, reply_markup=kb.get_admins_list_keyboard(admins))
    await callback.answer()

@super_admin_router.callback_query(kb.AdminManageCallback.filter(F.action == "remove"))
async def remove_admin_handler(callback: CallbackQuery, callback_data: kb.AdminManageCallback, session_maker: async_sessionmaker):
    user_db_id = callback_data.user_id
    await callback.message.delete()
    
    async with session_maker() as session:
        repo = Repository(session)
        user = await repo.session.get(User, user_db_id)
        
        if user:
            await repo.set_admin_status(user.id, False)
            await repo.log_action(
                actor_tg_id=callback.from_user.id,
                actor_username=callback.from_user.username,
                action="ADMIN_REMOVED",
                details=f"Removed admin rights from user {user.tg_id} (@{user.username})"
            )
            await session.commit()
            admin_cache[user.tg_id] = False
            
            await callback.answer(f"Пользователь {user.username or user.tg_id} разжалован.", show_alert=True)
            try: await callback.bot.send_message(user.tg_id, "📉 Вы были лишены прав администратора.")
            except: pass
            
            admins = await repo.get_all_admins()
            await callback.message.answer("Список обновлен:", reply_markup=kb.get_admins_list_keyboard(admins))
        else:
            await callback.answer("Пользователь не найден.", show_alert=True)
            await callback.message.answer("Меню:", reply_markup=kb.get_admin_management_menu())

@super_admin_router.callback_query(kb.AdminManageCallback.filter(F.action == "add"))
async def add_admin_start_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    msg = await callback.message.answer(
        "Введите <b>@username</b> или <b>Telegram ID</b> пользователя, которого хотите сделать админом:",
        reply_markup=kb.get_admin_cancel_keyboard()
    )
    await state.update_data(main_msg_id=msg.message_id)
    await state.set_state(AddAdminFSM.waiting_for_username)
    await callback.answer()

@super_admin_router.message(AddAdminFSM.waiting_for_username)
async def add_admin_finish_handler(message: Message, state: FSMContext, session_maker: async_sessionmaker):
    input_data = message.text.lstrip('@').strip()
    data = await state.get_data()
    main_msg_id = data.get("main_msg_id")
    
    await message.delete()
    if main_msg_id:
        try: await message.bot.delete_message(message.chat.id, main_msg_id)
        except: pass
    
    async with session_maker() as session:
        repo = Repository(session)
        user = None
        if input_data.isdigit():
            user = await repo.get_user_by_tg_id(int(input_data))
        if not user:
            user = await repo.get_user_by_username(input_data)
            
        if not user:
            new_msg = await message.answer(
                f"🚫 Пользователь <code>{input_data}</code> не найден.\nОн должен сначала запустить бота.",
                reply_markup=kb.get_admin_cancel_keyboard()
            )
            await state.update_data(main_msg_id=new_msg.message_id)
            return
            
        if user.is_admin:
            new_msg = await message.answer(
                f"⚠️ {user.username} уже является админом.",
                reply_markup=kb.get_admin_cancel_keyboard()
            )
            await state.update_data(main_msg_id=new_msg.message_id)
            return

        await repo.set_admin_status(user.id, True)
        await repo.log_action(
            actor_tg_id=message.from_user.id,
            actor_username=message.from_user.username,
            action="ADMIN_ADDED",
            details=f"Granted admin rights to {user.tg_id} (@{user.username})"
        )
        await session.commit()
        admin_cache[user.tg_id] = True
    
    await state.clear()
    await message.answer(
        f"✅ Пользователь <b>{user.username or user.tg_id}</b> успешно назначен администратором!",
        reply_markup=kb.get_admin_management_menu()
    )
    try: await message.bot.send_message(user.tg_id, "🎉 Вам выданы права администратора! Введите /start для входа в панель.")
    except: pass


# ==============================================================================
# PAYOUT LOGIC (HISTORY PRESERVED)
# ==============================================================================

@super_admin_router.callback_query(F.data == "get_payout_request")
async def get_payout_request_handler(callback: CallbackQuery, session_maker: async_sessionmaker):
    await callback.message.delete()
    payout_data = None
    async with session_maker() as session:
        repo = Repository(session)
        payout = await repo.get_oldest_payout_request()
        if payout:
            payout_data = {"id": payout.id, "amount": payout.amount, "wallet": payout.wallet, "username": payout.user.username, "tg_id": payout.user.tg_id}

    if not payout_data:
        await callback.answer(texts['admin_panel']['payout_queue_empty'], show_alert=True)
        await show_admin_panel(callback.bot, callback.message.chat.id, session_maker)
        return

    username = f"@{payout_data['username']}" if payout_data['username'] else f"ID: {payout_data['tg_id']}"
    text = texts['admin_panel']['payout_review_request'].format(username=username, amount=payout_data['amount'], wallet=payout_data['wallet'])
    await callback.message.answer(text, reply_markup=kb.get_payout_review_keyboard(payout_id=payout_data['id']))
    await callback.answer()


@super_admin_router.callback_query(kb.PayoutCallback.filter(F.action == "confirm"))
async def confirm_payout_handler(callback: CallbackQuery, callback_data: kb.PayoutCallback, bot: Bot, session_maker: async_sessionmaker):
    await callback.message.edit_text(texts['admin_panel']['payout_processing'])
    
    payout_data = None
    async with session_maker() as session:
        repo = Repository(session)
        payout = await repo.session.get(Payout, callback_data.payout_id, options=[selectinload(Payout.user)])
        
        if not payout or payout.status != PayoutStatus.PENDING:
            await callback.message.edit_text(texts['admin_panel']['error_already_processed'])
            # Возвращаем меню
            await show_admin_panel(bot, callback.message.chat.id, session_maker)
            return
        payout_data = {"id": payout.id, "wallet": payout.wallet, "amount": payout.amount, "user_tg_id": payout.user.tg_id, "username": payout.user.username}

    rate = coingecko_service.get_ton_to_usd_rate()
    if rate <= 0:
        await callback.message.edit_text(texts['admin_panel']['payout_error_api'])
        await show_admin_panel(bot, callback.message.chat.id, session_maker)
        return
    
    amount_ton = payout_data['amount'] / rate
    tx_hash = None
    try:
        tx_hash = await ton_service.send_transaction(to_address=payout_data['wallet'], amount_ton=amount_ton, comment="Rocky Clips Payout")
    except Exception as e:
        logging.error(f"Payout transaction error: {e}", exc_info=True)

    user_to_notify_id = payout_data['user_tg_id']
    amount_to_notify = payout_data['amount']

    if tx_hash:
        async with session_maker() as session:
            repo = Repository(session)
            await repo.confirm_payout(payout_id=callback_data.payout_id, admin_tg_id=callback.from_user.id, tx_hash=tx_hash)
            await repo.log_action(
                actor_tg_id=callback.from_user.id,
                actor_username=callback.from_user.username,
                action="PAYOUT_CONFIRMED",
                details=f"Payout ID {payout_data['id']} to user {user_to_notify_id}. Amount: ${amount_to_notify} (TX: {tx_hash})"
            )
            await session.commit()
        
        # --- ИЗМЕНЕНИЕ: Редактируем сообщение на "Успех", чтобы оставить в истории ---
        username_label = f"@{payout_data['username']}" if payout_data['username'] else f"ID: {user_to_notify_id}"
        await callback.message.edit_text(
            f"✅ <b>Выплата подтверждена</b>\n"
            f"👤 Юзер: {username_label}\n"
            f"💰 Сумма: {amount_to_notify}$\n"
            f"🔗 TX: <code>{tx_hash}</code>"
        )
        
        try:
            await bot.send_message(user_to_notify_id, texts['user_notifications']['payout_confirmed_user'].format(amount=amount_to_notify, tx_hash=tx_hash))
        except Exception as e:
            await bot.send_message(callback.from_user.id, texts['admin_panel']['error_notify_user_alert'].format(error=e))
    else:
        async with session_maker() as session:
            repo = Repository(session)
            await repo.cancel_payout(payout_id=callback_data.payout_id, admin_tg_id=callback.from_user.id)
            await repo.log_action(
                actor_tg_id=callback.from_user.id,
                actor_username=callback.from_user.username,
                action="PAYOUT_FAILED_TX",
                details=f"Payout ID {payout_data['id']} failed (transaction error)."
            )
            await session.commit()
            
        # Редактируем на ошибку
        await callback.message.edit_text(f"❌ <b>Ошибка транзакции</b>\nЗаявка на {amount_to_notify}$ отменена, средства возвращены.")
        
        try:
            await bot.send_message(user_to_notify_id, texts['user_notifications']['payout_failed_user'])
        except Exception as e:
            await bot.send_message(callback.from_user.id, texts['admin_panel']['error_notify_user_alert'].format(error=e))
    
    # Отправляем новое меню
    await show_admin_panel(bot, callback.message.chat.id, session_maker)


@super_admin_router.callback_query(kb.PayoutCallback.filter(F.action == "cancel"))
async def cancel_payout_handler(callback: CallbackQuery, callback_data: kb.PayoutCallback, bot: Bot, session_maker: async_sessionmaker):
    # Не удаляем, будем редактировать
    
    user_tg_id = 0
    amount = 0
    username = ""
    
    async with session_maker() as session:
        repo = Repository(session)
        try:
            cancelled_payout = await repo.cancel_payout(payout_id=callback_data.payout_id, admin_tg_id=callback.from_user.id)
            user_tg_id = cancelled_payout.user.tg_id
            amount = cancelled_payout.amount
            username = cancelled_payout.user.username
            
            await repo.log_action(
                actor_tg_id=callback.from_user.id,
                actor_username=callback.from_user.username,
                action="PAYOUT_CANCELLED",
                details=f"Payout ID {callback_data.payout_id} cancelled by admin."
            )
            await session.commit()
        except ValueError:
            await callback.message.edit_text(texts['admin_panel']['error_already_processed'])
            await show_admin_panel(bot, callback.message.chat.id, session_maker)
            return
    
    # --- ИЗМЕНЕНИЕ: Редактируем на статус "Отменено" ---
    username_label = f"@{username}" if username else f"ID: {user_tg_id}"
    await callback.message.edit_text(
        f"❌ <b>Выплата отменена</b>\n"
        f"👤 Юзер: {username_label}\n"
        f"💰 Сумма: {amount}$"
    )
    
    await show_admin_panel(bot, callback.message.chat.id, session_maker)

    if user_tg_id:
        try:
            await bot.send_message(user_tg_id, texts['user_notifications']['payout_cancelled_user'])
        except Exception as e:
            await bot.send_message(callback.from_user.id, texts['admin_panel']['error_notify_user_alert'].format(error=e))


# ==============================================================================
# BONUS LOGIC
# ==============================================================================

@super_admin_router.callback_query(F.data == "give_bonus_start")
async def start_bonus_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    msg = await callback.message.answer(texts['admin_panel']['ask_for_bonus_username'], reply_markup=kb.get_admin_cancel_keyboard())
    await state.update_data(main_panel_message_id=msg.message_id)
    await state.set_state(BonusFSM.waiting_for_username)
    await callback.answer()

@super_admin_router.message(BonusFSM.waiting_for_username)
async def bonus_username_handler(message: Message, state: FSMContext, session_maker: async_sessionmaker):
    username = message.text.lstrip('@').strip()
    data = await state.get_data()
    main_panel_message_id = data.get("main_panel_message_id")
    
    await message.delete()
    if main_panel_message_id:
        try: await message.bot.delete_message(message.chat.id, main_panel_message_id)
        except: pass
    
    user_data = None
    async with session_maker() as session:
        repo = Repository(session)
        user = await repo.get_user_by_username(username)
        if user:
            user_data = {"id": user.id, "username": user.username}

    if not user_data:
        new_msg = await message.answer(
            texts['admin_panel']['bonus_error_user_not_found'].format(username=f"@{username}"),
            reply_markup=kb.get_admin_cancel_keyboard()
        )
        await state.update_data(main_panel_message_id=new_msg.message_id)
        return

    await state.update_data(target_user_id=user_data["id"], target_username=user_data["username"])
    await state.set_state(BonusFSM.waiting_for_amount)

    new_msg = await message.answer(
        texts['admin_panel']['ask_for_bonus_amount'].format(username=f"@{user_data['username']}"),
        reply_markup=kb.get_admin_cancel_keyboard()
    )
    await state.update_data(main_panel_message_id=new_msg.message_id)

@super_admin_router.message(BonusFSM.waiting_for_amount)
async def bonus_amount_handler(message: Message, state: FSMContext, bot: Bot, session_maker: async_sessionmaker):
    data = await state.get_data()
    main_panel_message_id = data.get("main_panel_message_id")
    username = data.get("target_username")
    user_id = data.get("target_user_id")

    await message.delete()
    if main_panel_message_id:
        try: await bot.delete_message(message.chat.id, main_panel_message_id)
        except: pass
    
    amount = 0.0
    try:
        amount = float(message.text.strip().replace(',', '.'))
    except (ValueError, TypeError):
        new_msg = await message.answer(
            texts['admin_panel']['bonus_error_invalid_amount'],
            reply_markup=kb.get_admin_cancel_keyboard()
        )
        await state.update_data(main_panel_message_id=new_msg.message_id)
        return
    
    await state.clear()
    
    user_tg_id = 0
    async with session_maker() as session:
        repo = Repository(session)
        await repo.add_bonus_to_user(user_id=user_id, amount=amount)
        user = await repo.session.get(User, user_id)
        if user:
            user_tg_id = user.tg_id
        
        await repo.log_action(
            actor_tg_id=message.from_user.id,
            actor_username=message.from_user.username,
            action="BONUS_GIVEN",
            details=f"Gave ${amount} to user {user_tg_id} (@{username})"
        )
        
        await session.commit()

    await message.answer(texts['admin_panel']['bonus_success_admin'].format(amount=amount, username=f"@{username}"))
    
    if user_tg_id:
        try:
            await bot.send_message(user_tg_id, texts['user_notifications']['bonus_received'].format(amount=amount))
        except Exception as e:
            await message.answer(texts['admin_panel']['error_notify_user_alert'].format(error=e))

    await asyncio.sleep(3)
    await show_admin_panel(bot, message.chat.id, session_maker)