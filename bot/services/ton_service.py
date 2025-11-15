# bot/services/ton_service.py

import asyncio
import logging
from pytoniq import LiteClient, WalletV3R2, WalletV4R2, WalletV5R1, ShardAccount

from bot.config import config

class TonService:
    def __init__(self, mnemonics: list[str]):
        self.mnemonics = mnemonics

    async def get_account_state(self, client: LiteClient, address: str) -> ShardAccount | None:
        try:
            state = await client.get_account_state(address=address)
            return state
        except Exception as e:
            logging.error(f"Could not get account state for {address}: {e}")
            return None

    async def send_transaction(self, to_address: str, amount_ton: float, comment: str = "") -> str | None:
        client = None
        try:
            client = LiteClient.from_mainnet_config(trust_level=2, timeout=20)
            await client.connect()
            await client.get_masterchain_info()

            wallet = await WalletV5R1.from_mnemonic(provider=client, mnemonics=self.mnemonics, network_global_id=-239)

            state = await self.get_account_state(client, wallet.address)
            balance = state.balance if state and hasattr(state, 'balance') else 0
            seqno_for_log = state.seqno if state and hasattr(state, 'seqno') else 0
            
            friendly_address = wallet.address.to_str(is_user_friendly=True, is_bounceable=True)
            logging.info(f"Using {wallet.__class__.__name__}. Wallet address: {friendly_address}. Balance: {balance / 1e9} TON. Seqno: {seqno_for_log}")

            amount_nanotons = int(amount_ton * 1e9)
            if balance < amount_nanotons:
                logging.error(f"Insufficient balance for transaction. Needed: {amount_ton}, have: {balance / 1e9}")
                await client.close()
                return None

            tx_result = await wallet.transfer(
                destination=to_address,
                amount=amount_nanotons,
                body=comment
            )
            
            await client.close()

            # --- ФИНАЛЬНОЕ ИСПРАВЛЕНИЕ ---
            # Функция больше не возвращает объект с хэшем.
            # Мы не можем получить хэш напрямую, но можем вернуть "success"
            # для индикации успешной отправки в сеть.
            # Хэш можно будет найти в обозревателе блокчейна по адресу кошелька.
            # В реальном проекте, для получения хэша, нужен более сложный мониторинг.
            logging.info(f"Transaction sent to network. Result: {tx_result}")
            return "success" # Возвращаем "success" вместо хэша
            # ---------------------------

        except Exception as e:
            logging.error(f"Transaction failed: {e}", exc_info=True)
            if client:
                try: await client.close()
                except Exception: pass
            return None

ton_service = TonService(mnemonics=config.wallet_mnemonic.get_secret_value().split())