# bot/db/repository.py

from typing import Dict, Any
from sqlalchemy import select, update, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import User, Video, VideoHistory, VideoStatus, Payout, PayoutStatus


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

    # --- Методы для работы с видео (Video) ---

    async def add_video_to_queue(self, user_id: int, link: str) -> Video:
        new_video = Video(user_id=user_id, link=link)
        self.session.add(new_video)
        return new_video

    async def get_oldest_video_from_queue(self) -> Video | None:
        query = select(Video).options(selectinload(Video.user)).order_by(Video.created_at.asc()).limit(1)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
    
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

    # --- МЕТОДЫ ДЛЯ СТАТИСТИКИ (БЫЛИ ПОТЕРЯНЫ, ТЕПЕРЬ ВОЗВРАЩЕНЫ) ---
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
    
    async def has_pending_payout(self, user_id: int) -> bool:
        """Проверяет, есть ли у пользователя активная заявка на вывод."""
        query = select(Payout.id).where(Payout.user_id == user_id, Payout.status == PayoutStatus.PENDING).limit(1)
        result = await self.session.execute(query)
        return result.scalar_one_or_none() is not None