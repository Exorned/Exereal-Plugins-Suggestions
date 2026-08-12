import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
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
        lines.append(f"#{idea['id']} [{status}]\n{preview}\n")

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
    lines = ["🕓 Идеи на рассмотрении:\n"]
    for idea in ideas:
        who = f"@{idea['username']}" if idea["username"] else idea["full_name"]
        lines.append(f"#{idea['id']} от {who}\n{idea['text']}\n")
    await message.answer("\n".join(lines))


async def _change_status(message: Message, status: str) -> None:
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.answer("Использование: /approve <id> или /reject <id>")
        return

    idea_id = int(parts[1].strip())
    idea = db.get_idea(idea_id)
    if idea is None:
        await message.answer(f"Идея #{idea_id} не найдена.")
        return

    db.set_status(idea_id, status)
    label = "✅ одобрена" if status == "approved" else "❌ отклонена"
    await message.answer(f"Идея #{idea_id} {label}.")

    try:
        note = "одобрена ✅" if status == "approved" else "отклонена ❌"
        await message.bot.send_message(
            idea["user_id"],
            f"Твоя идея #{idea_id} была {note}\n\n«{idea['text'][:200]}»",
        )
    except Exception:
        logging.warning("Не удалось уведомить пользователя %s", idea["user_id"])


@router.message(Command("approve"))
async def cmd_approve(message: Message) -> None:
    await _change_status(message, "approved")


@router.message(Command("reject"))
async def cmd_reject(message: Message) -> None:
    await _change_status(message, "rejected")

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

    # пересылаем всем админам
    who = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                f"💡 Новая идея #{idea_id} от {who}:\n\n{text}\n\n"
                f"/approve {idea_id} — одобрить\n"
                f"/reject {idea_id} — отклонить",
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
