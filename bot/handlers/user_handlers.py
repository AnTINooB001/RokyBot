import json
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from pytoniq_core import Address

from bot.config import config
from bot.db.repository import Repository
from bot.keyboards import user_keyboards as kb
# --- ИЗМЕНЕНИЕ 1: Импортируем новое middleware ---
from bot.middlewares.throttling import RateLimiterMiddleware

BASE_DIR = Path(__file__).resolve().parent.parent.parent
with open(BASE_DIR / 'texts.json', 'r', encoding='utf-8') as f:
    texts = json.load(f)

user_router = Router(name="user_router")
throttled_router = Router(name="throttled_router")

# --- ИЗМЕНЕНИЕ 2: Применяем новое middleware с нужными параметрами ---
# limit=10, period=3600 (10 сообщений в час)
throttled_router.message.middleware(RateLimiterMiddleware(limit=10, period=3600))

user_router.include_router(throttled_router)


class Registration(StatesGroup):
    waiting_for_wallet = State()

class VideoSubmission(StatesGroup):
    waiting_for_link = State()


@user_router.message(F.text == "👤 Мой профиль")
async def profile_handler(message: Message, repo: Repository):
    user = await repo.get_user_by_tg_id(message.from_user.id)
    if not user or not user.wallet:
        await message.answer(texts['user_panel']['registration_needed'])
        return
    on_review_count = await repo.count_videos_on_review(user.id)
    accepted_count = await repo.count_accepted_videos(user.id)
    rejected_count = await repo.count_rejected_videos(user.id)
    wallet_short = f"{user.wallet[:4]}...{user.wallet[-4:]}"
    profile_text = texts['user_panel']['profile_text'].format(balance=user.balance, on_review_count=on_review_count, accepted_count=accepted_count, rejected_count=rejected_count, wallet_short=wallet_short)
    await message.answer(profile_text, reply_markup=kb.get_profile_keyboard())


@user_router.message(F.text == "🎬 Отправить видео")
async def send_video_handler(message: Message, state: FSMContext, repo: Repository):
    user = await repo.get_user_by_tg_id(message.from_user.id)
    if not user or not user.wallet:
        await message.answer(texts['user_panel']['registration_needed'])
        return
    await message.answer(texts['user_panel']['ask_for_video_link'])
    await state.set_state(VideoSubmission.waiting_for_link)


@throttled_router.message(VideoSubmission.waiting_for_link)
async def receive_video_link_handler(message: Message, state: FSMContext, repo: Repository):
    if not message.text or not message.text.startswith(('http://', 'https://')):
        await message.answer(texts['user_panel']['invalid_link'])
        return
    user = await repo.get_user_by_tg_id(message.from_user.id)
    await repo.add_video_to_queue(user_id=user.id, link=message.text)
    await state.clear()
    await message.answer(texts['user_panel']['video_submitted'])


@user_router.callback_query(F.data == "request_payout")
async def request_payout_handler(callback: CallbackQuery, repo: Repository, state: FSMContext):
    user = await repo.get_user_by_tg_id(callback.from_user.id)
    has_pending = await repo.has_pending_payout(user.id)
    if has_pending:
        await callback.answer(texts['user_panel']['payout_already_pending'], show_alert=True)
        return
    if user.balance >= config.min_payout_amount:
        text = texts['user_panel']['payout_confirm_request'].format(min_payout=config.min_payout_amount, balance=user.balance, wallet=user.wallet)
        await callback.message.edit_text(text, reply_markup=kb.get_confirm_payout_keyboard())
    else:
        text = texts['user_panel']['payout_not_enough_balance'].format(min_payout=config.min_payout_amount)
        await callback.answer(text, show_alert=True)


@user_router.callback_query(F.data == "confirm_payout_request")
async def confirm_payout_request_handler(callback: CallbackQuery, repo: Repository, state: FSMContext):
    user = await repo.get_user_by_tg_id(callback.from_user.id)
    has_pending = await repo.has_pending_payout(user.id)
    if has_pending:
        await callback.message.edit_text(texts['user_panel']['payout_already_pending'])
        await callback.answer()
        return
    if user.balance >= config.min_payout_amount:
        await repo.create_payout_request(user, user.balance)
        await callback.message.edit_text(texts['user_panel']['payout_request_created'])
    else:
        text = texts['user_panel']['payout_not_enough_balance'].format(min_payout=config.min_payout_amount)
        await callback.message.edit_text(text)
    await callback.answer()

@user_router.callback_query(F.data == "cancel_payout_request")
async def cancel_payout_request_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(texts['user_panel']['payout_request_cancelled'])
    await callback.answer()


@user_router.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu_handler(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


@user_router.message(CommandStart())
async def start_handler(message: Message, repo: Repository, bot: Bot):
    user = await repo.get_user_by_tg_id(message.from_user.id)
    if not user:
        user = await repo.create_user(tg_id=message.from_user.id, username=message.from_user.username)
    if user.wallet:
        await message.answer(texts['user_panel']['already_registered'], reply_markup=kb.get_main_menu_keyboard())
        return
    await check_subscription_and_proceed(user.tg_id, bot, message=message)


@user_router.callback_query(F.data == "check_subscription")
async def check_subscription_callback_handler(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    await check_subscription_and_proceed(callback.from_user.id, bot, callback=callback)


@user_router.callback_query(F.data == "agree_to_terms")
async def agree_to_terms_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(texts['registration']['ask_for_wallet'])
    await state.set_state(Registration.waiting_for_wallet)
    await callback.answer()


@user_router.message(Registration.waiting_for_wallet)
async def wallet_handler(message: Message, state: FSMContext, repo: Repository):
    wallet_address = message.text.strip()
    try:
        Address(wallet_address)
        is_valid = True
    except Exception: is_valid = False
    if is_valid:
        await repo.update_user_wallet(tg_id=message.from_user.id, wallet_address=wallet_address)
        await state.clear()
        await message.answer(texts['registration']['wallet_saved'], reply_markup=kb.get_main_menu_keyboard())
    else:
        await message.answer(texts['registration']['invalid_wallet'])


async def check_subscription_and_proceed(user_id: int, bot: Bot, message: Message = None, callback: CallbackQuery = None):
    target_entity = callback.message if callback else message
    if not target_entity: return
    try:
        member = await bot.get_chat_member(chat_id=config.channel_id, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            await target_entity.answer(texts['registration']['terms_and_conditions'], reply_markup=kb.get_agreement_keyboard())
            if callback: await callback.message.delete()
        else: await send_subscription_message(message, callback)
    except TelegramBadRequest as e:
        error_text = texts['start']['subscription_error'].format(error_details=e)
        await target_entity.answer(error_text)


async def send_subscription_message(message: Message = None, callback: CallbackQuery = None):
    user_entity = message.from_user if message else callback.from_user
    text = texts['start']['welcome'].format(user_name=user_entity.first_name)
    reply_markup = kb.get_subscribe_keyboard(f"https://t.me/{config.channel_id.lstrip('@')}")
    if callback: await callback.answer(texts['start']['not_subscribed_alert'], show_alert=True)
    elif message: await message.answer(text, reply_markup=reply_markup)