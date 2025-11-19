# bot/handlers/user_handlers.py

import json
import re
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup, any_state
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import config
from bot.db.repository import Repository
from bot.keyboards import user_keyboards as kb
from bot.filters.admin_filter import IsAdmin
# Импортируем Throttling Middleware (предполагается, что он в bot.middlewares.throttling)
# Если он у вас называется иначе, поправьте импорт
from bot.middlewares.throttling import RateLimiterMiddleware

# --- Setup ---
BASE_DIR = Path(__file__).resolve().parent.parent.parent
with open(BASE_DIR / 'texts.json', 'r', encoding='utf-8') as f:
    texts = json.load(f)

# --- States ---
class Registration(StatesGroup):
    waiting_for_wallet = State()

class VideoSubmission(StatesGroup):
    waiting_for_link = State()

class WalletChange(StatesGroup):
    waiting_for_new_wallet = State()

# --- Router ---
user_router = Router()
# Фильтр: этот роутер только для обычных пользователей (НЕ админов)

# при тесте удобно быть одновременно и пользователем и админом
if not __debug__:
    user_router.message.filter(~IsAdmin())
    user_router.callback_query.filter(~IsAdmin())

# Создаем отдельный роутер для троттлинга, чтобы применить его точечно
throttled_router = Router()
throttled_router.message.middleware(RateLimiterMiddleware(limit=3, period=3600)) # 3 видео в час
user_router.include_router(throttled_router)


# --- Start & Registration ---

#-------------------------------- TEST --------------------------------------
if __debug__:
    @user_router.message(Command("user"))
    async def start_handler(message: Message, bot: Bot, session_maker: async_sessionmaker):
        # Проверяем подписку на канал
        try:
            member = await bot.get_chat_member(chat_id=config.channel_id, user_id=message.from_user.id)
            if member.status in ["left", "kicked"]:
                await message.answer(
                    texts['start']['initial_welcome'],
                    reply_markup=kb.get_subscribe_keyboard(f"https://t.me/{config.channel_id.lstrip('@')}")
                )
                return
        except Exception as e:
            await message.answer(texts['start']['subscription_error'].format(error_details=str(e)))
            return

        async with session_maker() as session:
            repo = Repository(session)
            user = await repo.get_user_by_tg_id(message.from_user.id)
            
            if not user:
                # Начинаем регистрацию
                await repo.create_user(tg_id=message.from_user.id, username=message.from_user.username)
                await session.commit()
                # Отправляем полные условия
                await message.answer(texts['registration']['full_intro_and_rules'], reply_markup=kb.get_understood_keyboard())
            else:
                if not user.wallet:
                    # Если пользователь есть, но кошелек не задан (прервал регистрацию)
                    await message.answer(texts['registration']['short_terms_agreement'], reply_markup=kb.get_final_agreement_keyboard())
                else:
                    # Уже зарегистрирован
                    await message.answer(texts['user_panel']['main_menu_text'], reply_markup=kb.get_main_menu_keyboard())


#---------------------------------------------------------------TEST---------------------


@user_router.message(Command("start"))
async def start_handler(message: Message, bot: Bot, session_maker: async_sessionmaker):
    # Проверяем подписку на канал
    try:
        member = await bot.get_chat_member(chat_id=config.channel_id, user_id=message.from_user.id)
        if member.status in ["left", "kicked"]:
            await message.answer(
                texts['start']['initial_welcome'],
                reply_markup=kb.get_subscribe_keyboard(f"https://t.me/{config.channel_id.lstrip('@')}")
            )
            return
    except Exception as e:
        await message.answer(texts['start']['subscription_error'].format(error_details=str(e)))
        return

    async with session_maker() as session:
        repo = Repository(session)
        user = await repo.get_user_by_tg_id(message.from_user.id)
        
        if not user:
            # Начинаем регистрацию
            await repo.create_user(tg_id=message.from_user.id, username=message.from_user.username)
            await session.commit()
            # Отправляем полные условия
            await message.answer(texts['registration']['full_intro_and_rules'], reply_markup=kb.get_understood_keyboard())
        else:
            if not user.wallet:
                # Если пользователь есть, но кошелек не задан (прервал регистрацию)
                await message.answer(texts['registration']['short_terms_agreement'], reply_markup=kb.get_final_agreement_keyboard())
            else:
                # Уже зарегистрирован
                await message.answer(texts['user_panel']['main_menu_text'], reply_markup=kb.get_main_menu_keyboard())

