import asyncio
import logging
import time

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
    PreCheckoutQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import cfg, PLANS
import database as db

logging.basicConfig(level=logging.INFO)
router = Router()

DAY_SECONDS = 24 * 60 * 60


# ---------- Клавиатуры ----------

def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Купить VPN", callback_data="buy")
    kb.button(text="🔑 Мои ключи", callback_data="my_keys")
    kb.button(text="ℹ️ Помощь", callback_data="help")
    kb.adjust(1)
    return kb.as_markup()


def plans_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for plan in PLANS:
        kb.button(
            text=f"{plan.title} — {plan.price_rub}₽",
            callback_data=f"plan:{plan.code}",
        )
    kb.button(text="⬅️ Назад", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()


def payment_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if cfg.payment_provider_token:
        kb.button(text="💳 Оплатить", callback_data=f"pay:{order_id}")
    else:
        kb.button(text="✅ Я оплатил", callback_data=f"paid_manual:{order_id}")
    kb.button(text="❌ Отменить", callback_data=f"cancel:{order_id}")
    kb.adjust(1)
    return kb.as_markup()


def admin_confirm_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить оплату", callback_data=f"admin_confirm:{order_id}")
    kb.button(text="🚫 Отклонить", callback_data=f"admin_reject:{order_id}")
    kb.adjust(1)
    return kb.as_markup()


def plan_by_code(code: str):
    for p in PLANS:
        if p.code == code:
            return p
    return None


# ---------- Пользовательские команды ----------

@router.message(CommandStart())
async def cmd_start(message: Message):
    db.upsert_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "👋 Добро пожаловать в VPN-магазин!\n\n"
        "Быстрый, безопасный VPN на любой срок.\n"
        "Выберите действие в меню ниже:",
        reply_markup=main_menu_kb(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "ℹ️ Как это работает:\n"
        "1. Нажмите «Купить VPN» и выберите тариф.\n"
        "2. Оплатите удобным способом.\n"
        "3. Бот пришлёт вам конфиг/ключ VPN.\n\n"
        "Если возникли проблемы — напишите администратору.",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "back_main")
async def cb_back_main(call: CallbackQuery):
    await call.message.edit_text("Главное меню:", reply_markup=main_menu_kb())
    await call.answer()


@router.callback_query(F.data == "help")
async def cb_help(call: CallbackQuery):
    await call.message.edit_text(
        "ℹ️ Как это работает:\n"
        "1. «Купить VPN» → выбрать тариф.\n"
        "2. Оплатить.\n"
        "3. Получить конфиг VPN в этом чате.\n\n"
        "По вопросам — обратитесь к администратору.",
        reply_markup=main_menu_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "buy")
async def cb_buy(call: CallbackQuery):
    await call.message.edit_text("Выберите тариф:", reply_markup=plans_kb())
    await call.answer()


@router.callback_query(F.data == "my_keys")
async def cb_my_keys(call: CallbackQuery):
    keys = db.get_user_keys(call.from_user.id)
    if not keys:
        await call.message.edit_text(
            "У вас пока нет активных ключей.", reply_markup=main_menu_kb()
        )
        await call.answer()
        return

    text_parts = []
    for k in keys:
        expires = time.strftime("%d.%m.%Y", time.localtime(k["expires_at"]))
        active = "✅ активен" if k["expires_at"] > time.time() else "⛔ истёк"
        text_parts.append(
            f"Ключ от {time.strftime('%d.%m.%Y', time.localtime(k['issued_at']))}\n"
            f"До: {expires} ({active})\n"
            f"```\n{k['config_text']}\n```"
        )
    await call.message.edit_text(
        "\n\n".join(text_parts), reply_markup=main_menu_kb(), parse_mode="Markdown"
    )
    await call.answer()


@router.callback_query(F.data.startswith("plan:"))
async def cb_plan_selected(call: CallbackQuery):
    code = call.data.split(":", 1)[1]
    plan = plan_by_code(code)
    if not plan:
        await call.answer("Тариф не найден", show_alert=True)
        return

    order_id = db.create_order(call.from_user.id, plan.code, plan.price_rub)

    if cfg.payment_provider_token:
        text = (
            f"Тариф: {plan.title}\n"
            f"Сумма: {plan.price_rub}₽\n\n"
            f"Нажмите «Оплатить», чтобы перейти к оплате."
        )
    else:
        text = (
            f"Тариф: {plan.title}\n"
            f"Сумма: {plan.price_rub}₽\n\n"
            f"{cfg.manual_payment_info}\n\n"
            f"Номер заказа: #{order_id}"
        )

    await call.message.edit_text(text, reply_markup=payment_kb(order_id))
    await call.answer()


@router.callback_query(F.data.startswith("cancel:"))
async def cb_cancel(call: CallbackQuery):
    order_id = int(call.data.split(":", 1)[1])
    db.mark_order_cancelled(order_id)
    await call.message.edit_text("Заказ отменён.", reply_markup=main_menu_kb())
    await call.answer()


# ---------- Оплата через Telegram Payments ----------

@router.callback_query(F.data.startswith("pay:"))
async def cb_pay(call: CallbackQuery, bot: Bot):
    order_id = int(call.data.split(":", 1)[1])
    order = db.get_order(order_id)
    if not order or order["status"] != "pending":
        await call.answer("Заказ недоступен", show_alert=True)
        return

    plan = plan_by_code(order["plan_code"])
    prices = [LabeledPrice(label=plan.title, amount=plan.price_rub * 100)]  # копейки

    await bot.send_invoice(
        chat_id=call.from_user.id,
        title=f"VPN — {plan.title}",
        description=f"Подписка на VPN на {plan.days} дней",
        payload=f"order:{order_id}",
        provider_token=cfg.payment_provider_token,
        currency=cfg.currency,
        prices=prices,
        start_parameter=f"vpn-{order_id}",
    )
    await call.answer()


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_q: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(pre_checkout_q.id, ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message, bot: Bot):
    payload = message.successful_payment.invoice_payload  # "order:123"
    order_id = int(payload.split(":", 1)[1])
    order = db.get_order(order_id)
    if not order:
        return
    db.mark_order_paid(order_id)
    await deliver_vpn(bot, order_id, message.from_user.id)


# ---------- Ручная оплата (перевод + подтверждение админом) ----------

@router.callback_query(F.data.startswith("paid_manual:"))
async def cb_paid_manual(call: CallbackQuery, bot: Bot):
    order_id = int(call.data.split(":", 1)[1])
    order = db.get_order(order_id)
    if not order or order["status"] != "pending":
        await call.answer("Заказ недоступен", show_alert=True)
        return

    plan = plan_by_code(order["plan_code"])
    await call.message.edit_text(
        f"Заявка #{order_id} отправлена администратору на проверку.\n"
        f"Мы пришлём VPN-конфиг сразу после подтверждения оплаты.",
        reply_markup=main_menu_kb(),
    )
    await call.answer()

    admin_text = (
        f"🆕 Новая оплата на подтверждение\n"
        f"Заказ: #{order_id}\n"
        f"Пользователь: @{call.from_user.username or call.from_user.id} (id {call.from_user.id})\n"
        f"Тариф: {plan.title} — {plan.price_rub}₽"
    )
    for admin_id in cfg.admin_ids:
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=admin_confirm_kb(order_id))
        except Exception as e:
            logging.warning(f"Не удалось отправить сообщение админу {admin_id}: {e}")


