import asyncio
from .bot import dp, bot, storage, monitor_task


async def main():
    await storage.load()

    # Запуск фоновой задачи
    asyncio.create_task(monitor_task())

    # Запуск поллинга бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
