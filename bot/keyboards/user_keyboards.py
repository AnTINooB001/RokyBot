# bot/keyboards/user_keyboards.py

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_subscribe_keyboard(channel_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔗 Подписаться", url=channel_url))
    builder.row(InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription"))
    return builder.as_markup()

def get_agreement_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Окей, я согласен", callback_data="agree_to_terms"))
    return builder.as_markup()

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🎬 Отправить видео")], [KeyboardButton(text="👤 Мой профиль")]],
        resize_keyboard=True, input_field_placeholder="Выберите действие из меню"
    )

def get_profile_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💸 Запросить вывод", callback_data="request_payout"))
    builder.row(InlineKeyboardButton(text="🔄 Назад в меню", callback_data="back_to_main_menu"))
    return builder.as_markup()

def get_confirm_payout_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для подтверждения запроса на вывод."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, подтвердить", callback_data="confirm_payout_request"),
        InlineKeyboardButton(text="❌ Нет, отменить", callback_data="cancel_payout_request")
    )
    return builder.as_markup()