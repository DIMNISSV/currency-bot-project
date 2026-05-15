import json
import aiofiles
import os


class Storage:
    def __init__(self, filename: str):
        self.filename = filename
        self.data = {}

    async def load(self):
        if os.path.exists(self.filename):
            async with aiofiles.open(self.filename, 'r', encoding='utf-8') as f:
                content = await f.read()
                try:
                    self.data = json.loads(content)
                except json.JSONDecodeError:
                    self.data = {}
        else:
            self.data = {}

    async def save(self):
        async with aiofiles.open(self.filename, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(self.data, indent=4, ensure_ascii=False))

    async def add_currency(self, user_id: int, currency: str, threshold: float, direction: str):
        uid_str = str(user_id)
        if uid_str not in self.data:
            self.data[uid_str] = {}

        # Если валюты еще нет, создаем для нее пустой словарь
        if currency not in self.data[uid_str]:
            self.data[uid_str][currency] = {}

        # Записываем порог в нужном направлении (если уже было, оно обновится)
        self.data[uid_str][currency][direction] = threshold
        await self.save()

    async def remove_currency(self, user_id: int, currency: str, direction: str = None):
        uid_str = str(user_id)
        if uid_str in self.data and currency in self.data[uid_str]:
            if direction:
                # Удаляем только конкретное направление (например, только up)
                if direction in self.data[uid_str][currency]:
                    del self.data[uid_str][currency][direction]
                    # Если после удаления направлений не осталось, удаляем всю валюту
                    if not self.data[uid_str][currency]:
                        del self.data[uid_str][currency]
                    await self.save()
                    return True
                return False
            else:
                # Удаляем валюту со всеми ее правилами
                del self.data[uid_str][currency]
                await self.save()
                return True
        return False
