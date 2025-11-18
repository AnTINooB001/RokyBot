# bot/keyboards/admin_keyboards.py

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- Callback Data Classes ---
class VideoReviewCallback(CallbackData, prefix="review"):
    action: str
    video_id: int

class PayoutCallback(CallbackData, prefix="payout"):
    action: str
    payout_id: int


# --- Keyboards ---

def get_admin_main_menu(queue_count: int = 0, payout_count: int = 0, is_super_admin: bool = False) -> InlineKeyboardMarkup:
    """
    Inline клавиатура для главного меню администратора.
    
    Args:
        queue_count: Количество видео в очереди на проверку.
        payout_count: Количество заявок на вывод (отображается только супер-админу).
        is_super_admin: Если True, показывает кнопку управления выплатами.
    """
    builder = InlineKeyboardBuilder()
    
    # 1. Кнопка проверки видео (Доступна всем админам/модераторам)
    builder.row(InlineKeyboardButton(text=f"📩 Видео на проверку ({queue_count})", callback_data="get_video_review"))
    
    # 2. Кнопка выплат (Доступна ТОЛЬКО Супер-Админу)
    if is_super_admin:
        builder.row(InlineKeyboardButton(text=f"💰 Запросы на вывод ({payout_count})", callback_data="get_payout_request"))
    
    # 3. Общие кнопки (Статистика и Бонусы)
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
    """Клавиатура для принятия/отклонения видео."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Принять", callback_data=VideoReviewCallback(action="accept", video_id=video_id).pack()),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=VideoReviewCallback(action="reject", video_id=video_id).pack())
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_admin_main"))
    return builder.as_markup()


def get_payout_review_keyboard(payout_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для обработки запроса на вывод (только для супер-админа)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить выплату", callback_data=PayoutCallback(action="confirm", payout_id=payout_id).pack()),
        InlineKeyboardButton(text="❌ Отменить", callback_data=PayoutCallback(action="cancel", payout_id=payout_id).pack())
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_admin_main"))
    return builder.as_markup()


def get_admin_cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой 'Отмена' для прерывания FSM админом."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Отмена", callback_data="back_to_admin_main"))
    return builder.as_markup()