# bot/handlers/admin_handlers.py

import json
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.orm import selectinload # <-- Добавим этот импорт для чистоты

from bot.db.repository import Repository
from bot.keyboards import admin_keyboards as kb
from bot.middlewares.admin_check import AdminCheckMiddleware
from bot.services.coingecko_service import coingecko_service
from bot.services.ton_service import ton_service
# --- ИЗМЕНЕНИЕ ЗДЕСЬ: Импортируем Payout и PayoutStatus ---
from bot.db.models import Payout, PayoutStatus

BASE_DIR = Path(__file__).resolve().parent.parent.parent
with open(BASE_DIR / 'texts.json', 'r', encoding='utf-8') as f:
    texts = json.load(f)

class VideoRejection(StatesGroup):
    waiting_for_reason = State()

admin_router = Router()
admin_router.message.middleware(AdminCheckMiddleware())
admin_router.callback_query.middleware(AdminCheckMiddleware())


@admin_router.message(Command("admin"))
async def admin_panel_handler(message: Message, repo: Repository):
    queue_count = await repo.get_queue_count()
    payout_count = await repo.get_pending_payouts_count()
    await message.answer(texts['admin_panel']['welcome'], reply_markup=kb.get_admin_main_menu(queue_count=queue_count, payout_count=payout_count))

# --- Логика проверки видео ---
@admin_router.message(F.text.startswith("📩 Получить видео на проверку"))
async def get_video_for_review_handler(message: Message, repo: Repository):
    video = await repo.get_oldest_video_from_queue()
    if not video:
        await message.answer(texts['admin_panel']['queue_empty'])
        return
    user = video.user
    username = f"@{user.username}" if user.username else f"ID: {user.tg_id}"
    review_text = texts['admin_panel']['review_request'].format(username=username, link=video.link, created_at=video.created_at.strftime('%Y-%m-%d %H:%M'))
    await message.answer(review_text, reply_markup=kb.get_video_review_keyboard(video_id=video.id), disable_web_page_preview=True)

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
    await callback.message.edit_text(texts['admin_panel']['video_accepted'].format(amount=amount)); await callback.answer()

@admin_router.callback_query(kb.VideoReviewCallback.filter(F.action == "reject"))
async def reject_video_handler(callback: CallbackQuery, callback_data: kb.VideoReviewCallback, state: FSMContext):
    try:
        await callback.message.edit_text(texts['admin_panel']['ask_for_rejection_reason'])
        await state.set_state(VideoRejection.waiting_for_reason)
        await state.update_data(video_id=callback_data.video_id, original_message_id=callback.message.message_id)
    except TelegramBadRequest:
        await callback.answer("Сообщение слишком старое для ответа, получите заявку заново.", show_alert=True)
    finally:
        await callback.answer()

@admin_router.message(VideoRejection.waiting_for_reason)
async def rejection_reason_handler(message: Message, state: FSMContext, repo: Repository, bot: Bot):
    data = await state.get_data()
    video_id, original_message_id, reason = data.get("video_id"), data.get("original_message_id"), message.text
    await state.clear()
    try:
        processed_video = await repo.process_video_rejection(video_id=video_id, admin_tg_id=message.from_user.id, reason=reason)
    except ValueError:
        try: await bot.edit_message_text(message.chat.id, original_message_id, texts['admin_panel']['error_already_processed'])
        except TelegramBadRequest: await message.answer(texts['admin_panel']['error_already_processed'])
        return
    try:
        await bot.send_message(processed_video.user.tg_id, texts['user_notifications']['video_rejected'].format(reason=reason))
    except Exception as e:
        await message.answer(texts['admin_panel']['error_notify_user_alert'].format(error=e))
    try:
        await message.delete()
        await bot.delete_message(message.chat.id, original_message_id)
    except TelegramBadRequest: pass
    await message.answer(texts['admin_panel']['video_rejected'].format(reason=reason))