@router.callback_query(F.data.startswith("admin_confirm:"))
async def cb_admin_confirm(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in cfg.admin_ids:
        await call.answer("Недостаточно прав", show_alert=True)
        return

    order_id = int(call.data.split(":", 1)[1])
    order = db.get_order(order_id)
    if not order or order["status"] != "pending":
        await call.answer("Заказ уже обработан", show_alert=True)
        return

    db.mark_order_paid(order_id)
    await deliver_vpn(bot, order_id, order["user_id"])
    await call.message.edit_text(call.message.text + "\n\n✅ Оплата подтверждена, ключ выдан.")
    await call.answer()


@router.callback_query(F.data.startswith("admin_reject:"))
async def cb_admin_reject(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in cfg.admin_ids:
        await call.answer("Недостаточно прав", show_alert=True)
        return

    order_id = int(call.data.split(":", 1)[1])
    db.mark_order_cancelled(order_id)
    await call.message.edit_text(call.message.text + "\n\n🚫 Заявка отклонена.")
    await call.answer()

    order = db.get_order(order_id)
    if order:
        try:
            await bot.send_message(
                order["user_id"],
                f"❌ Оплата по заказу #{order_id} не подтверждена. "
                f"Свяжитесь с администратором, если считаете это ошибкой.",
            )
        except Exception:
            pass


# ---------- Выдача VPN-ключа ----------

async def deliver_vpn(bot: Bot, order_id: int, user_id: int):
    order = db.get_order(order_id)
    if not order:
        return
    plan = plan_by_code(order["plan_code"])

    # Берём готовый конфиг из пула (добавляется командой /addkeys администратором).
    # Если пул пуст - подставляем заглушку; замените generate_config()
    # интеграцией с вашей VPN-панелью (Outline, Marzban, WireGuard и т.п.)
    config_text = db.pop_free_key() or generate_placeholder_config(order_id)

    expires_at = int(time.time()) + plan.days * DAY_SECONDS
    db.issue_key(order_id, user_id, config_text, expires_at)

    expires_str = time.strftime("%d.%m.%Y", time.localtime(expires_at))
    try:
        await bot.send_message(
            user_id,
            f"✅ Оплата подтверждена!\n\n"
            f"Ваш VPN-конфиг (действителен до {expires_str}):\n"
            f"```\n{config_text}\n```",
            parse_mode="Markdown",
        )
    except Exception as e:
        logging.error(f"Не удалось отправить конфиг пользователю {user_id}: {e}")


def generate_placeholder_config(order_id: int) -> str:
    # ЗАГЛУШКА: замените реальной генерацией ключа/конфига вашего VPN-сервиса.
    return f"vpn://demo-key-order-{order_id}-CHANGE-ME"


# ---------- Админ: пополнение пула ключей ----------

@router.message(Command("addkeys"))
async def cmd_addkeys(message: Message):
    """
    Использование: ответьте командой /addkeys на сообщение со списком конфигов
    (по одному на строку), и они будут добавлены в пул для автоматической выдачи.
    """
    if message.from_user.id not in cfg.admin_ids:
        return
    if not message.reply_to_message or not message.reply_to_message.text:
        await message.answer(
            "Ответьте этой командой на сообщение со списком конфигов (по одному на строку)."
        )
        return
    lines = [l.strip() for l in message.reply_to_message.text.splitlines() if l.strip()]
    db.add_keys_to_pool(lines)
    await message.answer(f"Добавлено конфигов в пул: {len(lines)}")


async def main():
    if not cfg.bot_token:
        raise RuntimeError("Не задан BOT_TOKEN (переменная окружения или .env)")

    db.init_db()

    bot = Bot(token=cfg.bot_token)
    dp = Dispatcher()
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
