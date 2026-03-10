from telegram import Update
from telegram.ext import ContextTypes

from app_context import AppContext, safe_display
from controller import execute_action, ControllerError
from pending_store import get_plan, clear_plan


async def yes(update: Update, context: ContextTypes.DEFAULT_TYPE, ctx: AppContext):
    chat_id = update.effective_chat.id
    ttl = int(ctx.cfg.get("PENDING_TTL_SECONDS", "900") or "900")

    plan = get_plan(chat_id, ttl_seconds=ttl)
    if not plan:
        await update.message.reply_text(
            "Нет ожидающей записи (или протухла). Сначала /note или /observe.",
            disable_web_page_preview=True,
        )
        return

    try:
        report = execute_action(plan)
        clear_plan(chat_id)
        await update.message.reply_text(safe_display(report), disable_web_page_preview=True)
    except ControllerError as e:
        clear_plan(chat_id)
        await update.message.reply_text(f"❌ Ошибка выполнения: {e}", disable_web_page_preview=True)


async def no(update: Update, context: ContextTypes.DEFAULT_TYPE, ctx: AppContext):
    chat_id = update.effective_chat.id
    clear_plan(chat_id)
    await update.message.reply_text("ОТМЕНЕНО", disable_web_page_preview=True)
