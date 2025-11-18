# bot/handlers/super_admin_handlers.py

import asyncio
import json
import logging
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

from bot.db.models import User, Payout, PayoutStatus
from bot.db.repository import Repository
from bot.keyboards import admin_keyboards as kb
from bot.services.coingecko_service import coingecko_service
from bot.services.ton_service import ton_service
from bot.filters.admin_filter import IsSuperAdmin, admin_cache
# Импортируем функцию отображения меню из admin_handlers
from bot.handlers.admin_handlers import show_admin_panel

# --- Setup ---
BASE_DIR = Path(__file__).resolve().parent.parent.parent
with open(BASE_DIR / 'texts.json', 'r', encoding='utf-8') as f:
    texts = json.load(f)

# --- States ---
class BonusFSM(StatesGroup):
    waiting_for_username = State()
    waiting_for_amount = State()

class AddAdminFSM(StatesGroup):
    waiting_for_username = State()

# --- Router ---
super_admin_router = Router()
# ЖЕСТКИЙ ФИЛЬТР: Только супер-админы имеют доступ к этим хендлерам
super_admin_router.message.filter(IsSuperAdmin())
super_admin_router.callback_query.filter(IsSuperAdmin())


# ==============================================================================
# ADMIN MANAGEMENT LOGIC
# ==============================================================================

@super_admin_router.callback_query(F.data == "admin_manage_menu")
async def admin_manage_menu_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "👮 <b>Панель управления администраторами</b>\n\n"
        "Здесь вы можете назначать новых админов или снимать права с существующих.",
        reply_markup=kb.get_admin_management_menu()
    )
    await callback.answer()

# --- 1. Просмотр списка админов ---
@super_admin_router.callback_query(kb.AdminManageCallback.filter(F.action == "list"))
async def list_admins_handler(callback: CallbackQuery, session_maker: async_sessionmaker):
    async with session_maker() as session:
        repo = Repository(session)
        admins = await repo.get_all_admins()
    
    if not admins:
        text = "📋 Список назначенных админов пуст."
    else:
        text = "📋 <b>Список назначенных админов:</b>\n<i>Нажмите на кнопку с пользователем, чтобы лишить его прав.</i>"
        
    await callback.message.edit_text(text, reply_markup=kb.get_admins_list_keyboard(admins))
    await callback.answer()

# --- 2. Удаление админа ---
@super_admin_router.callback_query(kb.AdminManageCallback.filter(F.action == "remove"))
async def remove_admin_handler(callback: CallbackQuery, callback_data: kb.AdminManageCallback, session_maker: async_sessionmaker):
    user_db_id = callback_data.user_id
    
    async with session_maker() as session:
        repo = Repository(session)
        user = await repo.session.get(User, user_db_id)
        
        if user:
            # Снимаем права в БД
            await repo.set_admin_status(user.id, False)
            await session.commit()
            
            # Сбрасываем кэш, чтобы фильтр IsAdmin перестал пускать пользователя
            admin_cache[user.tg_id] = False
            
            await callback.answer(f"Пользователь {user.username or user.tg_id} разжалован.", show_alert=True)
            
            # Уведомляем бывшего админа
            try:
                await callback.bot.send_message(user.tg_id, "📉 Вы были лишены прав администратора.")
            except Exception: pass
            
            # Обновляем список в сообщении
            admins = await repo.get_all_admins()
            await callback.message.edit_reply_markup(reply_markup=kb.get_admins_list_keyboard(admins))
        else:
            await callback.answer("Пользователь не найден.", show_alert=True)

# --- 3. Добавление админа (Начало) ---
@super_admin_router.callback_query(kb.AdminManageCallback.filter(F.action == "add"))
async def add_admin_start_handler(callback: CallbackQuery, state: FSMContext):
    await state.update_data(main_msg_id=callback.message.message_id)
    await state.set_state(AddAdminFSM.waiting_for_username)
    await callback.message.edit_text(
        "Введите <b>@username</b> или <b>Telegram ID</b> пользователя, которого хотите сделать админом:",
        reply_markup=kb.get_admin_cancel_keyboard()
    )
    await callback.answer()

