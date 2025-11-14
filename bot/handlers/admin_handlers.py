import asyncio
import json
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.orm import selectinload

from bot.db.models import User
from bot.db.repository import Repository
from bot.keyboards import admin_keyboards as kb
from bot.middlewares.admin_check import AdminCheckMiddleware
from bot.services.coingecko_service import coingecko_service
from bot.services.ton_service import ton_service
from bot.db.models import Payout, PayoutStatus

BASE_DIR = Path(__file__).resolve().parent.parent.parent
with open(BASE_DIR / 'texts.json', 'r', encoding='utf-8') as f:
    texts = json.load(f)

# --- FSM States ---
class VideoRejection(StatesGroup):
    waiting_for_reason = State()

class BonusFSM(StatesGroup):
    waiting_for_username = State()
    waiting_for_amount = State()

admin_router = Router()
admin_router.message.middleware(AdminCheckMiddleware())
admin_router.callback_query.middleware(AdminCheckMiddleware())

# --- Helper Function for Admin Panel ---
async def show_admin_panel(bot: Bot, chat_id: int, repo: Repository):
    """Всегда отправляет НОВОЕ сообщение с главной админ-панелью."""
    queue_count = await repo.get_queue_count()
    payout_count = await repo.get_pending_payouts_count()
    text = texts['admin_panel']['welcome']
    reply_markup = kb.get_admin_main_menu(queue_count=queue_count, payout_count=payout_count)
    await bot.send_message(chat_id, text, reply_markup=reply_markup)


# --- Main Panel Navigation ---
@admin_router.message(Command("admin"))
async def admin_panel_handler(message: Message, repo: Repository, bot: Bot):
    await message.delete()
    await show_admin_panel(bot, message.chat.id, repo)

@admin_router.callback_query(F.data == "back_to_admin_main")
async def back_to_admin_main_handler(callback: CallbackQuery, repo: Repository, bot: Bot):
    await callback.message.delete()
    await show_admin_panel(bot, callback.message.chat.id, repo)
    await callback.answer()

@admin_router.callback_query(F.data == "admin_cancel_action", StateFilter("*"))
async def admin_cancel_handler(callback: CallbackQuery, state: FSMContext, repo: Repository, bot: Bot):
    await state.clear()
    await callback.message.delete()
    await show_admin_panel(bot, callback.message.chat.id, repo)
    await callback.answer(texts['admin_panel']['bonus_action_cancelled'], show_alert=False)


# --- Video Review Logic ---
@admin_router.callback_query(F.data == "get_video_review")
async def get_video_for_review_handler(callback: CallbackQuery, repo: Repository, bot: Bot):
    await callback.message.delete()
    video = await repo.get_oldest_video_from_queue()
    if not video:
        await callback.answer(texts['admin_panel']['queue_empty'], show_alert=True)
    else:
        user = video.user
        username = f"@{user.username}" if user.username else f"ID: {user.tg_id}"
        review_text = texts['admin_panel']['review_request'].format(
            username=username, link=video.link, created_at=video.created_at.strftime('%Y-%m-%d %H:%M')
        )
        await callback.message.answer(
            review_text, reply_markup=kb.get_video_review_keyboard(video_id=video.id), disable_web_page_preview=True
        )
    
    await show_admin_panel(bot, callback.message.chat.id, repo)
    await callback.answer()

@admin_router.callback_query(kb.VideoReviewCallback.filter(F.action == "accept"))
async def accept_video_handler(callback: CallbackQuery, callback_data: kb.VideoReviewCallback, repo: Repository, bot: Bot):
    video_id, amount = callback_data.video_id, 0.10
    try:
        processed_video = await repo.process_video_acceptance(video_id=video_id, admin_tg_id=callback.from_user.id, amount=amount)
    except ValueError:
        await callback.message.edit_text(texts['admin_panel']['error_already_processed']); await callback.answer(); return
    
    try:
        await bot.send_message(processed_video.user.tg_id, texts['user_notifications']['video_accepted'].format(amount=amount))
    except Exception as e:
        await callback.answer(texts['admin_panel']['error_notify_user_alert'].format(error=e), show_alert=True)
        
    await callback.message.delete()
    await callback.answer(texts['admin_panel']['video_accepted'].format(amount=amount), show_alert=False)

@admin_router.callback_query(kb.VideoReviewCallback.filter(F.action == "reject"))
async def reject_video_handler(callback: CallbackQuery, callback_data: kb.VideoReviewCallback, state: FSMContext):
    await callback.message.edit_text(texts['admin_panel']['ask_for_rejection_reason'])
    await state.set_state(VideoRejection.waiting_for_reason)
    await state.update_data(video_id=callback_data.video_id, original_message_id=callback.message.message_id)
    await callback.answer()

