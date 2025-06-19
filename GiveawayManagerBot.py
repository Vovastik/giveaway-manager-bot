# -*- coding: utf-8 -*-
import asyncio
import secrets
import string
import random
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# --- 1. НАЛАШТУВАННЯ ---
API_TOKEN = '7572309893:AAF0pJt6SC6vjk9f21yM69cYJQTctBEHBmU'
# Список ADMIN_IDS більше не використовується для доступу, але може бути корисний для вас,
# щоб надсилати собі сервісні повідомлення в майбутньому.
ADMIN_IDS = [2042464894]

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

# --- 2. МОДЕЛЮВАННЯ БАЗИ ДАНИХ ---
# УВАГА! Дані зникають після перезапуску. Наступний крок - перехід на SQLite.
giveaways_db = {}
participations_db = {}
finished_giveaways_db = {}

# --- 3. СТАНИ FSM ---
class GiveawayCreation(StatesGroup):
    awaiting_channel = State()
    awaiting_photo = State()
    awaiting_text = State()
    awaiting_end_date = State()
    awaiting_prize_slots = State()

class EndingGiveaway(StatesGroup):
    awaiting_custom_text = State()

# --- 4. КЛАВІАТУРА ГОЛОВНОГО МЕНЮ ---
main_creator_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Створити розіграш"), KeyboardButton(text="📋 Мої розіграші")],
        [KeyboardButton(text="🏆 Історія розіграшів")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Оберіть дію з меню..."
)

# --- 5. ФУНКЦІЇ-ПОМІЧНИКИ ---
def generate_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"

async def show_my_giveaways(user_id: int, chat_id: int):
    my_giveaways = [(g_id, g_data) for g_id, g_data in giveaways_db.items() if g_data.get("owner_id") == user_id]
    if not my_giveaways:
        await bot.send_message(chat_id=chat_id, text="У вас немає активних розіграшів.")
        return
    builder = InlineKeyboardBuilder()
    text = "<b>📌 Ваші активні розіграші:</b>\n\n"
    for i, (giveaway_id, data) in enumerate(my_giveaways, 1):
        prize_title = data.get("text", "Без назви").split('\n')[0]
        participants_count = len(participations_db.get(giveaway_id, []))
        text += f"{i}. <b>{prize_title}</b> (ID: <code>{giveaway_id}</code>)\n   - Учасників: {participants_count}\n"
        builder.button(text=f"🏁 Завершити розіграш #{i}", callback_data=f"end_giveaway:{giveaway_id}")
    builder.adjust(1)
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=builder.as_markup())

async def pick_and_announce_winners(giveaway_id: str, custom_text: str, admin_user: types.User, admin_chat: types.Chat):
    giveaway_data = giveaways_db[giveaway_id]
    participants_data = participations_db.get(giveaway_id, [])
    
    if not participants_data:
        await bot.send_message(admin_chat.id, "😔 На жаль, у цьому розіграші немає жодного учасника.")
        return

    num_winners = giveaway_data.get("prize_slots", 1)
    winners_data = random.sample(participants_data, k=min(num_winners, len(participants_data)))
    winners_ids = [w['user_id'] for w in winners_data]
    
    winner_mentions = []
    for winner in winners_data:
        if winner['username']:
            winner_mentions.append(f"@{winner['username']}")
        else:
            winner_mentions.append(f'<a href="tg://user?id={winner["user_id"]}">{winner["first_name"]}</a>')

    prize_title = giveaway_data.get("text", "Наш розіграш").splitlines()[0]
    results_text = (
        f"🎉 **Розіграш завершено!** 🎉\n\n"
        f"<b>Приз:</b> {prize_title}\n\n"
        f"🏆 **Наші переможці:**\n" + "\n".join(winner_mentions) +
        (f"\n\n<b>Важливо:</b> {custom_text}" if custom_text else "") +
        "\n\nВітаємо!"
    )
    
    try:
        await bot.send_message(chat_id=giveaway_data['channel_id'], text=results_text)
        reroll_builder = InlineKeyboardBuilder()
        reroll_builder.button(text="🔄 Перевибрати переможця", callback_data=f"reroll_winner:{giveaway_id}")
        await bot.send_message(chat_id=admin_chat.id, text="✅ Переможців успішно визначено та оголошено в каналі!", reply_markup=reroll_builder.as_markup())
    except Exception as e:
        await bot.send_message(admin_chat.id, f"❌ Не вдалося надіслати результати в канал. Помилка: {e}")

    finished_giveaways_db[giveaway_id] = giveaways_db.pop(giveaway_id)
    finished_giveaways_db[giveaway_id]['winners'] = winners_ids
    await show_my_giveaways(user_id=admin_user.id, chat_id=admin_chat.id)

