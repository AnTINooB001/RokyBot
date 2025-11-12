# bot/services/coingecko_service.py

from pycoingecko import CoinGeckoAPI


class CoinGeckoService:
    def __init__(self):
        self.api = CoinGeckoAPI()

    def get_ton_to_usd_rate(self) -> float:
        """
        Получает текущий курс TON к USD.
        Использует синхронную библиотеку, но для редких запросов это приемлемо.
        Для высоконагруженных систем стоит использовать aiohttp.
        """
        try:
            # Запрашиваем цену a 'the-open-network' в 'usd'
            price_data = self.api.get_price(ids='the-open-network', vs_currencies='usd')
            return price_data['the-open-network']['usd']
        except Exception as e:
            # В случае ошибки API возвращаем 0 или None и логируем ошибку
            print(f"Error getting price from CoinGecko: {e}") # TODO: Заменить на logging
            return 0.0

# Создаем один экземпляр сервиса для всего приложения
coingecko_service = CoinGeckoService()