@user_router.callback_query(F.data == "check_subscription")
async def check_subscription_handler(callback: CallbackQuery, bot: Bot):
    try:
        member = await bot.get_chat_member(chat_id=config.channel_id, user_id=callback.from_user.id)
        if member.status in ["left", "kicked"]:
            await callback.answer(texts['start']['not_subscribed_alert'], show_alert=True)
        else:
            # Подписался - запускаем логику старта заново
            # (удаляем кнопку подписки и вызываем start)
            await callback.message.delete()
            # Имитируем команду /start, вызывая хендлер (или просто просим нажать /start)
            # Проще всего отправить текст приветствия
            await callback.message.answer("Подписка подтверждена! Нажмите /start") 
    except Exception:
        await callback.answer(texts['start']['admin_error_alert'], show_alert=True)

# --- Registration Flow ---

@user_router.callback_query(F.data == "understood_terms")
async def understood_terms_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        texts['registration']['short_terms_agreement'],
        reply_markup=kb.get_final_agreement_keyboard()
    )

@user_router.callback_query(F.data == "final_agree")
async def final_agree_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(texts['registration']['ask_for_wallet'])
    await state.set_state(Registration.waiting_for_wallet)

@user_router.message(Registration.waiting_for_wallet)
async def wallet_input_handler(message: Message, state: FSMContext, session_maker: async_sessionmaker):
    wallet = message.text.strip()
    # Простая валидация TON кошелька (48 символов, base64url)
    if not re.match(r'^[a-zA-Z0-9_-]{48}$', wallet):
        await message.answer(texts['registration']['invalid_wallet'])
        return
    
    async with session_maker() as session:
        repo = Repository(session)
        await repo.update_user_wallet(message.from_user.id, wallet)
        await session.commit()
    
    await state.clear()
    await message.answer(texts['registration']['wallet_saved'])
    await message.answer(texts['user_panel']['main_menu_text'], reply_markup=kb.get_main_menu_keyboard())


# --- Main Menu Navigation ---

@user_router.callback_query(F.data == "back_to_main_menu", StateFilter(any_state))
async def back_to_main_menu_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        texts['user_panel']['main_menu_text'],
        reply_markup=kb.get_main_menu_keyboard()
    )


# --- Video Submission Logic ---

@user_router.callback_query(F.data == "send_video")
async def send_video_start_handler(callback: CallbackQuery, state: FSMContext):
    msg = await callback.message.edit_text(
        texts['user_panel']['ask_for_video_link'],
        reply_markup=kb.get_cancel_keyboard()
    )
    # Сохраняем ID сообщения, чтобы потом удалить его
    await state.update_data(prompt_message_id=msg.message_id)
    await state.set_state(VideoSubmission.waiting_for_link)

@throttled_router.message(VideoSubmission.waiting_for_link)
async def receive_video_link_handler(message: Message, state: FSMContext, session_maker: async_sessionmaker):
    link = message.text.strip()
    # Простая проверка на ссылку
    if not link.startswith(("http://", "https://")):
        await message.answer(texts['user_panel']['invalid_link'])
        return
    
    data = await state.get_data()
    prompt_message_id = data.get("prompt_message_id")
    
    await state.clear()
    
    # Удаляем сообщение "Пришлите ссылку"
    if prompt_message_id:
        try: await message.bot.delete_message(message.chat.id, prompt_message_id)
        except: pass

    async with session_maker() as session:
        repo = Repository(session)
        user = await repo.get_user_by_tg_id(message.from_user.id)
        if user:
            await repo.add_video_to_queue(user.id, link)
            await session.commit()
            
    await message.answer(texts['user_panel']['video_submitted'])
    await message.answer(texts['user_panel']['main_menu_text'], reply_markup=kb.get_main_menu_keyboard())

# --- Profile & Payout Logic ---

@user_router.callback_query(F.data == "show_profile")
async def show_profile_handler(callback: CallbackQuery, session_maker: async_sessionmaker):
    async with session_maker() as session:
        repo = Repository(session)
        user = await repo.get_user_by_tg_id(callback.from_user.id)
        
        # Статистика
        on_review = await repo.count_videos_on_review(user.id)
        accepted = await repo.count_accepted_videos(user.id)
        rejected = await repo.count_rejected_videos(user.id)

    wallet_short = f"{user.wallet[:4]}...{user.wallet[-4:]}" if user.wallet else "Не задан"
    
    text = texts['user_panel']['profile_text'].format(
        balance=user.balance,
        on_review_count=on_review,
        accepted_count=accepted,
        rejected_count=rejected,
        wallet_short=wallet_short
    )
    
    # Используем edit_text, если это возможно (если мы пришли из меню)
    try:
        await callback.message.edit_text(text, reply_markup=kb.get_profile_keyboard())
    except TelegramBadRequest:
        # Если сообщение слишком старое или контент не изменился
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=kb.get_profile_keyboard())