@admin_router.message(VideoRejection.waiting_for_reason)
async def rejection_reason_handler(message: Message, state: FSMContext, repo: Repository, bot: Bot):
    data = await state.get_data()
    video_id, original_message_id, reason = data.get("video_id"), data.get("original_message_id"), message.text
    await state.clear()
    
    try:
        processed_video = await repo.process_video_rejection(video_id=video_id, admin_tg_id=message.from_user.id, reason=reason)
    except ValueError:
        await bot.edit_message_text(chat_id=message.chat.id, message_id=original_message_id, text=texts['admin_panel']['error_already_processed']); return

    try:
        await bot.send_message(processed_video.user.tg_id, texts['user_notifications']['video_rejected'].format(reason=reason))
    except Exception as e:
        await message.answer(texts['admin_panel']['error_notify_user_alert'].format(error=e))
    
    await message.delete()
    await bot.delete_message(message.chat.id, original_message_id)


# --- Payout Logic ---
@admin_router.callback_query(F.data == "get_payout_request")
async def get_payout_request_handler(callback: CallbackQuery, repo: Repository, bot: Bot):
    await callback.message.delete()
    payout = await repo.get_oldest_payout_request()
    if not payout:
        await callback.answer(texts['admin_panel']['payout_queue_empty'], show_alert=True)
    else:
        user = payout.user
        username = f"@{user.username}" if user.username else f"ID: {user.tg_id}"
        text = texts['admin_panel']['payout_review_request'].format(username=username, amount=payout.amount, wallet=payout.wallet)
        await callback.message.answer(text, reply_markup=kb.get_payout_review_keyboard(payout_id=payout.id))
    
    await show_admin_panel(bot, callback.message.chat.id, repo)
    await callback.answer()

@admin_router.callback_query(kb.PayoutCallback.filter(F.action == "confirm"))
async def confirm_payout_handler(callback: CallbackQuery, callback_data: kb.PayoutCallback, repo: Repository, bot: Bot):
    payout = await repo.session.get(Payout, callback_data.payout_id, options=[selectinload(Payout.user)])
    if not payout or payout.status != PayoutStatus.PENDING:
        await callback.message.edit_text(texts['admin_panel']['error_already_processed']); await callback.answer(); return
    
    await callback.message.edit_text(texts['admin_panel']['payout_processing'])
    rate = coingecko_service.get_ton_to_usd_rate()
    if rate <= 0:
        await callback.message.edit_text(texts['admin_panel']['payout_error_api']); return
    
    amount_ton = payout.amount / rate
    tx_hash = await ton_service.send_transaction(to_address=payout.wallet, amount_ton=amount_ton, comment="Rocky Clips Payout")
    
    if tx_hash:
        await repo.confirm_payout(payout_id=payout.id, admin_tg_id=callback.from_user.id, tx_hash=tx_hash)
        await callback.message.delete()
        await callback.answer(texts['admin_panel']['payout_confirmed_admin'].format(tx_hash=tx_hash), show_alert=True)
        try:
            await bot.send_message(payout.user.tg_id, texts['user_notifications']['payout_confirmed_user'].format(amount=payout.amount, tx_hash=tx_hash))
        except Exception as e:
            await callback.answer(texts['admin_panel']['error_notify_user_alert'].format(error=e), show_alert=True)
    else:
        cancelled_payout = await repo.cancel_payout(payout_id=payout.id, admin_tg_id=callback.from_user.id)
        await callback.message.edit_text(texts['admin_panel']['payout_error_tx_admin'])
        try:
            await bot.send_message(cancelled_payout.user.tg_id, texts['user_notifications']['payout_failed_user'])
        except Exception as e:
            await callback.answer(texts['admin_panel']['error_notify_user_alert'].format(error=e), show_alert=True)
    
    await callback.answer()

@admin_router.callback_query(kb.PayoutCallback.filter(F.action == "cancel"))
async def cancel_payout_handler(callback: CallbackQuery, callback_data: kb.PayoutCallback, repo: Repository, bot: Bot):
    try:
        cancelled_payout = await repo.cancel_payout(payout_id=callback_data.payout_id, admin_tg_id=callback.from_user.id)
    except ValueError:
        await callback.message.edit_text(texts['admin_panel']['error_already_processed']); await callback.answer(); return
    
    try:
        await bot.send_message(cancelled_payout.user.tg_id, texts['user_notifications']['payout_cancelled_user'])
    except Exception as e:
        await callback.answer(texts['admin_panel']['error_notify_user_alert'].format(error=e), show_alert=True)
    
    await callback.message.delete()
    await callback.answer(texts['admin_panel']['payout_cancelled_admin'], show_alert=False)

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
async def get_global_stats_handler(callback: CallbackQuery, repo: Repository):
    await callback.message.delete()
    stats = await repo.get_global_stats()
    text = texts['admin_panel']['global_stats_message'].format(**stats)
    await callback.message.answer(
        text,
        reply_markup=kb.get_back_to_stats_menu_keyboard()
    )
    await callback.answer()

