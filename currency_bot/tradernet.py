import aiohttp
import json
import datetime
import logging

logger = logging.getLogger(__name__)


class TradernetClient:
    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://tradernet.global/api/"

    async def get_rates(self, pairs_days: dict) -> dict:
        """
        pairs_days: {"USD/KZT": {1, 2}, "EUR/USD": {1, 5}} (тикер -> множество нужных дней)
        Возвращает: {"USD/KZT": {"current": 450, "history": {1: 445, 2: 440}}}
        """
        if not pairs_days:
            return {}

        # Группируем запросы: {(base_currency, days_ago): set(target_currencies)}
        queries = {}
        for pair, days_set in pairs_days.items():
            if "/" not in pair:
                continue
            base, target = pair.split("/")
            base, target = base.upper(), target.upper()

            # Обязательно запрашиваем текущий курс (days = 0)
            queries.setdefault((base, 0), set()).add(target)
            for d in days_set:
                queries.setdefault((base, d), set()).add(target)

        result = {pair: {"current": None, "history": {}} for pair in pairs_days}
        today = datetime.datetime.now()

        async with aiohttp.ClientSession() as session:
            for (base, days), targets in queries.items():
                targets_list = list(targets)
                payload = {
                    "cmd": "getCrossRatesForDate",
                    "params": {
                        "base_currency": base,
                        "currencies": targets_list
                    }
                }

                # Если запрашиваем историю, добавляем дату
                if days > 0:
                    date_str = (today - datetime.timedelta(days=days)).strftime('%Y-%m-%d')
                    payload["params"]["date"] = date_str

                params = {"q": json.dumps(payload)}
                try:
                    async with session.get(self.base_url, params=params) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            rates = data.get("rates", {})
                            for t in targets_list:
                                pair_name = f"{base}/{t}"
                                val = rates.get(t)
                                if val is not None and pair_name in result:
                                    if days == 0:
                                        result[pair_name]["current"] = float(val)
                                    else:
                                        result[pair_name]["history"][days] = float(val)
                except Exception as e:
                    logger.error(f"Ошибка API Tradernet: {e}")

        # Защита от выходных: если исторической даты нет, страхуемся текущим курсом
        for pair, data in result.items():
            curr = data["current"]
            if curr is None:
                continue
            for d in pairs_days.get(pair, []):
                if d not in data["history"]:
                    data["history"][d] = curr

        return result
