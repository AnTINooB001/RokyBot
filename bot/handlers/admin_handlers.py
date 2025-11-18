# bot/handlers/admin_handlers.py

import asyncio
import json
import logging
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup, any_state
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.db.models import User
from bot.db.repository import Repository
from bot.keyboards import admin_keyboards as kb
from bot.config import config
from bot.filters.admin_filter import IsAdmin
from bot.middlewares.ban_check import cache

# --- Global variables & setup ---
BASE_DIR = Path(__file__).resolve().parent.parent.parent
with open(BASE_DIR / 'texts.json', 'r', encoding='utf-8') as f:
    texts = json.load(f)

MONEY_PER_VIDEO = 0.5  # Сумма за одно принятое видео (можно вынести в конфиг/БД)

# --- FSM States ---
class VideoRejection(StatesGroup):
    waiting_for_reason = State()

class VideoInProcess(StatesGroup):
    waiting_video_process = State()

class UserManagementFSM(StatesGroup):
    waiting_for_username = State()

# --- Router Setup ---
admin_router = Router()

# Применяем фильтр IsAdmin ко всему роутеру.
# Он пускает: 1. Супер-админов (из конфига). 2. Админов (is_admin=True в БД).
admin_router.message.filter(IsAdmin())
admin_router.callback_query.filter(IsAdmin())


# --- Helper Functions ---

def check_ban_permissions(actor_tg_id: int, target_user: User) -> bool:
    """
    Проверяет иерархию прав для бана/разбана.
    
    Args:
        actor_tg_id: Telegram ID того, кто пытается совершить действие.
        target_user: Объект пользователя из БД (жертва).
    """
    super_admins = config.super_admin_ids
    target_tg_id = target_user.tg_id
    
    # 1. Нельзя забанить самого себя
    if actor_tg_id == target_tg_id:
        return False

    # 2. НИКТО не может забанить Супер-Админа
    if target_tg_id in super_admins:
        return False
    
    # 3. Если действует Супер-Админ -> можно всё (кроме п.1 и п.2)
    if actor_tg_id in super_admins:
        return True
        
    # 4. Если действует обычный Админ (мы знаем это, т.к. прошли фильтр роутера)
    # Он не может трогать другого Админа (проверяем флаг из БД)
    if target_user.is_admin:
        return False
        
    # Обычных юзеров банить можно
    return True


async def show_admin_panel(bot: Bot, chat_id: int, session_maker: async_sessionmaker, message_id: int = None):
    """
    Отправляет или редактирует сообщение, показывая главную админ-панель.
    Эта функция используется и здесь, и в super_admin_handlers.
    """
    queue_count = 0
    payout_count = 0
    
    # Проверяем, является ли текущий пользователь супер-админом
    is_super_admin = chat_id in config.super_admin_ids

    async with session_maker() as session:
        repo = Repository(session)
        queue_count = await repo.get_queue_count()
        # Запрашиваем количество выплат только если это супер-админ (оптимизация)
        if is_super_admin:
            payout_count = await repo.get_pending_payouts_count()

    base_welcome = texts['admin_panel']['welcome']
    
    # Формируем заголовок в зависимости от роли
    if is_super_admin:
        role_title = "👑 Супер-Админ"
    else:
        role_title = "👮 Админ"
        
    text = f"{base_welcome}\n\nВаш уровень доступа: <b>{role_title}</b>"
    
    # Передаем флаг в клавиатуру, чтобы скрыть/показать кнопку выплат и управления админами
    reply_markup = kb.get_admin_main_menu(
        queue_count=queue_count, 
        payout_count=payout_count, 
        is_super_admin=is_super_admin
    )
    
    if message_id:
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
        except TelegramBadRequest:
            await bot.send_message(chat_id, text, reply_markup=reply_markup)
    else:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)


# --- Main Navigation ---

@admin_router.message(Command("start"))
async def admin_panel_handler(message: Message, bot: Bot, session_maker: async_sessionmaker):
    """Вход в админку (перехватывает /start у обычного юзера благодаря приоритету роутеров)."""
    await message.delete()
    await show_admin_panel(bot, message.chat.id, session_maker)

