import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv

import db

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x
}

logging.basicConfig(level=logging.INFO)
router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


class RejectStates(StatesGroup):
    waiting_reason = State()


class IdeaCallback(CallbackData, prefix="idea"):
    action: str
    idea_id: int


def idea_keyboard(idea_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить",
                    callback_data=IdeaCallback(action="approve", idea_id=idea_id).pack(),
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=IdeaCallback(action="reject", idea_id=idea_id).pack(),
                ),
            ]
        ]
    )


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет, это бот для предложения идей плагинов для канала Exereal Plugins\n\n"
        "Просто напиши мне текстом, какой плагин ты хочешь увидеть - "
        "опиши идею как можно подробнее (что должен делать плагин, "
        "какая от него польза).\n\n"
        "Команды:\n"
        "/myideas — посмотреть свои предложенные идеи\n"
        "/help — помощь"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Как это работает:\n"
        "1. Напиши идею плагина обычным сообщением\n"
        "2. Идея попадёт на рассмотрение\n"
        "3. Проверить статус своих идей - /myideas\n\n"
        "Постарайся описать идею конкретно: что плагин делает, "
        "какую проблему решает, как им пользоваться."
    )


@router.message(Command("myideas"))
async def cmd_myideas(message: Message) -> None:
    ideas = db.get_user_ideas(message.from_user.id)
    if not ideas:
        await message.answer("Ты пока не предлагал(а) ни одной идеи. Просто напиши её сюда!")
        return

    status_emoji = {"new": "🕓 на рассмотрении", "approved": "✅ одобрена", "rejected": "❌ отклонена"}
    lines = ["Твои идеи:\n"]
    for idea in ideas:
        status = status_emoji.get(idea["status"], idea["status"])
        preview = idea["text"][:80] + ("…" if len(idea["text"]) > 80 else "")
        entry = f"#{idea['id']} [{status}]\n{preview}"
        if idea["status"] == "rejected" and idea["reason"]:
            entry += f"\nПричина: {idea['reason']}"
        lines.append(entry + "\n")

    await message.answer("\n".join(lines))


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    s = db.get_stats()
    await message.answer(
        f"📊 Статистика идей\n\n"
        f"Всего: {s['total']}\n"
        f"🕓 На рассмотрении: {s['new']}\n"
        f"✅ Одобрено: {s['approved']}\n"
        f"❌ Отклонено: {s['rejected']}"
    )


@router.message(Command("pending"))
async def cmd_pending(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    ideas = db.get_ideas_by_status("new")
    if not ideas:
        await message.answer("Новых идей нет.")
        return
    for idea in ideas:
        who = f"@{idea['username']}" if idea["username"] else idea["full_name"]
        await message.answer(
            f"#{idea['id']} от {who}\n\n{idea['text']}",
            reply_markup=idea_keyboard(idea["id"]),
        )


@router.callback_query(IdeaCallback.filter(F.action == "approve"))
async def cb_idea_approve(query: CallbackQuery, callback_data: IdeaCallback, bot: Bot) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("У тебя нет прав на это действие.", show_alert=True)
        return

    idea_id = callback_data.idea_id
    idea = db.get_idea(idea_id)
    if idea is None:
        await query.answer("Идея не найдена.", show_alert=True)
        return
    if idea["status"] != "new":
        already = "одобрена ✅" if idea["status"] == "approved" else "отклонена ❌"
        await query.answer(f"Уже {already}", show_alert=True)
        return

    db.set_status(idea_id, "approved")
    who = f"@{idea['username']}" if idea["username"] else idea["full_name"]

    try:
        await query.message.edit_text(
            f"#{idea_id} от {who}\n\n{idea['text']}\n\n"
            f"✅ Одобрено (админ: {query.from_user.full_name})",
            reply_markup=None,
        )
    except TelegramBadRequest:
        pass

    await query.answer("Готово")

    try:
        await bot.send_message(
            idea["user_id"],
            f"Твоя идея #{idea_id} была одобрена ✅\n\n«{idea['text'][:200]}»",
        )
    except Exception:
        logging.warning("Не удалось уведомить пользователя %s", idea["user_id"])


@router.callback_query(IdeaCallback.filter(F.action == "reject"))
async def cb_idea_reject_start(query: CallbackQuery, callback_data: IdeaCallback, state: FSMContext) -> None:
    if not is_admin(query.from_user.id):
        await query.answer("У тебя нет прав на это действие.", show_alert=True)
        return

    idea_id = callback_data.idea_id
    idea = db.get_idea(idea_id)
    if idea is None:
        await query.answer("Идея не найдена.", show_alert=True)
        return
    if idea["status"] != "new":
        already = "одобрена ✅" if idea["status"] == "approved" else "отклонена ❌"
        await query.answer(f"Уже {already}", show_alert=True)
        return

    await state.set_state(RejectStates.waiting_reason)
    await state.update_data(
        idea_id=idea_id,
        admin_chat_id=query.message.chat.id,
        admin_message_id=query.message.message_id,
    )

    try:
        await query.message.edit_text(
            f"{query.message.text}\n\n"
            f"✍️ Напиши причину отказа следующим сообщением.\n"
            f"Чтобы отклонить без причины — отправь «-».\n"
            f"Чтобы отменить — /cancel",
            reply_markup=None,
        )
    except TelegramBadRequest:
        pass

    await query.answer()


@router.message(Command("cancel"), RejectStates.waiting_reason)
async def cancel_reject(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отмена. Идея осталась на рассмотрении.")


@router.message(RejectStates.waiting_reason)
async def process_reject_reason(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    idea_id = data["idea_id"]
    idea = db.get_idea(idea_id)
    await state.clear()

    if idea is None or idea["status"] != "new":
        await message.answer("Эта идея уже обработана — причина не сохранена.")
        return

    reason = message.text.strip() if message.text else ""
    reason = None if reason in ("-", "", "нет", "без причины") else reason

    db.set_status(idea_id, "rejected", reason=reason)
    who = f"@{idea['username']}" if idea["username"] else idea["full_name"]

    label = "❌ Отклонено (админ: " + message.from_user.full_name + ")"
    if reason:
        label += f"\nПричина: {reason}"

    try:
        await bot.edit_message_text(
            chat_id=data["admin_chat_id"],
            message_id=data["admin_message_id"],
            text=f"#{idea_id} от {who}\n\n{idea['text']}\n\n{label}",
            reply_markup=None,
        )
    except TelegramBadRequest:
        pass

    await message.answer(f"Идея #{idea_id} отклонена.")

    try:
        note = f"Твоя идея #{idea_id} была отклонена ❌\n\n«{idea['text'][:200]}»"
        if reason:
            note += f"\n\nПричина: {reason}"
        await bot.send_message(idea["user_id"], note)
    except Exception:
        logging.warning("Не удалось уведомить пользователя %s", idea["user_id"])


@router.message(F.text)
async def handle_idea(message: Message) -> None:
    text = message.text.strip()
    if len(text) < 5:
        await message.answer("Опиши идею чуть подробнее, пожалуйста.")
        return

    idea_id = db.add_idea(
        user_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
        text=text,
    )
    await message.answer(
        f"Спасибо! Идея #{idea_id} принята и отправлена на рассмотрение."
    )

    who = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                f"💡 Новая идея #{idea_id} от {who}:\n\n{text}",
                reply_markup=idea_keyboard(idea_id),
            )
        except Exception:
            logging.warning("Не удалось отправить админу %s", admin_id)


async def main() -> None:
    db.init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    logging.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())