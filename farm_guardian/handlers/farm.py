from telegram import Update
from telegram.ext import ContextTypes

from app_context import AppContext, safe_display
from controller import build_plan_from_text, format_plan_preview, ControllerError
from pending_store import set_plan, cleanup


async def _edit_status(msg, text: str):
    await msg.edit_text(safe_display(text), disable_web_page_preview=True)


async def handle_farm_request(update: Update, prompt: str, ctx: AppContext):
    status_msg = await update.message.reply_text("⏳ Дух вникает...")

    try:
        ttl = int(ctx.cfg.get("PENDING_TTL_SECONDS", "900") or "900")
        cleanup(ttl_seconds=ttl)

        data = build_plan_from_text(prompt)
        chat_id = update.effective_chat.id
        set_plan(chat_id, data)

        preview = format_plan_preview(data) + "\n\nПодтвердить: /yes\nОтменить: /no"
        await _edit_status(status_msg, preview)

    except ControllerError as e:
        ctx.logger.exception("Handled error")
        await _edit_status(status_msg, f"❌ Ошибка: {e}")
    except Exception as e:
        ctx.logger.exception("Unexpected error")
        await _edit_status(status_msg, f"❌ Ошибка: {e}")


async def note(update: Update, context: ContextTypes.DEFAULT_TYPE, ctx: AppContext):
    if not context.args:
        await update.message.reply_text("Формат: /note текст", disable_web_page_preview=True)
        return
    await handle_farm_request(update, " ".join(context.args), ctx)


async def observe(update: Update, context: ContextTypes.DEFAULT_TYPE, ctx: AppContext):
    if len(context.args) < 2:
        await update.message.reply_text("Формат: /observe Имя текст", disable_web_page_preview=True)
        return
    animal = context.args[0]
    text = " ".join(context.args[1:])
    await handle_farm_request(update, f"{animal}: {text}", ctx)
