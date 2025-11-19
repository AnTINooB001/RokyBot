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

MONEY_PER_VIDEO = 0.5

# --- FSM States ---
class VideoRejection(StatesGroup):
    waiting_for_reason = State()

class VideoInProcess(StatesGroup):
    waiting_video_process = State()

class UserManagementFSM(StatesGroup):
    waiting_for_username = State()

admin_router = Router()
admin_router.message.filter(IsAdmin())
admin_router.callback_query.filter(IsAdmin())


# --- Helper Functions ---

def check_ban_permissions(actor_tg_id: int, target_user: User) -> bool:
    super_admins = config.super_admin_ids
    target_tg_id = target_user.tg_id
    if actor_tg_id == target_tg_id: return False
    if target_tg_id in super_admins: return False
    if actor_tg_id in super_admins: return True
    if target_user.is_admin: return False
    return True


async def show_admin_panel(bot: Bot, chat_id: int, session_maker: async_sessionmaker, message_id_to_delete: int = None):
    """
    Удаляет старое сообщение (если есть) и отправляет новое с панелью.
    """
    queue_count = 0
    payout_count = 0
    
    is_super_admin = chat_id in config.super_admin_ids

    async with session_maker() as session:
        repo = Repository(session)
        queue_count = await repo.get_queue_count()
        if is_super_admin:
            payout_count = await repo.get_pending_payouts_count()

    base_welcome = texts['admin_panel']['welcome']
    role_title = "👑 Супер-Админ" if is_super_admin else "👮 Админ"
    text = f"{base_welcome}\n\nВаш уровень доступа: <b>{role_title}</b>"
    
    reply_markup = kb.get_admin_main_menu(
        queue_count=queue_count, 
        payout_count=payout_count, 
        is_super_admin=is_super_admin
    )
    
    # 1. Удаляем старое сообщение, если передан ID
    if message_id_to_delete:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id_to_delete)
        except Exception:
            pass # Сообщение уже удалено или слишком старое, игнорируем
    
    # 2. Отправляем новое сообщение
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)


# --- Main Navigation ---

@admin_router.message(Command("start"))
async def admin_panel_handler(message: Message, bot: Bot, session_maker: async_sessionmaker):
    # Удаляем команду /start для чистоты
    await message.delete()
    await show_admin_panel(bot, message.chat.id, session_maker)

@admin_router.callback_query(F.data == "back_to_admin_main", StateFilter(any_state))
async def back_to_admin_main_handler(callback: CallbackQuery, bot: Bot, state: FSMContext, session_maker: async_sessionmaker):
    # Проверяем, было ли у админа "на руках" видео
    data = await state.get_data()
    video_id = data.get("video_id")
    current_state = await state.get_state()
    
    # Если админ уходит из режима проверки видео, нужно разблокировать видео в БД
    if video_id and current_state == VideoInProcess.waiting_video_process:
        async with session_maker() as session:
            repo = Repository(session)
            await repo.unlock_video(video_id)
            await session.commit()
            logging.info(f"Admin {callback.from_user.id} unlocked video {video_id}")

    await state.clear()
    await show_admin_panel(bot, callback.message.chat.id, session_maker, callback.message.message_id)
    await callback.answer()


# --- User Management Logic ---

@admin_router.callback_query(F.data == "manage_users_start")
async def manage_users_start_handler(callback: CallbackQuery, state: FSMContext):
    # Удаляем старое меню
    await callback.message.delete()
    
    # Отправляем новое сообщение
    msg = await callback.message.answer(
        "Введите <b>@username</b> или <b>Telegram ID</b> пользователя для управления:",
        reply_markup=kb.get_admin_cancel_keyboard()
    )
    
    # Сохраняем ID этого сообщения, чтобы потом удалить/обновить
    await state.update_data(main_panel_message_id=msg.message_id)
    await state.set_state(UserManagementFSM.waiting_for_username)
    await callback.answer()

