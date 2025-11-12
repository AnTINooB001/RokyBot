from aiogram.filters.callback_data import CallbackData
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

class VideoReviewCallback(CallbackData, prefix="review"):
    action: str
    video_id: int

class PayoutCallback(CallbackData, prefix="payout"):
    action: str # 'confirm' or 'cancel'
    payout_id: int

def get_admin_main_menu(queue_count: int = 0, payout_count: int = 0) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"📩 Получить видео на проверку ({queue_count})")],
            [KeyboardButton(text=f"💰 Получить запрос на вывод ({payout_count})")],
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🎁 Начислить бонус")]
        ],
        resize_keyboard=True
    )

def get_video_review_keyboard(video_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Принять", callback_data=VideoReviewCallback(action="accept", video_id=video_id).pack()),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=VideoReviewCallback(action="reject", video_id=video_id).pack())
    )
    return builder.as_markup()

def get_payout_review_keyboard(payout_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для обработки запроса на вывод админом."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить выплату", callback_data=PayoutCallback(action="confirm", payout_id=payout_id).pack()),
        InlineKeyboardButton(text="❌ Отменить", callback_data=PayoutCallback(action="cancel", payout_id=payout_id).pack())
    )
    return builder.as_markup()