# --- 4. Добавление админа (Финал) ---
@super_admin_router.message(AddAdminFSM.waiting_for_username)
async def add_admin_finish_handler(message: Message, state: FSMContext, session_maker: async_sessionmaker):
    input_data = message.text.lstrip('@').strip()
    data = await state.get_data()
    main_msg_id = data.get("main_msg_id")
    
    await message.delete()
    
    async with session_maker() as session:
        repo = Repository(session)
        user = None
        # Поиск пользователя
        if input_data.isdigit():
            user = await repo.get_user_by_tg_id(int(input_data))
        if not user:
            user = await repo.get_user_by_username(input_data)
            
        # Обработка ошибок
        if not user:
            await message.bot.edit_message_text(
                chat_id=message.chat.id, message_id=main_msg_id,
                text=f"🚫 Пользователь <code>{input_data}</code> не найден в базе бота.\n"
                     f"Пользователь должен сначала запустить бота (/start).",
                reply_markup=kb.get_admin_cancel_keyboard()
            )
            return
            
        if user.is_admin:
            await message.bot.edit_message_text(
                chat_id=message.chat.id, message_id=main_msg_id,
                text=f"⚠️ Пользователь {user.username or user.tg_id} уже является админом.",
                reply_markup=kb.get_admin_cancel_keyboard()
            )
            return

        # Назначение админа
        await repo.set_admin_status(user.id, True)
        await session.commit()
        
        # Обновляем кэш, чтобы права появились мгновенно
        admin_cache[user.tg_id] = True
    
    await state.clear()
    
    # Подтверждение супер-админу
    await message.bot.edit_message_text(
        chat_id=message.chat.id, message_id=main_msg_id,
        text=f"✅ Пользователь <b>{user.username or user.tg_id}</b> успешно назначен администратором!",
        reply_markup=kb.get_admin_management_menu()
    )
    
    # Уведомление новому админу
    try:
        await message.bot.send_message(user.tg_id, "🎉 Вам выданы права администратора! Введите /start для входа в панель.")
    except Exception: pass


# ==============================================================================
# PAYOUT LOGIC
# ==============================================================================

@super_admin_router.callback_query(F.data == "get_payout_request")
async def get_payout_request_handler(callback: CallbackQuery, session_maker: async_sessionmaker):
    payout_data = None
    async with session_maker() as session:
        repo = Repository(session)
        payout = await repo.get_oldest_payout_request()
        if payout:
            payout_data = {"id": payout.id, "amount": payout.amount, "wallet": payout.wallet, "username": payout.user.username, "tg_id": payout.user.tg_id}

    if not payout_data:
        await callback.answer(texts['admin_panel']['payout_queue_empty'], show_alert=True)
        return

    username = f"@{payout_data['username']}" if payout_data['username'] else f"ID: {payout_data['tg_id']}"
    text = texts['admin_panel']['payout_review_request'].format(username=username, amount=payout_data['amount'], wallet=payout_data['wallet'])
    await callback.message.edit_text(text, reply_markup=kb.get_payout_review_keyboard(payout_id=payout_data['id']))
    await callback.answer()


@super_admin_router.callback_query(kb.PayoutCallback.filter(F.action == "confirm"))
async def confirm_payout_handler(callback: CallbackQuery, callback_data: kb.PayoutCallback, bot: Bot, session_maker: async_sessionmaker):
    payout_data = None
    async with session_maker() as session:
        repo = Repository(session)
        payout = await repo.session.get(Payout, callback_data.payout_id, options=[selectinload(Payout.user)])
        
        if not payout or payout.status != PayoutStatus.PENDING:
            await callback.message.edit_text(texts['admin_panel']['error_already_processed'])
            await callback.answer()
            return
        payout_data = {"id": payout.id, "wallet": payout.wallet, "amount": payout.amount, "user_tg_id": payout.user.tg_id}

    await callback.message.edit_text(texts['admin_panel']['payout_processing'])
    
    rate = coingecko_service.get_ton_to_usd_rate()
    if rate <= 0:
        await callback.message.edit_text(texts['admin_panel']['payout_error_api'])
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
            await session.commit()
        
        await callback.message.edit_text(texts['admin_panel']['payout_confirmed_admin'].format(tx_hash=tx_hash))
        try:
            await bot.send_message(user_to_notify_id, texts['user_notifications']['payout_confirmed_user'].format(amount=amount_to_notify, tx_hash=tx_hash))
        except Exception as e:
            await bot.send_message(callback.from_user.id, texts['admin_panel']['error_notify_user_alert'].format(error=e))
    else:
        async with session_maker() as session:
            repo = Repository(session)
            await repo.cancel_payout(payout_id=callback_data.payout_id, admin_tg_id=callback.from_user.id)
            await session.commit()
            
        await callback.message.edit_text(texts['admin_panel']['payout_error_tx_admin'])
        try:
            await bot.send_message(user_to_notify_id, texts['user_notifications']['payout_failed_user'])
        except Exception as e:
            await bot.send_message(callback.from_user.id, texts['admin_panel']['error_notify_user_alert'].format(error=e))
    
    await asyncio.sleep(3)
    await show_admin_panel(bot, callback.message.chat.id, session_maker, callback.message.message_id)


