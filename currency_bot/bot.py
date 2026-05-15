import asyncio
import datetime
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

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
storage = Storage(STORAGE_FILE)
api_client = TradernetClient(TRADERNET_API_KEY, TRADERNET_SECRET_KEY)

last_alert_prices = {}


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я бот для мониторинга валют.\n\n"
        "<b>Команды:</b>\n"
        "/add [Пара] [Порог в %] [Направление] [Дни (опц.)] — добавить правило\n"
        "/remove [Пара] [Направление (опц.)] — удалить правило\n"
        "/list — ваши отслеживания\n\n"
        "<b>Примеры:</b>\n"
        "<code>/add USD/KZT 1.5 both</code> (изменение на 1.5% за 1 день)\n"
        "<code>/add EUR/USD 4.0 up 3</code> (рост на 4% за 3 дня)"
    )


@dp.message(Command("add"))
async def cmd_add(message: types.Message):
    args = message.text.split()[1:]
    if len(args) not in (3, 4):
        await message.answer("Неверный формат. Пример: <code>/add USD/KZT 1.5 both 2</code>")
        return

    ticker = args[0].upper()
    direction = args[2].lower()

    if "/" not in ticker:
        await message.answer("Укажите пару через слэш. Например: USD/KZT")
        return

    try:
        threshold = float(args[1])
        # Если период не указан, берем 1 день
        days = int(args[3]) if len(args) == 4 else 1
    except ValueError:
        await message.answer("Порог и период должны быть числами.")
        return

    if direction not in ("up", "down", "both"):
        await message.answer("Направление должно быть up, down или both.")
        return
    if days < 1:
        await message.answer("Период должен быть не менее 1 дня.")
        return

    await storage.add_currency(message.from_user.id, ticker, threshold, direction, days)
    await message.answer(
        f"✅ Правило для <b>{ticker}</b> добавлено!\nСрабатывание: <b>{direction}</b> на {threshold}% за {days} дн.")


@dp.message(Command("remove"))
async def cmd_remove(message: types.Message):
    args = message.text.split()[1:]
    if not args:
        await message.answer("Пример: <code>/remove USD/KZT</code> или <code>/remove USD/KZT up</code>")
        return

    ticker = args[0].upper()
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

    # Собираем данные для запроса: какие тикеры и за сколько дней нужны
    pairs_days = {}
    for ticker, rules in user_data.items():
        pairs_days[ticker] = {r.get("days", 1) for r in rules.values() if isinstance(r, dict)}

    rates = await api_client.get_rates(pairs_days)

    text = "📊 <b>Ваши отслеживания:</b>\n\n"
    for ticker, rules in user_data.items():
        current_price = "<i>нет данных</i>"
        if ticker in rates and rates[ticker].get("current"):
            current_price = f"{rates[ticker]['current']}"

        text += f"🔹 <b>{ticker}</b> (Текущий курс: <b>{current_price}</b>)\n"
        for direction, rule in rules.items():
            if not isinstance(rule, dict): continue
            text += f"   └ {direction.upper()}: {rule['threshold']}% (за {rule['days']} дн.)\n"
        text += "\n"

    await message.answer(text)


async def monitor_task():
    """Фоновая задача проверки курсов"""
    await asyncio.sleep(5)
    current_day = datetime.datetime.now().day

    while True:
        try:
            # Сброс антиспама в полночь
            new_day = datetime.datetime.now().day
            if new_day != current_day:
                last_alert_prices.clear()
                current_day = new_day

            # Собираем нужные периоды со всех пользователей
            pairs_days = {}
            for uid, user_config in storage.data.items():
                for ticker, rules in user_config.items():
                    if ticker not in pairs_days:
                        pairs_days[ticker] = set()
                    for rule in rules.values():
                        if isinstance(rule, dict):
                            pairs_days[ticker].add(rule["days"])

            if not pairs_days:
                await asyncio.sleep(60)
                continue

            rates = await api_client.get_rates(pairs_days)

            for uid_str, user_config in storage.data.items():
                user_id = int(uid_str)
                if uid_str not in last_alert_prices:
                    last_alert_prices[uid_str] = {}

                for ticker, rules in user_config.items():
                    if ticker not in rates or not rates[ticker].get("current"):
                        continue

                    if ticker not in last_alert_prices[uid_str]:
                        last_alert_prices[uid_str][ticker] = {}

                    curr_price = rates[ticker]['current']
                    triggered = []

                    for direction, rule in rules.items():
                        if not isinstance(rule, dict): continue

                        threshold = rule["threshold"]
                        days = rule["days"]

                        # Историческая цена за нужный период
                        history_price = rates[ticker]['history'].get(days)
                        if not history_price:
                            continue

                        # Берем цену прошлого алерта (антиспам) либо историческую
                        baseline_price = last_alert_prices[uid_str][ticker].get(direction, history_price)
                        if baseline_price == 0:
                            continue

                        diff_pct = ((curr_price - baseline_price) / baseline_price) * 100

                        trigger = False
                        if direction == 'up' and diff_pct >= threshold:
                            trigger = True
                        elif direction == 'down' and diff_pct <= -threshold:
                            trigger = True
                        elif direction == 'both' and abs(diff_pct) >= threshold:
                            trigger = True

                        if trigger:
                            sign = "+" if diff_pct > 0 else ""
                            triggered.append(
                                f"<b>{direction.upper()}</b>: {sign}{diff_pct:.2f}% (порог {threshold}% за {days} дн.)")
                            # Сохраняем цену алерта для антиспама
                            last_alert_prices[uid_str][ticker][direction] = curr_price

                    if triggered:
                        msg = (
                                f"<b>Сработало правило по {ticker}!</b>\n\n"
                                + "\n".join(triggered) + "\n\n"
                                                         f"Текущая цена: <b>{curr_price}</b>"
                        )
                        await bot.send_message(user_id, msg)

        except Exception as e:
            logger.error(f"Ошибка в цикле мониторинга: {e}")

        await asyncio.sleep(60)