@admin_router.callback_query(F.data == "get_my_stats")
async def get_my_stats_handler(callback: CallbackQuery, repo: Repository):
    await callback.message.delete()
    admin_tg_id = callback.from_user.id
    stats = await repo.get_admin_stats(admin_tg_id)
    text = texts['admin_panel']['my_stats_message'].format(**stats)
    await callback.message.answer(
        text,
        reply_markup=kb.get_back_to_stats_menu_keyboard()
    )
    await callback.answer()


# --- Bonus Logic ---
@admin_router.callback_query(F.data == "give_bonus_start")
async def start_bonus_handler(callback: CallbackQuery, state: FSMContext):
    await state.update_data(main_panel_message_id=callback.message.message_id)
    await state.set_state(BonusFSM.waiting_for_username)
    await callback.message.edit_text(
        texts['admin_panel']['ask_for_bonus_username'],
        reply_markup=kb.get_admin_cancel_keyboard()
    )
    await callback.answer()

@admin_router.message(BonusFSM.waiting_for_username)
async def bonus_username_handler(message: Message, state: FSMContext, repo: Repository):
    username = message.text.lstrip('@').strip()
    user = await repo.get_user_by_username(username)
    
    data = await state.get_data()
    main_panel_message_id = data.get("main_panel_message_id")
    
    await message.delete()

    if not user:
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

    await state.update_data(target_user_id=user.id, target_username=user.username)
    await state.set_state(BonusFSM.waiting_for_amount)

    await message.bot.edit_message_text(
        chat_id=message.chat.id, message_id=main_panel_message_id,
        text=texts['admin_panel']['ask_for_bonus_amount'].format(username=f"@{user.username}"),
        reply_markup=kb.get_admin_cancel_keyboard()
    )

@admin_router.message(BonusFSM.waiting_for_amount)
async def bonus_amount_handler(message: Message, state: FSMContext, repo: Repository, bot: Bot):
    data = await state.get_data()
    main_panel_message_id = data.get("main_panel_message_id")
    username = data.get("target_username")
    user_id = data.get("target_user_id")

    await message.delete()

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
    
    await repo.add_bonus_to_user(user_id=user_id, amount=amount)
    await bot.edit_message_text(
        chat_id=message.chat.id, message_id=main_panel_message_id,
        text=texts['admin_panel']['bonus_success_admin'].format(amount=amount, username=f"@{username}")
    )
    
    try:
        user_obj = await repo.session.get(User, user_id)
        if user_obj:
            await bot.send_message(user_obj.tg_id, texts['user_notifications']['bonus_received'].format(amount=amount))
    except Exception as e:
        await message.answer(texts['admin_panel']['error_notify_user_alert'].format(error=e))

    await asyncio.sleep(3)
    await show_admin_panel(bot, message.chat.id, repo)


# --- Ban/Unban Logic ---
@admin_router.message(Command("ban"))
async def ban_user_handler(message: Message, repo: Repository, bot: Bot):
    args = message.text.split()
    if len(args) != 2:
        await message.answer(texts['admin_panel']['ban_error_format']); return
    
    username = args[1].lstrip('@')
    user = await repo.get_user_by_username(username)
    
    if not user:
        await message.answer(texts['admin_panel']['bonus_error_user_not_found'].format(username=f"@{username}")); return
    
    if user.is_banned:
        await message.answer(texts['admin_panel']['user_already_banned'].format(username=f"@{username}")); return
        
    await repo.ban_user(user.id)
    await message.answer(texts['admin_panel']['ban_success'].format(username=f"@{username}"))
    
    try:
        await bot.send_message(user.tg_id, texts['user_notifications']['user_banned'])
    except Exception as e:
        await message.answer(texts['admin_panel']['error_notify_user_alert'].format(error=e))

@admin_router.message(Command("unban"))
async def unban_user_handler(message: Message, repo: Repository, bot: Bot):
    args = message.text.split()
    if len(args) != 2:
        await message.answer(texts['admin_panel']['unban_error_format']); return
        
    username = args[1].lstrip('@')
    user = await repo.get_user_by_username(username)

    if not user:
        await message.answer(texts['admin_panel']['bonus_error_user_not_found'].format(username=f"@{username}")); return

    if not user.is_banned:
        await message.answer(texts['admin_panel']['user_not_banned'].format(username=f"@{username}")); return
        
    await repo.unban_user(user.id)
    await message.answer(texts['admin_panel']['unban_success'].format(username=f"@{username}"))

    try:
        await bot.send_message(user.tg_id, texts['user_notifications']['user_unbanned'])
    except Exception as e:
        await message.answer(texts['admin_panel']['error_notify_user_alert'].format(error=e))