@user_router.callback_query(F.data == "request_payout")
async def request_payout_handler(callback: CallbackQuery, session_maker: async_sessionmaker):
    async with session_maker() as session:
        repo = Repository(session)
        user = await repo.get_user_by_tg_id(callback.from_user.id)
        
        # --- ПРОВЕРКА НА СУЩЕСТВУЮЩУЮ ЗАЯВКУ ---
        if await repo.has_pending_payout(user.id):
            await callback.message.edit_text(
                text=texts['user_panel']['payout_already_pending'],
                reply_markup=kb.get_back_to_profile_keyboard()
            )
            await callback.answer()
            return
        # ---------------------------------------

        if user.balance < config.min_payout_amount:
            await callback.answer(
                texts['user_panel']['payout_not_enough_balance'].format(min_payout=config.min_payout_amount),
                show_alert=True
            )
            return

    text = texts['user_panel']['payout_confirm_request'].format(
        min_payout=config.min_payout_amount,
        balance=user.balance,
        wallet=user.wallet
    )
    await callback.message.edit_text(text, reply_markup=kb.get_confirm_payout_keyboard())


@user_router.callback_query(F.data == "confirm_payout_request")
async def confirm_payout_handler(callback: CallbackQuery, session_maker: async_sessionmaker):
    async with session_maker() as session:
        repo = Repository(session)
        user = await repo.get_user_by_tg_id(callback.from_user.id)
        
        # Повторная проверка (на всякий случай)
        if user.balance < config.min_payout_amount:
            await callback.answer("Недостаточно средств.", show_alert=True)
            await show_profile_handler(callback, session_maker)
            return
        
        if await repo.has_pending_payout(user.id):
             await callback.answer("Заявка уже существует.", show_alert=True)
             await show_profile_handler(callback, session_maker)
             return

        # Создаем заявку на ВСЮ сумму
        await repo.create_payout_request(user, user.balance)
        await session.commit()
        
    await callback.message.edit_text(
        texts['user_panel']['payout_request_created'],
        reply_markup=kb.get_back_to_profile_keyboard()
    )


@user_router.callback_query(F.data == "cancel_payout_request")
async def cancel_payout_handler(callback: CallbackQuery, session_maker: async_sessionmaker):
    await callback.answer(texts['user_panel']['payout_request_cancelled'])
    await show_profile_handler(callback, session_maker)


# --- Wallet Change ---

@user_router.callback_query(F.data == "change_wallet")
async def change_wallet_start_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        texts['user_panel']['ask_for_new_wallet'],
        reply_markup=kb.get_cancel_change_wallet_keyboard()
    )
    await state.set_state(WalletChange.waiting_for_new_wallet)
    # Сохраняем ID сообщения для редактирования/удаления
    await state.update_data(msg_id=callback.message.message_id)


@user_router.message(WalletChange.waiting_for_new_wallet)
async def change_wallet_input_handler(message: Message, state: FSMContext, session_maker: async_sessionmaker, bot: Bot):
    wallet = message.text.strip()
    data = await state.get_data()
    prev_msg_id = data.get("msg_id")

    await message.delete() # Удаляем сообщение юзера

    if not re.match(r'^[a-zA-Z0-9_-]{48}$', wallet):
        # Если ошибка - редактируем старое сообщение или отправляем новое
        if prev_msg_id:
            try:
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=prev_msg_id,
                    text=texts['registration']['invalid_wallet'],
                    reply_markup=kb.get_cancel_change_wallet_keyboard()
                )
            except:
                 msg = await message.answer(texts['registration']['invalid_wallet'], reply_markup=kb.get_cancel_change_wallet_keyboard())
                 await state.update_data(msg_id=msg.message_id)
        else:
             msg = await message.answer(texts['registration']['invalid_wallet'], reply_markup=kb.get_cancel_change_wallet_keyboard())
             await state.update_data(msg_id=msg.message_id)
        return
    
    async with session_maker() as session:
        repo = Repository(session)
        await repo.update_user_wallet(message.from_user.id, wallet)
        await session.commit()
    
    await state.clear()
    
    # Успех: удаляем старое сообщение и показываем профиль
    if prev_msg_id:
        try: await bot.delete_message(message.chat.id, prev_msg_id)
        except: pass

    await message.answer(texts['user_panel']['wallet_changed_successfully'])
    # Вызываем показ профиля как будто нажали кнопку (нужен session_maker)
    # Но у нас нет callback, поэтому просто отправляем сообщение с клавиатурой профиля
    # Чтобы не дублировать код, можно вызвать show_profile, но ему нужен callback.
    # Проще отправить руками:
    
    # Или лучше: создадим фейковый callback (плохая практика) или выделим show_profile в отдельную функцию (хорошая практика).
    # Но пока просто отправим сообщение меню.
    await message.answer(texts['user_panel']['main_menu_text'], reply_markup=kb.get_main_menu_keyboard())