@admin_router.message(UserManagementFSM.waiting_for_username)
async def user_manage_input_handler(message: Message, state: FSMContext, bot: Bot, session_maker: async_sessionmaker):
    input_data = message.text.lstrip('@').strip()
    data = await state.get_data()
    main_message_id = data.get("main_panel_message_id")
    
    # Удаляем ввод админа
    await message.delete()
    
    # Удаляем предыдущее сообщение бота (с просьбой ввести username)
    if main_message_id:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=main_message_id)
        except Exception: pass

    user = None
    async with session_maker() as session:
        repo = Repository(session)
        if input_data.isdigit():
            user = await repo.get_user_by_tg_id(int(input_data))
        if not user:
            user = await repo.get_user_by_username(input_data)
    
    if not user:
        # Отправляем новое сообщение об ошибке
        new_msg = await message.answer(
            f"🚫 Пользователь <code>{input_data}</code> не найден.\nПопробуйте еще раз:",
            reply_markup=kb.get_admin_cancel_keyboard()
        )
        await state.update_data(main_panel_message_id=new_msg.message_id)
        return
    
    can_manage = check_ban_permissions(actor_tg_id=message.from_user.id, target_user=user)
    
    role_name = "👤 Пользователь"
    if user.tg_id in config.super_admin_ids: role_name = "👑 Супер-Админ"
    elif user.is_admin: role_name = "👮 Админ"

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
        info_text += "⚠️ <i>У вас нет прав для изменения статуса этого пользователя.</i>"

    await state.clear()
    
    # Отправляем карточку пользователя новым сообщением
    await message.answer(
        text=info_text,
        reply_markup=kb.get_user_management_keyboard(
            db_user_id=user.id, 
            is_banned=user.is_banned, 
            can_manage=can_manage
        )
    )


@admin_router.callback_query(kb.UserActionCallback.filter())
async def execute_user_action_handler(callback: CallbackQuery, callback_data: kb.UserActionCallback, bot: Bot, session_maker: async_sessionmaker):
    target_user_tg_id = 0
    action_done = False
    log_text = ""
    
    async with session_maker() as session:
        repo = Repository(session)
        user = await repo.session.get(User, callback_data.user_id)
        if not user:
            await callback.answer("Пользователь не найден.", show_alert=True); return
        target_user_tg_id = user.tg_id
        
        if not check_ban_permissions(actor_tg_id=callback.from_user.id, target_user=user):
            await callback.answer("⛔️ Отказано в доступе.", show_alert=True); return

        if callback_data.action == "ban":
            if user.is_banned: await callback.answer("Уже заблокирован."); return
            await repo.ban_user(user.id)
            cache[user.tg_id] = True
            action_done = True
            log_text = "заблокирован"
        elif callback_data.action == "unban":
            if not user.is_banned: await callback.answer("Уже разблокирован."); return
            await repo.unban_user(user.id)
            cache[user.tg_id] = False
            action_done = True
            log_text = "разблокирован"
        await session.commit()
        await session.refresh(user)

    if action_done:
        role_name = "👤 Пользователь"
        if user.tg_id in config.super_admin_ids: role_name = "👑 Супер-Админ"
        elif user.is_admin: role_name = "👮 Админ"

        status_emoji = "🚫 ЗАБАНЕН" if user.is_banned else "✅ Активен"
        info_text = (
            f"👤 <b>Управление пользователем:</b>\n\nUser: @{user.username}\nРоль: <b>{role_name}</b>\n"
            f"Баланс: {user.balance:.2f} $\nСтатус: <b>{status_emoji}</b>\n\n✅ <i>Успешно {log_text}.</i>"
        )
        
        # Удаляем старую карточку и отправляем новую (чтобы была внизу)
        await callback.message.delete()
        await callback.message.answer(
            text=info_text,
            reply_markup=kb.get_user_management_keyboard(db_user_id=user.id, is_banned=user.is_banned, can_manage=True)
        )
        
        try:
            msg = texts['user_notifications']['user_banned'] if callback_data.action == "ban" else texts['user_notifications']['user_unbanned']
            await bot.send_message(target_user_tg_id, msg)
        except Exception: pass 


# --- Video Review Logic ---

@admin_router.callback_query(F.data == "get_video_review")
async def get_video_for_review_handler(callback: CallbackQuery, session_maker: async_sessionmaker, state :FSMContext):
    await callback.message.delete()
    
    video_data = None
    async with session_maker() as session:
        repo = Repository(session)
        # ИСПОЛЬЗУЕМ НОВЫЙ МЕТОД
        # Передаем ID админа, чтобы закрепить видео за ним
        video = await repo.get_video_for_review(admin_tg_id=callback.from_user.id)
        
        if video:
            video_data = {"id": video.id, "link": video.link, "created_at": video.created_at, "username": video.user.username, "tg_id": video.user.tg_id}
            # Коммитим транзакцию, чтобы сохранить "замок" в базе
            await session.commit() 

    if not video_data:
        await callback.answer(texts['admin_panel']['queue_empty'], show_alert=True)
        await show_admin_panel(callback.bot, callback.message.chat.id, session_maker)
        return

    await state.set_state(VideoInProcess.waiting_video_process)
    await state.update_data(video_id=video_data['id'], video_link=video_data['link'], user_tg_id=video_data['tg_id'])

    username = f"@{video_data['username']}" if video_data['username'] else f"ID: {video_data['tg_id']}"
    review_text = texts['admin_panel']['review_request'].format(
        username=username, link=video_data['link'], created_at=video_data['created_at'].strftime('%Y-%m-%d %H:%M')
    )
    
    # Отправляем новое сообщение
    await callback.message.answer(
        review_text, 
        reply_markup=kb.get_video_review_keyboard(video_id=video_data['id']), 
        disable_web_page_preview=True
    )
    await callback.answer()


