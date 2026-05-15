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

# Память для антиспама
last_alert_prices = {}


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я бот для мониторинга валют.\n"
        "Команды:\n"
        "/add [Пара] [Порог в %] [Направление: up/down/both] — добавить валюту\n"
        "/remove [Пара] [Опционально: направление] — удалить валюту или конкретное правило\n"
        "/list — ваши отслеживания\n\n"
        "Пример 1: <code>/add USD/KZT 1.5 up</code>\n"
        "Пример 2: <code>/add USD/KZT 2.0 down</code>"
    )


@dp.message(Command("add"))
async def cmd_add(message: types.Message):
    args = message.text.split()[1:]
    if len(args) != 3:
        await message.answer("Неверный формат. Пример: <code>/add USD/KZT 1.5 both</code>")
        return

    ticker, threshold, direction = args
    ticker = ticker.upper()
    direction = direction.lower()

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
    await message.answer(
        f"Правило для {ticker} добавлено! При изменении <b>{direction}</b> на {threshold}% придет уведомление.")


@dp.message(Command("remove"))
async def cmd_remove(message: types.Message):
    args = message.text.split()[1:]
    if not args:
        await message.answer("Укажите тикер. Пример: <code>/remove USD/KZT</code> или <code>/remove USD/KZT up</code>")
        return

    ticker = args[0].upper()
    # Если указано направление, удалим только его
    direction = args[1].lower() if len(args) > 1 else None

    success = await storage.remove_currency(message.from_user.id, ticker, direction)
    if success:
        if direction:
            await message.answer(f"Правило <b>{direction}</b> для {ticker} удалено.")
        else:
            await message.answer(f"Все отслеживания для {ticker} удалены.")
    else:
        await message.answer("Такое правило не найдено.")


@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    uid_str = str(message.from_user.id)
    user_data = storage.data.get(uid_str, {})

    if not user_data:
        await message.answer("Вы ничего не отслеживаете.")
        return

    tickers = list(user_data.keys())
    rates = await api_client.get_rates_with_prev(tickers)

    text = "📊 <b>Ваши отслеживания:</b>\n\n"
    for ticker, rules in user_data.items():
        current_price = "<i>нет данных</i>"
        if ticker in rates:
            current_price = f"{rates[ticker]['current']}"

        text += f"🔹 <b>{ticker}</b> (Текущий курс: <b>{current_price}</b>)\n"
        for direction, threshold in rules.items():
            text += f"   └ {direction.upper()}: {threshold}%\n"
        text += "\n"

    await message.answer(text)


async def monitor_task():
    """Фоновая задача проверки курсов"""
    await asyncio.sleep(5)
    while True:
        try:
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

                for ticker, rules in user_config.items():
                    if ticker not in rates:
                        continue

                    curr_price = rates[ticker]['current']
                    prev_close = rates[ticker]['prev']
                    baseline_price = last_alert_prices[uid_str].get(ticker, prev_close)

                    if baseline_price == 0:
                        continue

                    diff_pct = ((curr_price - baseline_price) / baseline_price) * 100

                    # Список сработавших правил
                    triggered = []

                    for direction, threshold in rules.items():
                        if direction == 'up' and diff_pct >= threshold:
                            triggered.append(f"Рост: <b>+{diff_pct:.2f}%</b> (порог {threshold}%)")
                        elif direction == 'down' and diff_pct <= -threshold:
                            triggered.append(f"Падение: <b>{diff_pct:.2f}%</b> (порог {threshold}%)")
                        elif direction == 'both' and abs(diff_pct) >= threshold:
                            sign = "+" if diff_pct > 0 else ""
                            triggered.append(f"Изменение: <b>{sign}{diff_pct:.2f}%</b> (порог {threshold}%)")

                    if triggered:
                        msg = (
                                f"<b>Резкое изменение курса {ticker}!</b>\n\n"
                                + "\n".join(triggered) + "\n\n"
                                                         f"Текущая цена: <b>{curr_price}</b>\n"
                                                         f"Базовая цена: <b>{baseline_price}</b>"
                        )
                        await bot.send_message(user_id, msg)
                        # Обновляем базовую цену
                        last_alert_prices[uid_str][ticker] = curr_price

        except Exception as e:
            logger.error(f"Ошибка в цикле мониторинга: {e}")

        await asyncio.sleep(60)
