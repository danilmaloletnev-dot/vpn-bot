import os
from dataclasses import dataclass, field

# Загружаем переменные окружения из .env, если есть python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class Plan:
    code: str
    title: str
    days: int
    price_rub: int  # цена в рублях (в копейках для Telegram Payments считаем ниже)


@dataclass
class Config:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    admin_ids: list = field(default_factory=lambda: [
        int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
    ])
    # Провайдер-токен для Telegram Payments (получить у @BotFather -> Payments)
    # Если пусто - бот работает в режиме "ручного подтверждения" (перевод + чек)
    payment_provider_token: str = os.getenv("PAYMENT_PROVIDER_TOKEN", "")
    currency: str = os.getenv("CURRENCY", "RUB")
    # Реквизиты для ручной оплаты (если провайдер-токена нет)
    manual_payment_info: str = os.getenv(
        "MANUAL_PAYMENT_INFO",
        "Карта: 0000 0000 0000 0000\nПолучатель: Иван Иванов\nПосле оплаты нажмите «Я оплатил» и пришлите чек."
    )
    db_path: str = os.getenv("DB_PATH", "vpn_bot.db")


PLANS = [
    Plan(code="p1m", title="1 месяц", days=30, price_rub=199),
    Plan(code="p3m", title="3 месяца", days=90, price_rub=499),
    Plan(code="p12m", title="12 месяцев", days=365, price_rub=1499),
]

cfg = Config()
