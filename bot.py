import json
import logging
import os
import re
from datetime import datetime as dt
from pathlib import Path
from typing import Any, Dict, Optional

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from llm_client import AnythingLLMClient, LLMClientError
from controller import (
    parse_llm_json,
    execute_action,
    format_plan_preview,
    ControllerError,
)

from pending_store import get_plan, set_plan, clear_plan, cleanup


# -------------------- ЛОГИ --------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("bot")


# -------------------- PROMPT --------------------
SYSTEM_PROMPT = f"""
Strict JSON only. No prose. No markdown blocks.
Date: {dt.now().strftime('%Y-%m-%d')}

EXAMPLES:
- "Открыли сено" -> {{"action":"modify","path":"resources/feed.md","mode":"replace_block","block_id":"inventory","content":"Открыт рулон сена 300кг"}}
- "Рэй активен" -> {{"action":"modify","path":"animals/рэй.md","mode":"replace_block","block_id":"observations","content":"Активное состояние"}}
- "Купили зерно" -> {{"action":"modify","path":"resources/feed.md","mode":"replace_block","block_id":"log","content":"Закупка зерна 50кг"}}

MAP:
- Сено/Зерно/Корм -> resources/feed.md (block_id: inventory или log)
- Животные -> animals/имя.md (block_id: observations)
- Другое -> journal/{dt.now().strftime('%Y-%m-%d')}.md
""".strip()


# -------------------- CONFIG (secrets.json) --------------------
def _read_json(path: Path) -> Dict[str, Any]:
    """
    ВАЖНО: utf-8-sig съедает BOM.
    Это лечит ошибку: Unexpected UTF-8 BOM
    """
    try:
        raw = path.read_text(encoding="utf-8-sig")
        return json.loads(raw) if raw.strip() else {}
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        raise RuntimeError(f"secrets.json битый JSON: {path} | {e}")


def load_config() -> Dict[str, str]:
    """
    Приоритет:
    1) config/secrets.json
    2) переменные окружения (перекрывают secrets)
    """
    here = Path(__file__).resolve().parent
    secrets_path = here / "config" / "secrets.json"

    secrets = _read_json(secrets_path)

    def pick(key: str, default: str = "") -> str:
        env = os.environ.get(key, "").strip()
        if env:
            return env
        v = str(secrets.get(key, default) or "").strip()
        return v

    cfg = {
        "TELEGRAM_TOKEN": pick("TELEGRAM_TOKEN"),
        "ANYTHINGLLM_API_KEY": pick("ANYTHINGLLM_API_KEY"),
        "ANYTHINGLLM_BASE_URL": pick("ANYTHINGLLM_BASE_URL", "http://127.0.0.1:3001"),
        "ANYTHINGLLM_WORKSPACE": pick("ANYTHINGLLM_WORKSPACE", "moya-rabochaya-oblast"),
        "REQUEST_TIMEOUT": pick("REQUEST_TIMEOUT", "300"),
        "PENDING_TTL_SECONDS": pick("PENDING_TTL_SECONDS", "900"),  # 15 минут
        "SECRETS_PATH": str(secrets_path),
    }

    missing = [k for k in ("TELEGRAM_TOKEN", "ANYTHINGLLM_API_KEY") if not cfg[k]]
    if missing:
        raise RuntimeError(
            "Не хватает ключей: " + ", ".join(missing) + "\n"
            f"Проверь файл: {cfg['SECRETS_PATH']}\n"
            "Он должен содержать TELEGRAM_TOKEN и ANYTHINGLLM_API_KEY."
        )

    return cfg


# -------------------- Telegram anti-URL --------------------
def _safe_display(text: str) -> str:
    """
    Telegram иногда распознаёт куски как URL (feed.md, resources/...).
    Ломаем отображение, НЕ ломая реальные пути в файлах.
    """
    if not text:
        return text

    text = re.sub(r"\.md\b", "·md", text)  # feed.md -> feed·md
    text = text.replace("resources/", "resources／")
    text = text.replace("system/", "system／")
    text = text.replace("animals/", "animals／")
    text = text.replace("journal/", "journal／")
    text = text.replace("http://", "hxxp://").replace("https://", "hxxps://")
    return text


# -------------------- GLOBALS --------------------
llm: Optional[AnythingLLMClient] = None
CFG: Dict[str, str] = {}