@admin_router.callback_query(F.data == "back_to_admin_main", StateFilter(any_state))
async def back_to_admin_main_handler(callback: CallbackQuery, bot: Bot, state: FSMContext, session_maker: async_sessionmaker):
    """Возврат в главное меню."""
    await state.clear()
    await show_admin_panel(bot, callback.message.chat.id, session_maker, callback.message.message_id)
    await callback.answer()


# --- User Management Logic (Ban/Unban UI) ---

@admin_router.callback_query(F.data == "manage_users_start")
async def manage_users_start_handler(callback: CallbackQuery, state: FSMContext):
    """Вход в меню управления пользователями."""
    await state.update_data(main_panel_message_id=callback.message.message_id)
    await state.set_state(UserManagementFSM.waiting_for_username)
    
    await callback.message.edit_text(
        "Введите <b>@username</b> или <b>Telegram ID</b> пользователя для управления:",
        reply_markup=kb.get_admin_cancel_keyboard()
    )
    await callback.answer()

@admin_router.message(UserManagementFSM.waiting_for_username)
async def user_manage_input_handler(message: Message, state: FSMContext, bot: Bot, session_maker: async_sessionmaker):
    """Поиск пользователя и отображение его карточки."""
    input_data = message.text.lstrip('@').strip()
    data = await state.get_data()
    main_message_id = data.get("main_panel_message_id")
    
    await message.delete()

    user = None
    async with session_maker() as session:
        repo = Repository(session)
        # Поиск по ID
        if input_data.isdigit():
            user = await repo.get_user_by_tg_id(int(input_data))
        # Если не нашли, поиск по username
        if not user:
            user = await repo.get_user_by_username(input_data)
    
    if not user:
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id, 
                message_id=main_message_id,
                text=f"🚫 Пользователь <code>{input_data}</code> не найден.\nПопробуйте еще раз:",
                reply_markup=kb.get_admin_cancel_keyboard()
            )
        except TelegramBadRequest:
             await message.answer(f"🚫 Пользователь <code>{input_data}</code> не найден.", reply_markup=kb.get_admin_cancel_keyboard())
        return
    
    # Проверяем права по иерархии
    can_manage = check_ban_permissions(actor_tg_id=message.from_user.id, target_user=user)
    
    # --- ОПРЕДЕЛЕНИЕ РОЛИ ДЛЯ ОТОБРАЖЕНИЯ ---
    role_name = "👤 Пользователь"
    if user.tg_id in config.super_admin_ids:
        role_name = "👑 Супер-Админ"
    elif user.is_admin: # Проверяем флаг в БД
        role_name = "👮 Админ"
    # ---------------------------------------

    status_emoji = "🚫 ЗАБАНЕН" if user.is_banned else "✅ Активен"
    user_link = f"@{user.username}" if user.username else f"ID: {user.tg_id}"
    
    info_text = (
        f"👤 <b>Управление пользователем:</b>\n\n"
        f"User: {user_link}\n"
        f"Роль: <b>{role_name}</b>\n"
        f"Баланс: {user.balance:.2f} $\n"
        f"Статус: <b>{status_emoji}</b>\n\n"
    )
    
    if not can_manage:
        info_text += "⚠️ <i>У вас нет прав для изменения статуса этого пользователя (Иерархия прав).</i>"

    await state.clear()
    
    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=main_message_id,
        text=info_text,
        reply_markup=kb.get_user_management_keyboard(
            db_user_id=user.id, 
            is_banned=user.is_banned, 
            can_manage=can_manage
        )
    )


