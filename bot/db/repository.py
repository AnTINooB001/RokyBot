# bot/db/repository.py

import datetime
from typing import Dict, Any
from sqlalchemy import select, update, func, delete, or_, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# Импортируем ActionLog и другие модели
from bot.db.models import User, Video, VideoHistory, VideoStatus, Payout, PayoutStatus, ActionLog


class Repository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # --- Методы для работы с пользователями (User) ---

    async def get_user_by_tg_id(self, tg_id: int) -> User | None:
        query = select(User).where(User.tg_id == tg_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_user_by_username(self, username: str) -> User | None:
        query = select(User).where(func.lower(User.username) == username.lower())
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_user(self, tg_id: int, username: str | None = None) -> User:
        new_user = User(tg_id=tg_id, username=username)
        self.session.add(new_user)
        await self.session.flush()
        return new_user

    async def update_user_wallet(self, tg_id: int, wallet_address: str) -> None:
        stmt = update(User).where(User.tg_id == tg_id).values(wallet=wallet_address, subscribed=True)
        await self.session.execute(stmt)

    async def add_bonus_to_user(self, user_id: int, amount: float) -> None:
        stmt = update(User).where(User.id == user_id).values(balance=User.balance + amount)
        await self.session.execute(stmt)

    async def ban_user(self, user_id: int) -> None:
        stmt = update(User).where(User.id == user_id).values(is_banned=True)
        await self.session.execute(stmt)

    async def unban_user(self, user_id: int) -> None:
        stmt = update(User).where(User.id == user_id).values(is_banned=False)
        await self.session.execute(stmt)

    # --- Admin Management ---
    async def set_admin_status(self, user_id: int, is_admin: bool) -> None:
        """Назначает или снимает права админа."""
        stmt = update(User).where(User.id == user_id).values(is_admin=is_admin)
        await self.session.execute(stmt)

    async def get_all_admins(self) -> list[User]:
        """Возвращает список всех админов из БД."""
        query = select(User).where(User.is_admin == True)
        result = await self.session.execute(query)
        return result.scalars().all()

    # --- Методы для работы с видео (Video) ---

    async def add_video_to_queue(self, user_id: int, link: str) -> Video:
        new_video = Video(user_id=user_id, link=link)
        self.session.add(new_video)
        return new_video
    
    async def get_video_for_review(self, admin_tg_id: int, lock_timeout_minutes: int = 15) -> Video | None:
        """
        Ищет старейшее видео, которое свободно или чей замок истек,
        и атомарно блокирует его за admin_tg_id.
        """
        now = datetime.datetime.now()
        timeout_threshold = now - datetime.timedelta(minutes=lock_timeout_minutes)
        
        # 1. Находим ID подходящего видео (свободно ИЛИ таймаут)
        subquery = (
            select(Video.id)
            .where(
                or_(
                    Video.locked_by_admin_id.is_(None),
                    Video.locked_at < timeout_threshold
                )
            )
            .order_by(Video.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True) 
            .scalar_subquery()
        )

        # 2. Атомарно обновляем это видео (ставим свой замок)
        stmt = (
            update(Video)
            .where(Video.id == subquery)
            .values(
                locked_by_admin_id=admin_tg_id,
                locked_at=now
            )
            .returning(Video)
        )
        
        result = await self.session.execute(stmt)
        video = result.scalar_one_or_none()
        
        if video:
            # Подгружаем юзера, так как returning вернул только видео
            await self.session.refresh(video, ["user"])
            
        return video

    async def unlock_video(self, video_id: int) -> None:
        """Снимает блокировку с видео."""
        stmt = (
            update(Video)
            .where(Video.id == video_id)
            .values(locked_by_admin_id=None, locked_at=None)
        )
        await self.session.execute(stmt)

    async def get_queue_count(self) -> int:
        query = select(func.count(Video.id))
        result = await self.session.execute(query)
        return result.scalar_one()

    async def process_video_acceptance(self, video_id: int, admin_tg_id: int, amount: float) -> Video:
        video_to_process = await self.session.get(Video, video_id, options=[selectinload(Video.user)])
        if not video_to_process: raise ValueError("Video not found")
        
        user_update_stmt = update(User).where(User.id == video_to_process.user_id).values(balance=User.balance + amount)
        await self.session.execute(user_update_stmt)
        
        history_record = VideoHistory(user_id=video_to_process.user_id, link=video_to_process.link, status=VideoStatus.ACCEPTED, admin_tg_id=admin_tg_id, created_at=video_to_process.created_at)
        self.session.add(history_record)
        await self.session.delete(video_to_process)
        return video_to_process

    async def process_video_rejection(self, video_id: int, admin_tg_id: int, reason: str) -> Video:
        video_to_process = await self.session.get(Video, video_id, options=[selectinload(Video.user)])
        if not video_to_process: raise ValueError("Video not found")
        
        history_record = VideoHistory(user_id=video_to_process.user_id, link=video_to_process.link, status=VideoStatus.REJECTED, reason=reason, admin_tg_id=admin_tg_id, created_at=video_to_process.created_at)
        self.session.add(history_record)
        await self.session.delete(video_to_process)
        return video_to_process

    # --- Методы для работы с выплатами (Payout) ---

    async def create_payout_request(self, user: User, amount: float) -> Payout:
        payout = Payout(user_id=user.id, amount=amount, wallet=user.wallet)
        self.session.add(payout)
        user.balance -= amount
        self.session.add(user)
        await self.session.flush()
        return payout
        
    async def get_oldest_payout_request(self) -> Payout | None:
        query = select(Payout).options(selectinload(Payout.user)).where(Payout.status == PayoutStatus.PENDING).order_by(Payout.created_at.asc()).limit(1)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
        
    async def get_pending_payouts_count(self) -> int:
        query = select(func.count(Payout.id)).where(Payout.status == PayoutStatus.PENDING)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def confirm_payout(self, payout_id: int, admin_tg_id: int, tx_hash: str) -> None:
        stmt = update(Payout).where(Payout.id == payout_id).values(status=PayoutStatus.PAID, admin_tg_id=admin_tg_id, tx_hash=tx_hash)
        await self.session.execute(stmt)

    async def cancel_payout(self, payout_id: int, admin_tg_id: int) -> Payout:
        payout = await self.session.get(Payout, payout_id, options=[selectinload(Payout.user)])
        if not payout: 
            raise ValueError("Payout not found")
        
        user_update_stmt = (
            update(User)
            .where(User.id == payout.user_id)
            .values(balance=User.balance + payout.amount)
        )
        await self.session.execute(user_update_stmt)
        
        payout.status = PayoutStatus.CANCELLED
        payout.admin_tg_id = admin_tg_id
        self.session.add(payout)
        
        return payout

    # --- МЕТОДЫ ДЛЯ СТАТИСТИКИ ---
    async def count_videos_on_review(self, user_id: int) -> int:
        query = select(func.count(Video.id)).where(Video.user_id == user_id)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def count_accepted_videos(self, user_id: int) -> int:
        query = select(func.count(VideoHistory.id)).where(VideoHistory.user_id == user_id, VideoHistory.status == VideoStatus.ACCEPTED)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def count_rejected_videos(self, user_id: int) -> int:
        query = select(func.count(VideoHistory.id)).where(VideoHistory.user_id == user_id, VideoHistory.status == VideoStatus.REJECTED)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def get_global_stats(self) -> Dict[str, Any]:
        total_users = await self.session.scalar(select(func.count(User.id)))
        total_processed_videos = await self.session.scalar(select(func.count(VideoHistory.id)))
        total_paid_amount = await self.session.scalar(select(func.sum(Payout.amount)).where(Payout.status == PayoutStatus.PAID))
        
        return {
            "total_users": total_users or 0,
            "total_processed_videos": total_processed_videos or 0,
            "total_paid_amount": total_paid_amount or 0.0,
        }
    
    async def get_admin_stats(self, admin_tg_id: int) -> Dict[str, Any]:
        videos_processed_query = select(func.count(VideoHistory.id)).where(VideoHistory.admin_tg_id == admin_tg_id)
        payouts_confirmed_query = select(func.count(Payout.id)).where(
            Payout.admin_tg_id == admin_tg_id,
            Payout.status == PayoutStatus.PAID
        )

        videos_processed = await self.session.scalar(videos_processed_query)
        payouts_confirmed = await self.session.scalar(payouts_confirmed_query)
        
        return {
            "videos_processed": videos_processed or 0,
            "payouts_confirmed": payouts_confirmed or 0,
        }
    
    async def has_pending_payout(self, user_id: int) -> bool:
        query = select(Payout.id).where(Payout.user_id == user_id, Payout.status == PayoutStatus.PENDING).limit(1)
        result = await self.session.execute(query)
        return result.scalar_one_or_none() is not None

    # --- LOGGING METHODS (НОВЫЕ) ---
    
    async def log_action(self, actor_tg_id: int, action: str, details: str = None, actor_username: str = None) -> None:
        """Записывает действие в лог."""
        log_entry = ActionLog(
            actor_tg_id=actor_tg_id,
            actor_username=actor_username,
            action=action,
            details=details
        )
        self.session.add(log_entry)
        # Обычно коммит делается в хендлере

    async def get_all_logs(self) -> list[ActionLog]:
        """Возвращает все логи, отсортированные по новизне."""
        query = select(ActionLog).order_by(desc(ActionLog.created_at))
        result = await self.session.execute(query)
        return result.scalars().all()