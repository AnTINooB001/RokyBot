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

class UserActionCallback(CallbackData, prefix="user_act"):
    action: str  # "ban" или "unban"
    user_id: int # ID пользователя в базе данных

class AdminManageCallback(CallbackData, prefix="adm_mng"):
    action: str      # "add", "list", "remove", "back"
    user_id: int = 0 # ID пользователя для удаления (по умолчанию 0)


# --- Keyboards ---

def get_admin_main_menu(queue_count: int = 0, payout_count: int = 0, is_super_admin: bool = False) -> InlineKeyboardMarkup:
    """
    Inline клавиатура для главного меню администратора.
    """
    builder = InlineKeyboardBuilder()
    
    # 1. Кнопка проверки видео (Доступна всем)
    builder.row(InlineKeyboardButton(text=f"📩 Видео на проверку ({queue_count})", callback_data="get_video_review"))
    
    # 2. Функции Супер-Админа
    if is_super_admin:
        builder.row(InlineKeyboardButton(text=f"💰 Запросы на вывод ({payout_count})", callback_data="get_payout_request"))
        # Новая кнопка управления админами
        builder.row(InlineKeyboardButton(text="👮 Управление админами", callback_data="admin_manage_menu"))
    
    # 3. Статистика и Управление пользователями (Баны)
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="show_stats_menu"),
        InlineKeyboardButton(text="👥 Управление юзерами", callback_data="manage_users_start")
    )
    
    # 4. Бонусы
    builder.row(InlineKeyboardButton(text="🎁 Начислить бонус", callback_data="give_bonus_start"))
    
    return builder.as_markup()


def get_admin_management_menu() -> InlineKeyboardMarkup:
    """Меню управления администраторами."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить админа", callback_data=AdminManageCallback(action="add").pack()))
    builder.row(InlineKeyboardButton(text="📋 Список админов", callback_data=AdminManageCallback(action="list").pack()))
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_admin_main"))
    return builder.as_markup()


def get_admins_list_keyboard(admins_list: list) -> InlineKeyboardMarkup:
    """Генерирует список админов с кнопками для их удаления."""
    builder = InlineKeyboardBuilder()
    
    for admin in admins_list:
        # Отображаем username или ID, если username нет
        label = f"🗑 {admin.username or admin.tg_id}"
        builder.row(InlineKeyboardButton(
            text=label, 
            callback_data=AdminManageCallback(action="remove", user_id=admin.id).pack()
        ))
        
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_manage_menu"))
    return builder.as_markup()


def get_stats_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📈 Моя статистика", callback_data="get_my_stats"))
    builder.row(InlineKeyboardButton(text="🌍 Общая статистика", callback_data="get_global_stats"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_admin_main"))
    return builder.as_markup()


def get_back_to_stats_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню статистики", callback_data="show_stats_menu"))
    return builder.as_markup()


def get_video_review_keyboard(video_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Принять", callback_data=VideoReviewCallback(action="accept", video_id=video_id).pack()),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=VideoReviewCallback(action="reject", video_id=video_id).pack())
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_admin_main"))
    return builder.as_markup()


def get_payout_review_keyboard(payout_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить выплату", callback_data=PayoutCallback(action="confirm", payout_id=payout_id).pack()),
        InlineKeyboardButton(text="❌ Отменить", callback_data=PayoutCallback(action="cancel", payout_id=payout_id).pack())
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_admin_main"))
    return builder.as_markup()


def get_user_management_keyboard(db_user_id: int, is_banned: bool, can_manage: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    if can_manage:
        if is_banned:
            builder.row(InlineKeyboardButton(
                text="✅ Разблокировать", 
                callback_data=UserActionCallback(action="unban", user_id=db_user_id).pack()
            ))
        else:
            builder.row(InlineKeyboardButton(
                text="🚫 Заблокировать", 
                callback_data=UserActionCallback(action="ban", user_id=db_user_id).pack()
            ))
    
    builder.row(InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_admin_main"))
    return builder.as_markup()


def get_admin_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Отмена", callback_data="back_to_admin_main"))
    return builder.as_markup()