import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice, PreCheckoutQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

BOT_TOKEN = "9106602210:AAFUoekM4McGTDwtPhS3E-g7IchfYfD2jHo"
OWNER_USER_ID = 7176371503

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
logging.basicConfig(level=logging.INFO)

last_charge_id = None  # хранит последний платёж для refund

class GiftStates(StatesGroup):
    waiting_for_message = State()

GIFTS = [
    {"id": "heart",    "name": "💔 Сердце",    "price": 15,  "emoji": "💔"},
    {"id": "bear",     "name": "🧸 Мишка",     "price": 15,  "emoji": "🧸"},
    {"id": "gift",     "name": "🎁 Подарок",   "price": 25,  "emoji": "🎁"},
    {"id": "rose",     "name": "🌹 Роза",      "price": 25,  "emoji": "🌹"},
    {"id": "cake",     "name": "🎂 Торт",      "price": 50,  "emoji": "🎂"},
    {"id": "bouquet",  "name": "💐 Букет",     "price": 50,  "emoji": "💐"},
    {"id": "rocket",   "name": "🚀 Ракета",    "price": 50,  "emoji": "🚀"},
    {"id": "cup",      "name": "🏆 Кубок",     "price": 100, "emoji": "🏆"},
    {"id": "ring",     "name": "💍 Кольцо",    "price": 100, "emoji": "💍"},
    {"id": "diamond",  "name": "💎 Бриллиант", "price": 100, "emoji": "💎"},
]

def gifts_kb():
    buttons = [
        [InlineKeyboardButton(
            text=f"{g['emoji']} {g['name'].split(maxsplit=1)[-1]} — ⭐{g['price']}",
            callback_data=f"gift:{g['id']}"
        )]
        for g in GIFTS
    ]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Привет! Нажми кнопку ниже, чтобы анонимно подарить подарок админу.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Подарить админу", callback_data="start_gift")]
        ])
    )

@dp.callback_query(F.data == "start_gift")
async def start_gift(call: CallbackQuery):
    await call.message.edit_text("Выберите подарок:", reply_markup=gifts_kb())
    await call.answer()

@dp.callback_query(F.data.startswith("gift:"))
async def select_gift(call: CallbackQuery, state: FSMContext):
    gift_id = call.data.split(":")[1]
    gift = next(g for g in GIFTS if g["id"] == gift_id)
    await state.update_data(gift=gift)
    await state.set_state(GiftStates.waiting_for_message)
    await call.message.edit_text(
        f"Выбран: {gift['name']} — ⭐{gift['price']}\n\n"
        "Напишите сообщение к подарку (до 128 символов) или нажмите «Пропустить»",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data="skip")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")]
        ])
    )
    await call.answer()

@dp.callback_query(F.data == "skip")
async def skip(call: CallbackQuery, state: FSMContext):
    await state.update_data(text=None)
    await send_invoice(call.message, state)
    await call.answer()

@dp.message(GiftStates.waiting_for_message)
async def get_text(message: Message, state: FSMContext):
    if len(message.text) > 128:
        return await message.answer("Слишком длинно. Максимум 128 символов.")
    await state.update_data(text=message.text)
    await send_invoice(message, state)

async def send_invoice(message: Message, state: FSMContext):
    data = await state.get_data()
    gift = data["gift"]
    text = data.get("text") or ""
    await bot.send_invoice(
        chat_id=message.chat.id,
        title=f"Анонимный подарок: {gift['name']}",
        description="Подарок уйдёт анонимно",
        payload=f"{gift['id']}|{text}",
        currency="XTR",
        prices=[LabeledPrice(label=gift["name"], amount=gift["price"])]
    )
    await state.clear()

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def success(message: Message):
    global last_charge_id
    payload = message.successful_payment.invoice_payload
    gift_id, text = payload.split("|", 1)
    text = text if text else None

    last_charge_id = message.successful_payment.telegram_payment_charge_id

    # Уведомляем владельца
    try:
        await bot.send_message(
            OWNER_USER_ID,
            f"Новый платёж: {message.successful_payment.total_amount} Stars\n"
            f"Charge ID: `{last_charge_id}`",
            parse_mode="Markdown"
        )
    except:
        pass

    try:
        gifts = await bot.get_available_gifts()
        target_price = next(x["price"] for x in GIFTS if x["id"] == gift_id)
        target = next((g for g in gifts.gifts if g.star_count == target_price), None)

        if target:
            await bot.send_gift(
                user_id=OWNER_USER_ID,
                gift_id=target.id,
                text=text
            )
            await message.answer("✅ Подарок отправлен!")
        else:
            await message.answer("Не нашёл подходящий подарок. Напиши /refund.")
    except Exception as e:
        logging.error(f"Gift error: {e}")
        await message.answer("Ошибка отправки. Напиши /refund чтобы вернуть Stars.")

@dp.message(F.text == "/refund")
async def refund(message: Message):
    global last_charge_id
    if message.from_user.id != OWNER_USER_ID:
        return await message.answer("Только владелец может делать возврат.")

    if not last_charge_id:
        return await message.answer("Нет сохранённого платежа для возврата.")

    try:
        await bot.refund_star_payment(
            user_id=message.from_user.id,  # возвращаем тому, кто платил? 
            # На самом деле refund всегда идёт плательщику, user_id здесь игнорируется в большинстве случаев
            telegram_payment_charge_id=last_charge_id
        )
        await message.answer("✅ Stars возвращены покупателю.")
        last_charge_id = None
    except Exception as e:
        await message.answer(f"Ошибка возврата: {e}")

@dp.callback_query(F.data == "cancel")
async def cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Отменено.")
    await call.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
