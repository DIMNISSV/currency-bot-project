import aiohttp
import json
import datetime
import logging

logger = logging.getLogger(__name__)


class TradernetClient:
    def __init__(self, api_key: str, secret_key: str):
        # Ключи оставляем для инициализации, но для данного метода они не требуются,
        # так как курсы валют — это открытые данные, доступные по GET-запросу
        self.api_key = api_key
        self.secret_key = secret_key
        # Базовый URL согласно документации для GET-запросов
        self.base_url = "https://tradernet.global/api/"

    async def get_rates_with_prev(self, pairs: list) -> dict:
        """
        На вход: ["USD/KZT", "EUR/KZT"]
        На выход: {"USD/KZT": {"current": 450.5, "prev": 448.2}, ...}
        """
        if not pairs:
            return {}

        requests_by_base = {}
        for pair in pairs:
            if "/" not in pair:
                continue
            base, target = pair.split("/")
            base, target = base.upper(), target.upper()
            if base not in requests_by_base:
                requests_by_base[base] = set()
            requests_by_base[base].add(target)

        result = {}
        # Получаем вчерашнюю дату
        yesterday_str = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')

        async with aiohttp.ClientSession() as session:
            for base, targets in requests_by_base.items():
                targets_list = list(targets)

                # Запрос 1: Текущие курсы (сегодня)
                payload_curr = {
                    "cmd": "getCrossRatesForDate",
                    "params": {
                        "base_currency": base,
                        "currencies": targets_list
                    }
                }

                # Запрос 2: Вчерашние курсы
                payload_prev = {
                    "cmd": "getCrossRatesForDate",
                    "params": {
                        "base_currency": base,
                        "currencies": targets_list,
                        "date": yesterday_str
                    }
                }

                async def fetch(payload):
                    # Отправляем GET-запрос с параметром q={json_string}
                    params = {"q": json.dumps(payload)}
                    try:
                        async with session.get(self.base_url, params=params) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                # Если от API пришла ошибка в JSON
                                if "errMsg" in data:
                                    logger.error(f"Ошибка API: {data['errMsg']} | Payload: {payload}")
                                    return {}
                                return data.get("rates", {})
                            else:
                                logger.error(f"HTTP Ошибка {resp.status} | Payload: {payload}")
                                return {}
                    except Exception as e:
                        logger.error(f"Сетевая ошибка: {e}")
                        return {}

                # Делаем асинхронные запросы
                curr_rates = await fetch(payload_curr)
                prev_rates = await fetch(payload_prev)

                for target in targets_list:
                    pair_name = f"{base}/{target}"
                    if target in curr_rates:
                        result[pair_name] = {
                            "current": float(curr_rates[target]),
                            # Если вчерашнего курса нет (выходной), страхуемся и ставим текущий
                            "prev": float(prev_rates.get(target, curr_rates[target]))
                        }

        return result