# --- Логика обработки выплат ---
@admin_router.message(F.text.startswith("💰 Получить запрос на вывод"))
async def get_payout_request_handler(message: Message, repo: Repository):
    payout = await repo.get_oldest_payout_request()
    if not payout:
        await message.answer(texts['admin_panel']['payout_queue_empty']); return
    user = payout.user
    username = f"@{user.username}" if user.username else f"ID: {user.tg_id}"
    text = texts['admin_panel']['payout_review_request'].format(username=username, amount=payout.amount, wallet=payout.wallet)
    await message.answer(text, reply_markup=kb.get_payout_review_keyboard(payout_id=payout.id))

@admin_router.callback_query(kb.PayoutCallback.filter(F.action == "confirm"))
async def confirm_payout_handler(callback: CallbackQuery, callback_data: kb.PayoutCallback, repo: Repository, bot: Bot):
    payout_id = callback_data.payout_id
    # Используем session.get, так как это прямой доступ по первичному ключу
    payout = await repo.session.get(Payout, payout_id, options=[selectinload(Payout.user)])
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
        await callback.message.edit_text(texts['admin_panel']['payout_confirmed_admin'].format(tx_hash=tx_hash))
        try:
            await bot.send_message(payout.user.tg_id, texts['user_notifications']['payout_confirmed_user'].format(amount=payout.amount, tx_hash=tx_hash))
        except Exception as e:
            await callback.answer(texts['admin_panel']['error_notify_user_alert'].format(error=e), show_alert=True)
    else:
        await callback.message.edit_text(texts['admin_panel']['payout_error_tx'])
    await callback.answer()

@admin_router.callback_query(kb.PayoutCallback.filter(F.action == "cancel"))
async def cancel_payout_handler(callback: CallbackQuery, callback_data: kb.PayoutCallback, repo: Repository, bot: Bot):
    try:
        # Вызываем наш исправленный/проверенный метод
        cancelled_payout = await repo.cancel_payout(payout_id=callback_data.payout_id, admin_tg_id=callback.from_user.id)
    except ValueError:
        await callback.message.edit_text(texts['admin_panel']['error_already_processed']); await callback.answer(); return
    
    # Сообщаем админу
    await callback.message.edit_text(texts['admin_panel']['payout_cancelled_admin'])
    
    # Уведомляем пользователя, что деньги вернулись на баланс
    try:
        await bot.send_message(cancelled_payout.user.tg_id, texts['user_notifications']['payout_cancelled_user'])
    except Exception as e:
        await callback.answer(texts['admin_panel']['error_notify_user_alert'].format(error=e), show_alert=True)
    
    await callback.answer()

# --- Команды статистики и бонусов ---
@admin_router.message(F.text == "📊 Статистика")
@admin_router.message(Command("stats"))
async def stats_handler(message: Message, repo: Repository):
    stats = await repo.get_global_stats()
    await message.answer(texts['admin_panel']['stats_message'].format(**stats))

@admin_router.message(F.text == "🎁 Начислить бонус")
async def bonus_instruction_handler(message: Message):
    await message.answer(texts['admin_panel']['bonus_instruction'])

@admin_router.message(Command("bonus"))
async def bonus_command_handler(message: Message, repo: Repository, bot: Bot):
    args = message.text.split()
    if len(args) != 3:
        await message.answer(texts['admin_panel']['bonus_error_format']); return
    username, amount_str = args[1].lstrip('@'), args[2]
    try: amount = float(amount_str)
    except ValueError: await message.answer(texts['admin_panel']['bonus_error_invalid_amount']); return
    user = await repo.get_user_by_username(username)
    if not user:
        await message.answer(texts['admin_panel']['bonus_error_user_not_found'].format(username=f"@{username}")); return
    await repo.add_bonus_to_user(user_id=user.id, amount=amount)
    await message.answer(texts['admin_panel']['bonus_success_admin'].format(amount=amount, username=f"@{username}"))
    try:
        await bot.send_message(user.tg_id, texts['user_notifications']['bonus_received'].format(amount=amount))
    except Exception as e:
        await message.answer(texts['admin_panel']['error_notify_user_alert'].format(error=e))