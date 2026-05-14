import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command

from .config import BOT_TOKEN, TRADERNET_API_KEY, TRADERNET_SECRET_KEY, STORAGE_FILE
from .storage import Storage
from .tradernet import TradernetClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()
storage = Storage(STORAGE_FILE)
api_client = TradernetClient(TRADERNET_API_KEY, TRADERNET_SECRET_KEY)

last_alert_prices = {}


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я бот для мониторинга валют.\n"
        "Команды:\n"
        "/add [Тикер] [Порог в %] [Направление: up/down/both] — добавить валюту\n"
        "/remove [Тикер] — удалить валюту\n"
        "/list — ваши валюты\n\n"
        "Пример: <code>/add USDKZT 1.5 both</code>"
    )


@dp.message(Command("add"))
async def cmd_add(message: types.Message):
    args = message.text.split()[1:]
    if len(args) != 3:
        await message.answer("Неверный формат. Пример: <code>/add USD/KZT 1.5 both</code>")
        return

    ticker, threshold, direction = args
    ticker = ticker.upper()

    if "/" not in ticker:
        await message.answer("Укажите пару через слэш. Например: USD/KZT")
        return

    try:
        threshold = float(threshold)
    except ValueError:
        await message.answer("Порог должен быть числом.")
        return

    if direction not in ("up", "down", "both"):
        await message.answer("Направление должно быть up, down или both.")
        return

    await storage.add_currency(message.from_user.id, ticker, threshold, direction)
    await message.answer(f"Валютная пара {ticker} добавлена! Порог: {threshold}%, Направление: {direction}")

@dp.message(Command("remove"))
async def cmd_remove(message: types.Message):
    args = message.text.split()[1:]
    if not args:
        await message.answer("Укажите тикер. Пример: /remove USDKZT")
        return

    ticker = args[0]
    success = await storage.remove_currency(message.from_user.id, ticker)
    if success:
        await message.answer(f"Валюта {ticker} удалена из отслеживания.")
    else:
        await message.answer("Валюта не найдена.")


@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    uid_str = str(message.from_user.id)
    user_data = storage.data.get(uid_str, {})

    if not user_data:
        await message.answer("Вы ничего не отслеживаете.")
        return

    tickers = list(user_data.keys())
    # Запрашиваем через новый метод!
    rates = await api_client.get_rates_with_prev(tickers)

    text = "Ваши валюты:\n"
    for ticker, params in user_data.items():
        current_price = "<i>нет данных</i>"
        if ticker in rates:
            current_price = f"{rates[ticker]['current']}"

        text += (
            f"• <b>{ticker}</b>: {params['threshold']}% ({params['direction']})\n"
            f"  Текущий курс: <b>{current_price}</b>\n\n"
        )

    await message.answer(text)

async def monitor_task():
    """Фоновая задача, которая проверяет курсы каждую минуту"""
    await asyncio.sleep(5)  # Ждем загрузки
    while True:
        try:
            # Собираем уникальные тикеры, чтобы запрашивать API 1 раз
            all_tickers = set()
            for uid, data in storage.data.items():
                for ticker in data.keys():
                    all_tickers.add(ticker)

            if not all_tickers:
                await asyncio.sleep(60)
                continue

            rates = await api_client.get_rates_with_prev(list(all_tickers))

            for uid_str, user_config in storage.data.items():
                user_id = int(uid_str)
                if uid_str not in last_alert_prices:
                    last_alert_prices[uid_str] = {}

                for ticker, params in user_config.items():
                    if ticker not in rates:
                        continue

                    curr_price = rates[ticker]['current']
                    prev_close = rates[ticker]['prev']

                    # Если уже было уведомление, сравниваем с ценой ПОСЛЕДНЕГО уведомления (антиспам)
                    # Иначе сравниваем с предыдущим закрытием
                    baseline_price = last_alert_prices[uid_str].get(ticker, prev_close)

                    if baseline_price == 0:
                        continue

                    diff_pct = ((curr_price - baseline_price) / baseline_price) * 100
                    direction = params['direction']
                    threshold = params['threshold']

                    trigger = False
                    if direction == 'up' and diff_pct >= threshold:
                        trigger = True
                    elif direction == 'down' and diff_pct <= -threshold:
                        trigger = True
                    elif direction == 'both' and abs(diff_pct) >= threshold:
                        trigger = True

                    if trigger:
                        msg = (
                            f"🚨 <b>Резкое изменение курса {ticker}!</b>\n"
                            f"Текущая цена: {curr_price}\n"
                            f"Базовая цена: {baseline_price}\n"
                            f"Изменение: {diff_pct:+.2f}%"
                        )
                        await bot.send_message(user_id, msg)
                        # Обновляем цену последнего алерта
                        last_alert_prices[uid_str][ticker] = curr_price

        except Exception as e:
            logger.error(f"Ошибка в цикле мониторинга: {e}")

        await asyncio.sleep(60)  # Интервал проверки (1 минута)