@admin_router.callback_query(kb.UserActionCallback.filter())
async def execute_user_action_handler(callback: CallbackQuery, callback_data: kb.UserActionCallback, bot: Bot, session_maker: async_sessionmaker):
    """Выполнение бана или разбана по нажатию кнопки."""
    target_user_tg_id = 0
    action_done = False
    log_text = ""
    
    async with session_maker() as session:
        repo = Repository(session)
        user = await repo.session.get(User, callback_data.user_id)
        
        if not user:
            await callback.answer("Пользователь не найден в БД.", show_alert=True)
            return
            
        target_user_tg_id = user.tg_id
        
        # ПОВТОРНАЯ ПРОВЕРКА ПРАВ (Backend защита)
        if not check_ban_permissions(actor_tg_id=callback.from_user.id, target_user=user):
            await callback.answer("⛔️ Отказано в доступе.", show_alert=True)
            return

        if callback_data.action == "ban":
            if user.is_banned:
                await callback.answer("Уже заблокирован.")
                return
            await repo.ban_user(user.id)
            cache[user.tg_id] = True # Обновляем кэш middleware мгновенно
            action_done = True
            log_text = "заблокирован"
            
        elif callback_data.action == "unban":
            if not user.is_banned:
                await callback.answer("Уже разблокирован.")
                return
            await repo.unban_user(user.id)
            cache[user.tg_id] = False # Обновляем кэш middleware мгновенно
            action_done = True
            log_text = "разблокирован"
            
        await session.commit()
        # Обновляем объект user, чтобы получить актуальные данные
        await session.refresh(user)

    if action_done:
        # Обновляем карточку пользователя
        role_name = "👤 Пользователь"
        if user.tg_id in config.super_admin_ids:
            role_name = "👑 Супер-Админ"
        elif user.is_admin:
            role_name = "👮 Админ"

        status_emoji = "🚫 ЗАБАНЕН" if user.is_banned else "✅ Активен"
        user_link = f"@{user.username}" if user.username else f"ID: {user.tg_id}"
        
        info_text = (
            f"👤 <b>Управление пользователем:</b>\n\n"
            f"User: {user_link}\n"
            f"Роль: <b>{role_name}</b>\n"
            f"Баланс: {user.balance:.2f} $\n"
            f"Статус: <b>{status_emoji}</b>\n\n"
            f"✅ <i>Успешно {log_text}.</i>"
        )
        
        await callback.message.edit_text(
            text=info_text,
            reply_markup=kb.get_user_management_keyboard(
                db_user_id=user.id, 
                is_banned=user.is_banned, 
                can_manage=True
            )
        )
        
        # Уведомляем пользователя
        try:
            if callback_data.action == "ban":
                await bot.send_message(target_user_tg_id, texts['user_notifications']['user_banned'])
            else:
                await bot.send_message(target_user_tg_id, texts['user_notifications']['user_unbanned'])
        except Exception:
            pass 


# --- Video Review Logic ---

@admin_router.callback_query(F.data == "get_video_review")
async def get_video_for_review_handler(callback: CallbackQuery, session_maker: async_sessionmaker, state :FSMContext):
    video_data = None
    async with session_maker() as session:
        repo = Repository(session)
        video = await repo.get_oldest_video_from_queue()
        if video:
            video_data = {"id": video.id, "link": video.link, "created_at": video.created_at, "username": video.user.username, "tg_id": video.user.tg_id}

    if not video_data:
        await callback.answer(texts['admin_panel']['queue_empty'], show_alert=True)
        return

    # Сохраняем данные в FSM
    await state.set_state(VideoInProcess.waiting_video_process)
    await state.update_data(
        video_id=video_data['id'],
        video_link=video_data['link'],
        user_tg_id=video_data['tg_id']
    )

    username = f"@{video_data['username']}" if video_data['username'] else f"ID: {video_data['tg_id']}"
    review_text = texts['admin_panel']['review_request'].format(
        username=username, link=video_data['link'], created_at=video_data['created_at'].strftime('%Y-%m-%d %H:%M')
    )
    
    await callback.message.edit_text(
        review_text, 
        reply_markup=kb.get_video_review_keyboard(video_id=video_data['id']), 
        disable_web_page_preview=True
    )
    await callback.answer()


