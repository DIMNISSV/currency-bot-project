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
        # Перешли на классический домен, как в вашей документации
        self.base_url = "https://tradernet.com/api/"

    async def get_rates_range(self, pairs_max_days: dict) -> dict:
        """
        pairs_max_days: {"USD/KZT": 3, "EUR/USD": 5}
        Возвращает: {"USD/KZT": {"current": 471, "history": {1: 470, 2: 780, 3: 470}}}
        """
        if not pairs_max_days:
            return {}

        queries = {}
        today = datetime.datetime.now()

        # Группируем запросы. Запрашиваем МИНИМУМ 5 дней истории для каждой пары,
        # чтобы 100% найти "последний актуальный" курс, если сегодня выходной
        for pair, max_days in pairs_max_days.items():
            if "/" not in pair:
                continue
            base, target = pair.upper().split("/")

            search_days = max(max_days, 5)
            for d in range(0, search_days + 1):
                queries.setdefault((base, d), set()).add(target)

        result = {pair: {"current": None, "history": {}} for pair in pairs_max_days}
        fetched_data = {pair: {} for pair in pairs_max_days}

        async with aiohttp.ClientSession() as session:
            tasks = []

            async def fetch(base, d, targets):
                # Явно передаем точную дату, чтобы биржа не путалась
                date_str = (today - datetime.timedelta(days=d)).strftime('%Y-%m-%d')
                payload = {
                    "cmd": "getCrossRatesForDate",
                    "params": {
                        "base_currency": base,
                        "currencies": list(targets),
                        "date": date_str
                    }
                }

                params = {"q": json.dumps(payload)}
                try:
                    async with session.get(self.base_url, params=params) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return base, d, list(targets), data.get("rates", {})
                except Exception as e:
                    logger.error(f"Ошибка API Tradernet: {e}")
                return base, d, list(targets), {}

            # Параллельно запрашиваем все нужные даты
            for (base, d), targets in queries.items():
                tasks.append(fetch(base, d, targets))

            responses = await asyncio.gather(*tasks)

            # Сохраняем все успешные ответы
            for base, d, targets, rates in responses:
                for t in targets:
                    pair_name = f"{base}/{t}"
                    if pair_name not in fetched_data:
                        continue
                    val = rates.get(t)
                    if val is not None:
                        fetched_data[pair_name][d] = float(val)

        # Формируем логичный итоговый ответ
        for pair, max_days in pairs_max_days.items():

            # 1. ТЕКУЩИЙ КУРС: первый найденный курс, начиная с сегодня и вглубь на 5 дней назад
            current_val = None
            for d in range(0, 6):
                if d in fetched_data[pair]:
                    current_val = fetched_data[pair][d]
                    break

            result[pair]["current"] = current_val

            # 2. ИСТОРИЯ (только для запрошенного количества дней)
            for d in range(1, max_days + 1):
                if d in fetched_data[pair]:
                    result[pair]["history"][d] = fetched_data[pair][d]
                else:
                    # Если исторический день выпал на выходной, ищем ближайший доступный более старый курс,
                    # чтобы математика скачков работала бесперебойно
                    for look_back in range(d, d + 6):
                        if look_back in fetched_data[pair]:
                            result[pair]["history"][d] = fetched_data[pair][look_back]
                            break

        return result
