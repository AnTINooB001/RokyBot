import asyncio
import json
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.exceptions import TelegramBadRequest

from pytoniq_core import Address

from bot.config import config
from bot.db.repository import Repository
from bot.keyboards import user_keyboards as kb
from bot.middlewares.throttling import RateLimiterMiddleware

# --- Global variables & setup ---
BASE_DIR = Path(__file__).resolve().parent.parent.parent
with open(BASE_DIR / 'texts.json', 'r', encoding='utf-8') as f:
    texts = json.load(f)

user_router = Router(name="user_router")
throttled_router = Router(name="throttled_router")

throttled_router.message.middleware(RateLimiterMiddleware(limit=10, period=3600))
user_router.include_router(throttled_router)


# --- FSM States ---
class Registration(StatesGroup):
    waiting_for_wallet = State()

class VideoSubmission(StatesGroup):
    waiting_for_link = State()

class ProfileUpdate(StatesGroup):
    waiting_for_new_wallet = State()


# --- Helper Functions ---

async def show_main_menu(bot: Bot, chat_id: int, message_id: int | None = None, text: str = None):
    """Отправляет или редактирует сообщение, показывая главное меню."""
    if text is None:
        text = texts['user_panel']['main_menu_text']
    
    reply_markup = kb.get_main_menu_keyboard()
    if message_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup
            )
        except TelegramBadRequest:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    else:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)

async def show_profile_panel(bot: Bot, chat_id: int, repo: Repository, message_id: int | None = None):
    """Отправляет или редактирует сообщение с профилем пользователя."""
    user = await repo.get_user_by_tg_id(chat_id)
    if not user:
        return

    on_review_count = await repo.count_videos_on_review(user.id)
    accepted_count = await repo.count_accepted_videos(user.id)
    rejected_count = await repo.count_rejected_videos(user.id)
    wallet_short = f"{user.wallet[:4]}...{user.wallet[-4:]}" if user.wallet else "Не указан"
    
    profile_text = texts['user_panel']['profile_text'].format(
        balance=user.balance,
        on_review_count=on_review_count,
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        wallet_short=wallet_short
    )
    
    reply_markup = kb.get_profile_keyboard()
    if message_id:
        try:
            await bot.edit_message_text(chat_id, message_id, profile_text, reply_markup=reply_markup)
        except TelegramBadRequest:
            await bot.send_message(chat_id, profile_text, reply_markup=reply_markup)
    else:
        await bot.send_message(chat_id, profile_text, reply_markup=reply_markup)


# --- Registration Flow ---

@user_router.message(CommandStart())
async def start_handler(message: Message, repo: Repository, bot: Bot):
    await message.delete()
    user = await repo.get_user_by_tg_id(message.from_user.id)
    if not user:
        user = await repo.create_user(tg_id=message.from_user.id, username=message.from_user.username)
    
    if user.wallet:
        await show_main_menu(bot, message.chat.id)
        return
    
    channel_url = f"https://t.me/{config.channel_id.lstrip('@')}"
    await message.answer(texts['start']['initial_welcome'], reply_markup=kb.get_subscribe_keyboard(channel_url))

@user_router.callback_query(F.data == "check_subscription")
async def check_subscription_callback_handler(callback: CallbackQuery, bot: Bot):
    try:
        member = await bot.get_chat_member(chat_id=config.channel_id, user_id=callback.from_user.id)
        if member.status in ["member", "administrator", "creator"]:
            await callback.message.delete()
            await bot.send_message(callback.from_user.id, texts['registration']['intro_text'])
            await bot.send_message(
                callback.from_user.id,
                texts['registration']['full_terms_and_conditions'],
                reply_markup=kb.get_understood_keyboard()
            )
            for video_path in config.video_paths:
                try:
                    full_path = BASE_DIR / video_path
                    video = FSInputFile(full_path)
                    await bot.send_video(callback.from_user.id, video)
                except Exception as e:
                    print(f"Error sending video {video_path}: {e}")
        else:
            await callback.answer(texts['start']['not_subscribed_alert'], show_alert=True)
    except TelegramBadRequest as e:
        error_text = texts['start']['subscription_error'].format(error_details=e)
        if callback.message:
            await callback.message.answer(error_text)
    finally:
        await callback.answer()

@user_router.callback_query(F.data == "understood_terms")
async def understood_terms_handler(callback: CallbackQuery, bot: Bot):
    await callback.message.edit_reply_markup(reply_markup=None)
    await bot.send_message(
        callback.from_user.id,
        texts['registration']['short_terms_agreement'],
        reply_markup=kb.get_final_agreement_keyboard()
    )
    await callback.answer()

@user_router.callback_query(F.data == "final_agree")
async def final_agree_handler(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.message.edit_reply_markup(reply_markup=None)
    
    prompt_message = await bot.send_message(
        callback.from_user.id,
        texts['registration']['ask_for_wallet']
    )
    
    await state.set_state(Registration.waiting_for_wallet)
    await state.update_data(prompt_message_id=prompt_message.message_id)
    await callback.answer()

@user_router.message(Registration.waiting_for_wallet)
async def wallet_handler(message: Message, state: FSMContext, repo: Repository, bot: Bot):
    data = await state.get_data()
    prompt_message_id = data.get("prompt_message_id")
    wallet_address = message.text.strip()
    
    await message.delete()

    try:
        Address(wallet_address)
        is_valid = True
    except Exception:
        is_valid = False

    if is_valid:
        await repo.update_user_wallet(tg_id=message.from_user.id, wallet_address=wallet_address)
        await state.clear()
        
        if prompt_message_id:
            try:
                await bot.delete_message(message.chat.id, prompt_message_id)
            except TelegramBadRequest:
                pass
            
        final_text = texts['registration']['wallet_saved'] + "\n\n" + texts['user_panel']['main_menu_text']
        await show_main_menu(bot, message.chat.id, text=final_text)
    else:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text=texts['registration']['invalid_wallet']
        )
        await asyncio.sleep(3)
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text=texts['registration']['ask_for_wallet']
        )


