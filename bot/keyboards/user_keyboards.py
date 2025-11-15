# bot/keyboards/user_keyboards.py

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_subscribe_keyboard(channel_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔗 Подписаться", url=channel_url))
    builder.row(InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription"))
    return builder.as_markup()

def get_understood_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для подтверждения прочтения полных условий."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Все понял!, давай дальше", callback_data="understood_terms"))
    return builder.as_markup()

def get_final_agreement_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для финального согласия с короткими условиями."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Да, согласен", callback_data="final_agree"))
    return builder.as_markup()

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Inline клавиатура для главного меню."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎬 Отправить видео", callback_data="send_video"))
    builder.row(InlineKeyboardButton(text="👤 Мой профиль", callback_data="show_profile"))
    return builder.as_markup()

def get_profile_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💸 Запросить вывод", callback_data="request_payout"))
    # --- НОВАЯ КНОПКА ---
    builder.row(InlineKeyboardButton(text="✏️ Изменить кошелек", callback_data="change_wallet"))
    # ------------------
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_main_menu"))
    return builder.as_markup()

def get_confirm_payout_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для подтверждения запроса на вывод."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, подтвердить", callback_data="confirm_payout_request"),
        InlineKeyboardButton(text="❌ Нет, отменить", callback_data="cancel_payout_request")
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="show_profile"))
    return builder.as_markup()

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с одной кнопкой 'Отмена', ведущей в главное меню."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_main_menu"))
    return builder.as_markup()

# --- НОВАЯ КЛАВИАТУРА ДЛЯ ОТМЕНЫ СМЕНЫ КОШЕЛЬКА ---
def get_cancel_change_wallet_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с одной кнопкой 'Отмена', ведущей обратно в профиль."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="show_profile"))
    return builder.as_markup()