# --- 6. ОБРОБНИКИ ОСНОВНИХ КОМАНД ---
@dp.message(CommandStart(deep_link=True))
async def handle_start_with_giveaway(message: types.Message, command: CommandObject):
    giveaway_id = command.args
    if giveaway_id not in giveaways_db:
        await message.answer("❌ На жаль, цей розіграш не знайдено.")
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так, хочу взяти участь!", callback_data=f"join_giveaway:{giveaway_id}")
    await message.answer("👋 Вітаю! Щоб підтвердити участь, натисніть кнопку.", reply_markup=builder.as_markup())

@dp.message(Command("start"))
async def handle_start_with_role_choice(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Я Учасник", callback_data="role:participant")
    builder.button(text="🎙️ Я Стрімер", callback_data="role:streamer")
    builder.adjust(1)
    await message.answer("👋 **Вітаю!**\n\nОберіть вашу роль:", reply_markup=builder.as_markup())

# --- 7. ОБРОБНИКИ ІНЛАЙН-КНОПОК (CALLBACK QUERY) ---
@dp.callback_query(F.data.startswith("join_giveaway:"))
async def process_giveaway_join(callback: types.CallbackQuery):
    user = callback.from_user
    giveaway_id = callback.data.split(":")[1]
    if giveaway_id not in giveaways_db:
        await callback.message.edit_text("❌ На жаль, розіграш вже неактивний.")
        await callback.answer()
        return
    if any(p['user_id'] == user.id for p in participations_db.get(giveaway_id, [])):
        await callback.answer("👍 Ви вже берете участь!", show_alert=True)
        return
    new_ticket_id = generate_id("t")
    timestamp = datetime.now()
    if giveaway_id not in participations_db:
        participations_db[giveaway_id] = []
    participations_db[giveaway_id].append({'user_id': user.id, 'username': user.username, 'first_name': user.first_name, 'ticket_id': new_ticket_id, 'timestamp': timestamp})
    await callback.message.delete()
    await bot.send_message(chat_id=user.id, text=f"✅ **Ви зареєстровані!**\n\n<b>ВАШ КВИТОК</b>\n🎫 Номер: <code>{new_ticket_id}</code>")
    current_giveaway = giveaways_db[giveaway_id]
    new_count = len(participations_db[giveaway_id])
    bot_info = await bot.get_me()
    button_link = f"https://t.me/{bot_info.username}?start={giveaway_id}"
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Взяти участь", url=button_link)
    new_caption = (f"{current_giveaway['text']}\n\nУчасників: {new_count}\nПризових місць: {current_giveaway['prize_slots']}\nДата розіграшу: {current_giveaway['end_date']}")
    try:
        await bot.edit_message_caption(chat_id=current_giveaway['channel_id'], message_id=current_giveaway['announcement_message_id'], caption=new_caption, reply_markup=builder.as_markup())
    except Exception as e:
        print(f"ПОМИЛКА ОНОВЛЕННЯ ЛІЧИЛЬНИКА: {e}")
    await callback.answer()

@dp.callback_query(F.data == "role:participant")
async def handle_participant_role(callback: types.CallbackQuery):
    await callback.message.edit_text("🎉 **Вітаю!**\n\nЩоб взяти участь, знайдіть пост з розіграшем та натисніть '<b>✅ Взяти участь</b>'.")
    await callback.answer()

@dp.callback_query(F.data == "role:streamer")
async def handle_streamer_role(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("Вітаю в панелі творця! Оберіть дію за допомогою кнопок головного меню.", reply_markup=main_creator_menu)
    await callback.answer()

@dp.callback_query(F.data.startswith("end_giveaway:"))
async def start_end_giveaway(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    giveaway_id = callback.data.split(":")[1]
    if giveaway_id not in giveaways_db or giveaways_db[giveaway_id]["owner_id"] != user_id:
        await callback.answer("❌ Помилка: це не ваш розіграш.", show_alert=True)
        return
    await state.update_data(giveaway_id_to_end=giveaway_id)
    await state.set_state(EndingGiveaway.awaiting_custom_text)
    builder = InlineKeyboardBuilder()
    builder.button(text="➡️ Пропустити", callback_data=f"skip_text:{giveaway_id}")
    await callback.message.edit_text(
        "✍️ **Останній крок: Додатковий текст**\n\nНапишіть повідомлення для переможців (напр., `Переможцю звернутися до @admin`).\n\nАбо просто натисніть кнопку 'Пропустити'.",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("skip_text:"))
async def skip_custom_text_handler(callback: types.CallbackQuery, state: FSMContext):
    giveaway_id = callback.data.split(":")[1]
    await callback.message.delete()
    await pick_and_announce_winners(giveaway_id=giveaway_id, custom_text="", admin_user=callback.from_user, admin_chat=callback.message.chat)
    await callback.answer()

@dp.callback_query(F.data.startswith("reroll_winner:"))
async def reroll_winner_handler(callback: types.CallbackQuery):
    # ... (код перевибору переможця)
    pass

# --- 8. ОБРОБНИКИ КНОПОК ГОЛОВНОГО МЕНЮ ---
@dp.message(F.text == "➕ Створити розіграш")
async def handle_create_giveaway_button(message: types.Message, state: FSMContext):
    await state.set_state(GiveawayCreation.awaiting_channel)
    await message.answer("Розпочинаємо! Надішліть ID або @username каналу.", reply_markup=types.ReplyKeyboardRemove())

@dp.message(F.text == "📋 Мої розіграші")
async def handle_my_giveaways_button(message: types.Message):
    await show_my_giveaways(user_id=message.from_user.id, chat_id=message.chat.id)
    
@dp.message(F.text == "🏆 Історія розіграшів")
async def handle_history_giveaways_button(message: types.Message):
    user_id = message.from_user.id
    my_finished_giveaways = [(g_id, g_data) for g_id, g_data in finished_giveaways_db.items() if g_data.get("owner_id") == user_id]
    if not my_finished_giveaways:
        await message.answer("У вас ще немає завершених розіграшів.")
        return
    response_text = "<b>🏆 Ваша історія розіграшів:</b>\n\n"
    for i, (giveaway_id, data) in enumerate(my_finished_giveaways, 1):
        prize_title = data.get("text", "Без назви").split('\n')[0]
        winner_ids = data.get("winners", [])
        winner_mentions = []
        for winner_id in winner_ids:
            participant_data = next((p for p in participations_db.get(giveaway_id, []) if p['user_id'] == winner_id), None)
            if participant_data:
                if participant_data['username']:
                    winner_mentions.append(f"@{participant_data['username']}")
                else:
                    winner_mentions.append(f'<a href="tg://user?id={participant_data["user_id"]}">{participant_data["first_name"]}</a>')
            else:
                winner_mentions.append(f"ID: {winner_id}")
        response_text += f"{i}. <b>{prize_title}</b>\n   - Переможці: {', '.join(winner_mentions)}\n\n"
    await message.answer(response_text)

# --- 9. ОБРОБНИКИ FSM ---
@dp.message(GiveawayCreation.awaiting_channel)
async def process_channel(message: types.Message, state: FSMContext):
    # ... (код для FSM створення розіграшу)
    pass
# ... (всі інші обробники FSM тут)

@dp.message(EndingGiveaway.awaiting_custom_text, F.text)
async def process_custom_text_and_pick_winner(message: types.Message, state: FSMContext):
    data = await state.get_data()
    giveaway_id = data.get("giveaway_id_to_end")
    await state.clear()
    await message.delete()
    custom_text = message.text
    await pick_and_announce_winners(giveaway_id=giveaway_id, custom_text=custom_text, admin_user=message.from_user, admin_chat=message.chat)

# --- 10. ЗАПУСК БОТА ---
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    print("Запускаємо GiveawayManagerBot...")
    asyncio.run(main())