# --- Main Menu and Profile Handlers ---

@user_router.callback_query(F.data == "show_profile")
async def profile_handler(callback: CallbackQuery, repo: Repository, bot: Bot):
    await callback.message.delete()
    await show_profile_panel(bot, callback.from_user.id, repo)
    await callback.answer()

@user_router.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu_handler(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await show_main_menu(bot, callback.from_user.id)
    await callback.answer()


# --- Wallet Change Handlers ---

@user_router.callback_query(F.data == "change_wallet")
async def change_wallet_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        texts['user_panel']['ask_for_new_wallet'],
        reply_markup=kb.get_cancel_change_wallet_keyboard()
    )
    await state.set_state(ProfileUpdate.waiting_for_new_wallet)
    await state.update_data(prompt_message_id=callback.message.message_id)
    await callback.answer()

@user_router.message(ProfileUpdate.waiting_for_new_wallet)
async def new_wallet_handler(message: Message, state: FSMContext, repo: Repository, bot: Bot):
    data = await state.get_data()
    prompt_message_id = data.get("prompt_message_id")
    new_wallet_address = message.text.strip()
    await message.delete()
    
    try:
        Address(new_wallet_address)
        is_valid = True
    except Exception:
        is_valid = False

    if is_valid:
        await repo.update_user_wallet(tg_id=message.from_user.id, wallet_address=new_wallet_address)
        await state.clear()
        await bot.delete_message(message.chat.id, prompt_message_id)
        
        temp_msg = await message.answer(texts['user_panel']['wallet_changed_successfully'])
        await asyncio.sleep(2)
        await temp_msg.delete()
        
        await show_profile_panel(bot, message.chat.id, repo)
    else:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text=texts['registration']['invalid_wallet'],
            reply_markup=kb.get_cancel_change_wallet_keyboard()
        )
        await asyncio.sleep(3)
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            text=texts['user_panel']['ask_for_new_wallet'],
            reply_markup=kb.get_cancel_change_wallet_keyboard()
        )


# --- Video Submission Handlers ---

@user_router.callback_query(F.data == "send_video")
async def send_video_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        texts['user_panel']['ask_for_video_link'],
        reply_markup=kb.get_cancel_keyboard()
    )
    await state.set_state(VideoSubmission.waiting_for_link)
    await state.update_data(prompt_message_id=callback.message.message_id)
    await callback.answer()

@throttled_router.message(VideoSubmission.waiting_for_link)
async def receive_video_link_handler(message: Message, state: FSMContext, repo: Repository, bot: Bot):
    data = await state.get_data()
    prompt_message_id = data.get("prompt_message_id")
    await state.clear()
    await message.delete()

    if not message.text or not message.text.startswith(('http://', 'https://')):
        await bot.edit_message_text(
            texts['user_panel']['invalid_link'],
            chat_id=message.chat.id,
            message_id=prompt_message_id,
            reply_markup=kb.get_cancel_keyboard()
        )
        await state.set_state(VideoSubmission.waiting_for_link)
        await state.update_data(prompt_message_id=prompt_message_id)
    else:
        user = await repo.get_user_by_tg_id(message.from_user.id)
        await repo.add_video_to_queue(user_id=user.id, link=message.text)
        await bot.delete_message(message.chat.id, prompt_message_id)
        await show_main_menu(bot, message.chat.id)


# --- Payout Handlers ---

@user_router.callback_query(F.data == "request_payout")
async def request_payout_handler(callback: CallbackQuery, repo: Repository):
    user = await repo.get_user_by_tg_id(callback.from_user.id)
    if await repo.has_pending_payout(user.id):
        await callback.answer(texts['user_panel']['payout_already_pending'], show_alert=True)
        return
    
    if user.balance >= config.min_payout_amount:
        text = texts['user_panel']['payout_confirm_request'].format(
            min_payout=config.min_payout_amount,
            balance=user.balance,
            wallet=user.wallet
        )
        await callback.message.edit_text(text, reply_markup=kb.get_confirm_payout_keyboard())
    else:
        await callback.answer(
            texts['user_panel']['payout_not_enough_balance'].format(min_payout=config.min_payout_amount),
            show_alert=True
        )
    await callback.answer()

@user_router.callback_query(F.data == "confirm_payout_request")
async def confirm_payout_request_handler(callback: CallbackQuery, repo: Repository, bot: Bot):
    user = await repo.get_user_by_tg_id(callback.from_user.id)
    if await repo.has_pending_payout(user.id):
        await callback.answer(texts['user_panel']['payout_already_pending'], show_alert=True)
        return
    
    await callback.message.delete()
    if user.balance >= config.min_payout_amount:
        await repo.create_payout_request(user, user.balance)
        await callback.answer(texts['user_panel']['payout_request_created'], show_alert=True)
    else:
        await callback.answer(
            texts['user_panel']['payout_not_enough_balance'].format(min_payout=config.min_payout_amount),
            show_alert=True
        )
    
    await show_profile_panel(bot, callback.from_user.id, repo)

@user_router.callback_query(F.data == "cancel_payout_request")
async def cancel_payout_request_handler(callback: CallbackQuery, repo: Repository, bot: Bot):
    await callback.message.delete()
    await callback.answer(texts['user_panel']['payout_request_cancelled'], show_alert=False)
    await show_profile_panel(bot, callback.from_user.id, repo)