def init_llm():
    global llm
    timeout = int(CFG.get("REQUEST_TIMEOUT", "300") or "300")

    try:
        llm = AnythingLLMClient(
            base_url=CFG["ANYTHINGLLM_BASE_URL"],
            api_key=CFG["ANYTHINGLLM_API_KEY"],
            workspace=CFG["ANYTHINGLLM_WORKSPACE"],
            timeout=timeout,
        )
    except TypeError:
        llm = AnythingLLMClient(
            base_url=CFG["ANYTHINGLLM_BASE_URL"],
            api_key=CFG["ANYTHINGLLM_API_KEY"],
            workspace=CFG["ANYTHINGLLM_WORKSPACE"],
        )

    logger.info("LLMClient: base=%s workspace=%s", CFG["ANYTHINGLLM_BASE_URL"], CFG["ANYTHINGLLM_WORKSPACE"])


async def _edit_status(msg, text: str):
    await msg.edit_text(_safe_display(text), disable_web_page_preview=True)


# -------------------- HANDLERS --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        _safe_display(
            "🐄 Дух Фермы на связи.\n\n"
            "Команды:\n"
            "• /note <текст> — запись в память (с подтверждением /yes)\n"
            "• /observe <Имя> <текст> — наблюдение по животному (с подтверждением /yes)\n\n"
            "Подтверждение:\n"
            "• /yes — выполнить предложенную запись\n"
            "• /no — отменить\n\n"
            "Примеры:\n"
            "• /note Сегодня много продуктов заваккумировали — завтра день торговли\n"
            "• /note Открыли рулон сена 300кг\n"
            "• /observe Белка Сегодня вялая, плохо ела, стояла отдельно\n\n"
            "Сервис:\n"
            "• /ping — проверка связи\n"
        ),
        disable_web_page_preview=True,
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        _safe_display(
            "✅ На связи.\n"
            f"Workspace: {CFG.get('ANYTHINGLLM_WORKSPACE')}\n"
            f"BaseURL: {CFG.get('ANYTHINGLLM_BASE_URL')}\n"
            f"Secrets: {CFG.get('SECRETS_PATH')}\n"
            f"Pending TTL: {CFG.get('PENDING_TTL_SECONDS')} sec"
        ),
        disable_web_page_preview=True,
    )


async def yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    ttl = int(CFG.get("PENDING_TTL_SECONDS", "900") or "900")

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
        await update.message.reply_text(_safe_display(report), disable_web_page_preview=True)
    except ControllerError as e:
        clear_plan(chat_id)
        await update.message.reply_text(f"❌ Ошибка выполнения: {e}", disable_web_page_preview=True)


async def no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    clear_plan(chat_id)
    await update.message.reply_text("🗑️ Отменено.", disable_web_page_preview=True)


async def handle_farm_request(update: Update, prompt: str):
    status_msg = await update.message.reply_text("⏳ Дух вникает...")

    try:
        if llm is None:
            raise RuntimeError("LLM не инициализирован (llm is None)")

        ttl = int(CFG.get("PENDING_TTL_SECONDS", "900") or "900")
        cleanup(ttl_seconds=ttl)

        full_prompt = f"{SYSTEM_PROMPT}\n\nTask: {prompt}"
        llm_answer = llm.ask(full_prompt)
        logger.info("LLM raw: %s", llm_answer)

        data = parse_llm_json(llm_answer)

        chat_id = update.effective_chat.id
        set_plan(chat_id, data)

        preview = format_plan_preview(data) + "\n\nПодтвердить: /yes\nОтменить: /no"
        await _edit_status(status_msg, preview)

    except (LLMClientError, ControllerError) as e:
        logger.exception("Handled error")
        await _edit_status(status_msg, f"❌ Ошибка: {e}")
    except Exception as e:
        logger.exception("Unexpected error")
        await _edit_status(status_msg, f"❌ Ошибка: {e}")


async def note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Формат: /note текст", disable_web_page_preview=True)
        return
    await handle_farm_request(update, " ".join(context.args))


async def observe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Формат: /observe Имя текст", disable_web_page_preview=True)
        return
    animal = context.args[0]
    text = " ".join(context.args[1:])
    await handle_farm_request(update, f"{animal}: {text}")


# -------------------- MAIN --------------------
def main():
    global CFG
    CFG = load_config()
    init_llm()

    app = ApplicationBuilder().token(CFG["TELEGRAM_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("yes", yes))
    app.add_handler(CommandHandler("no", no))
    app.add_handler(CommandHandler("note", note))
    app.add_handler(CommandHandler("observe", observe))

    logger.info("🐂 Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