@admin_router.callback_query(kb.VideoReviewCallback.filter(F.action == "accept"))
async def accept_video_handler(callback: CallbackQuery, bot: Bot, session_maker: async_sessionmaker, state :FSMContext):
    data = await state.get_data()
    video_id = data.get("video_id")
    video_link = data.get("video_link")
    user_tg_id = data.get("user_tg_id")
    
    # Проверка состояния FSM
    current_state = await state.get_state()
    if not video_id or current_state != VideoInProcess.waiting_video_process:
        await callback.answer("Ошибка сессии. Начните проверку заново.", show_alert=True)
        return

    await state.clear()
    
    async with session_maker() as session:
        repo = Repository(session)
        try:
            await repo.process_video_acceptance(video_id=video_id, admin_tg_id=callback.from_user.id, amount=MONEY_PER_VIDEO)
            await session.commit()
        except ValueError:
            await callback.answer(texts['admin_panel']['error_already_processed'], show_alert=True)
            await show_admin_panel(bot, callback.message.chat.id, session_maker, callback.message.message_id)
            return
    
    await callback.answer(texts['admin_panel']['video_accepted'].format(amount=MONEY_PER_VIDEO), show_alert=False)
    await show_admin_panel(bot, callback.message.chat.id, session_maker, callback.message.message_id)

    if user_tg_id:
        try:
            await bot.send_message(user_tg_id, texts['user_notifications']['video_accepted'].format(amount=MONEY_PER_VIDEO, video_link=video_link))
        except Exception as e:
            await bot.send_message(callback.from_user.id, texts['admin_panel']['error_notify_user_alert'].format(error=e))
        

@admin_router.callback_query(kb.VideoReviewCallback.filter(F.action == "reject"))
async def reject_video_handler(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state != VideoInProcess.waiting_video_process:
        await callback.answer("Ошибка сессии. Начните проверку заново.", show_alert=True)
        return

    await state.set_state(VideoRejection.waiting_for_reason)
    await state.update_data(original_message_id=callback.message.message_id)
    await callback.message.edit_text(texts['admin_panel']['ask_for_rejection_reason'], reply_markup=kb.get_admin_cancel_keyboard())
    await callback.answer()


@admin_router.message(VideoRejection.waiting_for_reason)
async def rejection_reason_handler(message: Message, state: FSMContext, bot: Bot, session_maker: async_sessionmaker):
    data = await state.get_data()
    video_id = data.get("video_id")
    video_link = data.get("video_link")
    user_tg_id = data.get("user_tg_id")
    original_message_id = data.get("original_message_id")
    reason = message.text
    
    await state.clear()
    await message.delete()

    async with session_maker() as session:
        repo = Repository(session)
        try:
            await repo.process_video_rejection(video_id=video_id, admin_tg_id=message.from_user.id, reason=reason)
            await session.commit()
        except ValueError:
            await bot.edit_message_text(chat_id=message.chat.id, message_id=original_message_id, text=texts['admin_panel']['error_already_processed'])
            return

    await show_admin_panel(bot, message.chat.id, session_maker, original_message_id)
    if user_tg_id:
        try:
            await bot.send_message(user_tg_id, texts['user_notifications']['video_rejected'].format(reason=reason, video_link=video_link))
        except Exception as e:
            await bot.send_message(message.from_user.id, texts['admin_panel']['error_notify_user_alert'].format(error=e))


# --- Statistics Logic ---

@admin_router.callback_query(F.data == "show_stats_menu")
async def show_stats_menu_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        texts['admin_panel']['stats_menu_title'],
        reply_markup=kb.get_stats_menu_keyboard()
    )
    await callback.answer()

@admin_router.callback_query(F.data == "get_global_stats")
async def get_global_stats_handler(callback: CallbackQuery, session_maker: async_sessionmaker):
    async with session_maker() as session:
        stats = await Repository(session).get_global_stats()
        
    text = texts['admin_panel']['global_stats_message'].format(**stats)
    await callback.message.edit_text(
        text,
        reply_markup=kb.get_back_to_stats_menu_keyboard()
    )
    await callback.answer()

@admin_router.callback_query(F.data == "get_my_stats")
async def get_my_stats_handler(callback: CallbackQuery, session_maker: async_sessionmaker):
    async with session_maker() as session:
        stats = await Repository(session).get_admin_stats(callback.from_user.id)
        
    text = texts['admin_panel']['my_stats_message'].format(**stats)
    await callback.message.edit_text(
        text,
        reply_markup=kb.get_back_to_stats_menu_keyboard()
    )
    await callback.answer()