@admin_router.callback_query(kb.VideoReviewCallback.filter(F.action == "accept"))
async def accept_video_handler(callback: CallbackQuery, bot: Bot, session_maker: async_sessionmaker, state :FSMContext):
    # Удаляем сообщение с видео
    await callback.message.delete()
    
    data = await state.get_data()
    video_id = data.get("video_id")
    video_link = data.get("video_link")
    user_tg_id = data.get("user_tg_id")
    
    if not video_id or (await state.get_state()) != VideoInProcess.waiting_video_process:
        await callback.answer("Ошибка сессии.", show_alert=True)
        await show_admin_panel(bot, callback.message.chat.id, session_maker) # Вернуть меню
        return

    await state.clear()
    
    async with session_maker() as session:
        repo = Repository(session)
        try:
            await repo.process_video_acceptance(video_id=video_id, admin_tg_id=callback.from_user.id, amount=MONEY_PER_VIDEO)
            await session.commit()
        except ValueError:
            await callback.answer(texts['admin_panel']['error_already_processed'], show_alert=True)
            await show_admin_panel(bot, callback.message.chat.id, session_maker)
            return
    
    await callback.answer(texts['admin_panel']['video_accepted'].format(amount=MONEY_PER_VIDEO), show_alert=False)
    # Показываем главное меню новым сообщением
    await show_admin_panel(bot, callback.message.chat.id, session_maker)

    if user_tg_id:
        try:
            await bot.send_message(user_tg_id, texts['user_notifications']['video_accepted'].format(amount=MONEY_PER_VIDEO, video_link=video_link))
        except Exception as e:
            await bot.send_message(callback.from_user.id, texts['admin_panel']['error_notify_user_alert'].format(error=e))
        

@admin_router.callback_query(kb.VideoReviewCallback.filter(F.action == "reject"))
async def reject_video_handler(callback: CallbackQuery, state: FSMContext):
    if (await state.get_state()) != VideoInProcess.waiting_video_process:
        await callback.answer("Ошибка сессии.", show_alert=True)
        return

    await state.set_state(VideoRejection.waiting_for_reason)
    # Удаляем старое
    await callback.message.delete()
    
    # Отправляем форму причины
    msg = await callback.message.answer(texts['admin_panel']['ask_for_rejection_reason'], reply_markup=kb.get_admin_cancel_keyboard())
    
    # Сохраняем ID сообщения, чтобы удалить его, если нажмут "Отмена"
    await state.update_data(original_message_id=msg.message_id)
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
    await message.delete() # Удаляем текст причины
    
    if original_message_id:
        try: await bot.delete_message(message.chat.id, original_message_id) # Удаляем вопрос
        except: pass

    async with session_maker() as session:
        repo = Repository(session)
        try:
            await repo.process_video_rejection(video_id=video_id, admin_tg_id=message.from_user.id, reason=reason)
            await session.commit()
        except ValueError:
            await message.answer(texts['admin_panel']['error_already_processed'])
            await show_admin_panel(bot, message.chat.id, session_maker)
            return

    await show_admin_panel(bot, message.chat.id, session_maker)
    if user_tg_id:
        try:
            await bot.send_message(user_tg_id, texts['user_notifications']['video_rejected'].format(reason=reason, video_link=video_link))
        except Exception as e:
            await bot.send_message(message.from_user.id, texts['admin_panel']['error_notify_user_alert'].format(error=e))


# --- Statistics Logic ---

@admin_router.callback_query(F.data == "show_stats_menu")
async def show_stats_menu_handler(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        texts['admin_panel']['stats_menu_title'],
        reply_markup=kb.get_stats_menu_keyboard()
    )
    await callback.answer()

@admin_router.callback_query(F.data == "get_global_stats")
async def get_global_stats_handler(callback: CallbackQuery, session_maker: async_sessionmaker):
    await callback.message.delete()
    async with session_maker() as session:
        stats = await Repository(session).get_global_stats()
    await callback.message.answer(texts['admin_panel']['global_stats_message'].format(**stats), reply_markup=kb.get_back_to_stats_menu_keyboard())
    await callback.answer()

@admin_router.callback_query(F.data == "get_my_stats")
async def get_my_stats_handler(callback: CallbackQuery, session_maker: async_sessionmaker):
    await callback.message.delete()
    async with session_maker() as session:
        stats = await Repository(session).get_admin_stats(callback.from_user.id)
    await callback.message.answer(texts['admin_panel']['my_stats_message'].format(**stats), reply_markup=kb.get_back_to_stats_menu_keyboard())
    await callback.answer()