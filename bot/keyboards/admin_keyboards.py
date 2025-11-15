# bot/keyboards/admin_keyboards.py

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

class VideoReviewCallback(CallbackData, prefix="review"):
    action: str
    video_id: int

class PayoutCallback(CallbackData, prefix="payout"):
    action: str
    payout_id: int

def get_admin_main_menu(queue_count: int = 0, payout_count: int = 0) -> InlineKeyboardMarkup:
    """
    Inline клавиатура для главного меню администратора.
    """
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"📩 Видео на проверку ({queue_count})", callback_data="get_video_review"))
    builder.row(InlineKeyboardButton(text=f"💰 Запросы на вывод ({payout_count})", callback_data="get_payout_request"))
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="show_stats_menu"),
        InlineKeyboardButton(text="🎁 Начислить бонус", callback_data="give_bonus_start")
    )
    return builder.as_markup()

def get_stats_menu_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для меню выбора статистики."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📈 Моя статистика", callback_data="get_my_stats"))
    builder.row(InlineKeyboardButton(text="🌍 Общая статистика", callback_data="get_global_stats"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_admin_main"))
    return builder.as_markup()

def get_back_to_stats_menu_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой 'Назад' в меню статистики."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню статистики", callback_data="show_stats_menu"))
    return builder.as_markup()

def get_video_review_keyboard(video_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Принять", callback_data=VideoReviewCallback(action="accept", video_id=video_id).pack()),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=VideoReviewCallback(action="reject", video_id=video_id).pack())
    )
    # --- ДОБАВЛЯЕМ КНОПКУ НАЗАД ---
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_admin_main"))
    return builder.as_markup()

def get_payout_review_keyboard(payout_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для обработки запроса на вывод админом."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить выплату", callback_data=PayoutCallback(action="confirm", payout_id=payout_id).pack()),
        InlineKeyboardButton(text="❌ Отменить", callback_data=PayoutCallback(action="cancel", payout_id=payout_id).pack())
    )
    # --- ДОБАВЛЯЕМ КНОПКУ НАЗАД ---
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_admin_main"))
    return builder.as_markup()

def get_admin_cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой 'Отмена' для прерывания FSM админом."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Отмена", callback_data="back_to_admin_main"))
    return builder.as_markup()