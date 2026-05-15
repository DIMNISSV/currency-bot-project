import aiohttp
import json
import datetime
import logging
import asyncio

logger = logging.getLogger(__name__)


class TradernetClient:
    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://tradernet.global/api/"

    async def get_rates_range(self, pairs_max_days: dict) -> dict:
        """
        pairs_max_days: {"USD/KZT": 3, "EUR/USD": 5} (максимальное кол-во дней для пары)
        Возвращает: {"USD/KZT": {"current": 471, "history": {1: 470, 2: 780, 3: 470}}}
        """
        if not pairs_max_days:
            return {}

        queries = {}
        today = datetime.datetime.now()

        # Собираем уникальные запросы: (базовая валюта, сдвиг_в_днях) -> {целевые валюты}
        for pair, max_days in pairs_max_days.items():
            if "/" not in pair:
                continue
            base, target = pair.upper().split("/")

            for d in range(0, max_days + 1):
                queries.setdefault((base, d), set()).add(target)

        result = {pair: {"current": None, "history": {}} for pair in pairs_max_days}

        async with aiohttp.ClientSession() as session:
            tasks = []

            # Асинхронная функция для отправки одного GET-запроса
            async def fetch(base, d, targets):
                payload = {
                    "cmd": "getCrossRatesForDate",
                    "params": {
                        "base_currency": base,
                        "currencies": list(targets)
                    }
                }
                # Если d > 0, запрашиваем историю
                if d > 0:
                    date_str = (today - datetime.timedelta(days=d)).strftime('%Y-%m-%d')
                    payload["params"]["date"] = date_str

                params = {"q": json.dumps(payload)}
                try:
                    async with session.get(self.base_url, params=params) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return base, d, list(targets), data.get("rates", {})
                except Exception as e:
                    logger.error(f"Ошибка API Tradernet: {e}")
                return base, d, list(targets), {}

            # Параллельно запускаем все необходимые запросы
            for (base, d), targets in queries.items():
                tasks.append(fetch(base, d, targets))

            responses = await asyncio.gather(*tasks)

            # Распределяем ответы по итоговому словарю
            for base, d, targets, rates in responses:
                for t in targets:
                    pair_name = f"{base}/{t}"
                    if pair_name not in result:
                        continue
                    val = rates.get(t)
                    if val is not None:
                        if d == 0:
                            result[pair_name]["current"] = float(val)
                        else:
                            result[pair_name]["history"][d] = float(val)

        return result