@super_admin_router.callback_query(kb.PayoutCallback.filter(F.action == "cancel"))
async def cancel_payout_handler(callback: CallbackQuery, callback_data: kb.PayoutCallback, bot: Bot, session_maker: async_sessionmaker):
    user_tg_id = 0
    async with session_maker() as session:
        repo = Repository(session)
        try:
            cancelled_payout = await repo.cancel_payout(payout_id=callback_data.payout_id, admin_tg_id=callback.from_user.id)
            user_tg_id = cancelled_payout.user.tg_id
            await session.commit()
        except ValueError:
            await callback.answer(texts['admin_panel']['error_already_processed'], show_alert=True)
            return
    
    await callback.answer(texts['admin_panel']['payout_cancelled_admin'], show_alert=False)
    await show_admin_panel(bot, callback.message.chat.id, session_maker, callback.message.message_id)

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
    await state.update_data(main_panel_message_id=callback.message.message_id)
    await state.set_state(BonusFSM.waiting_for_username)
    await callback.message.edit_text(texts['admin_panel']['ask_for_bonus_username'], reply_markup=kb.get_admin_cancel_keyboard())
    await callback.answer()

@super_admin_router.message(BonusFSM.waiting_for_username)
async def bonus_username_handler(message: Message, state: FSMContext, session_maker: async_sessionmaker):
    username = message.text.lstrip('@').strip()
    
    user_data = None
    async with session_maker() as session:
        repo = Repository(session)
        user = await repo.get_user_by_username(username)
        if user:
            user_data = {"id": user.id, "username": user.username}

    data = await state.get_data()
    main_panel_message_id = data.get("main_panel_message_id")
    await message.delete()

    if not user_data:
        await message.bot.edit_message_text(
            chat_id=message.chat.id, message_id=main_panel_message_id,
            text=texts['admin_panel']['bonus_error_user_not_found'].format(username=f"@{username}")
        )
        await asyncio.sleep(3)
        await message.bot.edit_message_text(
            chat_id=message.chat.id, message_id=main_panel_message_id,
            text=texts['admin_panel']['ask_for_bonus_username'],
            reply_markup=kb.get_admin_cancel_keyboard()
        )
        return

    await state.update_data(target_user_id=user_data["id"], target_username=user_data["username"])
    await state.set_state(BonusFSM.waiting_for_amount)

    await message.bot.edit_message_text(
        chat_id=message.chat.id, message_id=main_panel_message_id,
        text=texts['admin_panel']['ask_for_bonus_amount'].format(username=f"@{user_data['username']}"),
        reply_markup=kb.get_admin_cancel_keyboard()
    )

@super_admin_router.message(BonusFSM.waiting_for_amount)
async def bonus_amount_handler(message: Message, state: FSMContext, bot: Bot, session_maker: async_sessionmaker):
    data = await state.get_data()
    main_panel_message_id = data.get("main_panel_message_id")
    username = data.get("target_username")
    user_id = data.get("target_user_id")

    await message.delete()
    
    amount = 0.0
    try:
        amount = float(message.text.strip().replace(',', '.'))
    except (ValueError, TypeError):
        await bot.edit_message_text(
            chat_id=message.chat.id, message_id=main_panel_message_id,
            text=texts['admin_panel']['bonus_error_invalid_amount']
        )
        await asyncio.sleep(3)
        await bot.edit_message_text(
            chat_id=message.chat.id, message_id=main_panel_message_id,
            text=texts['admin_panel']['ask_for_bonus_amount'].format(username=f"@{username}"),
            reply_markup=kb.get_admin_cancel_keyboard()
        )
        return
    
    await state.clear()
    
    user_tg_id = 0
    async with session_maker() as session:
        repo = Repository(session)
        await repo.add_bonus_to_user(user_id=user_id, amount=amount)
        user = await repo.session.get(User, user_id)
        if user:
            user_tg_id = user.tg_id
        await session.commit()

    await bot.edit_message_text(
        chat_id=message.chat.id, message_id=main_panel_message_id,
        text=texts['admin_panel']['bonus_success_admin'].format(amount=amount, username=f"@{username}")
    )
    
    if user_tg_id:
        try:
            await bot.send_message(user_tg_id, texts['user_notifications']['bonus_received'].format(amount=amount))
        except Exception as e:
            await message.answer(texts['admin_panel']['error_notify_user_alert'].format(error=e))

    await asyncio.sleep(3)
    await show_admin_panel(bot, message.chat.id, session_maker, main_panel_message_id)