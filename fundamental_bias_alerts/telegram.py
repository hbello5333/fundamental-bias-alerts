from __future__ import annotations

import json
from typing import Any
from urllib import error, request

TELEGRAM_API_BASE_URL = "https://api.telegram.org"
TELEGRAM_MAX_TEXT_LENGTH = 4096

_ALLOWED_UPDATE_TYPES = (
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "my_chat_member",
)


class TelegramRequestError(RuntimeError):
    pass


class TelegramBotClient:
    def __init__(self, bot_token: str, *, api_base_url: str = TELEGRAM_API_BASE_URL) -> None:
        token = bot_token.strip()
        if not token:
            raise ValueError("Telegram bot token is required.")
        self.bot_token = token
        self.api_base_url = api_base_url.rstrip("/")

    def send_message(self, *, chat_id: str, text: str) -> dict[str, Any]:
        resolved_chat_id = str(chat_id).strip()
        if not resolved_chat_id:
            raise ValueError("Telegram chat ID is required.")

        cleaned_text = _truncate_text(text)
        if not cleaned_text:
            raise ValueError("Telegram message text cannot be empty.")

        return self._post(
            "sendMessage",
            {
                "chat_id": resolved_chat_id,
                "text": cleaned_text,
                "disable_web_page_preview": True,
            },
        )

    def get_updates(self, *, limit: int = 20, timeout_seconds: int = 0) -> list[dict[str, Any]]:
        response = self._post(
            "getUpdates",
            {
                "limit": max(1, min(limit, 100)),
                "timeout": max(0, timeout_seconds),
                "allowed_updates": list(_ALLOWED_UPDATE_TYPES),
            },
        )
        result = response.get("result", [])
        if not isinstance(result, list):
            raise TelegramRequestError("Telegram getUpdates returned an unexpected result payload.")
        return result

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.api_base_url}/bot{self.bot_token}/{method}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=30) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            description = _error_description(exc, fallback=f"HTTP {exc.code}")
            raise TelegramRequestError(f"Telegram {method} failed: {description}") from exc
        except error.URLError as exc:
            raise TelegramRequestError(f"Telegram {method} failed: {exc.reason}") from exc

        try:
            parsed = json.loads(raw_body or "{}")
        except json.JSONDecodeError as exc:
            raise TelegramRequestError(f"Telegram {method} returned invalid JSON.") from exc

        if not parsed.get("ok", False):
            description = parsed.get("description", "unknown Telegram error")
            raise TelegramRequestError(f"Telegram {method} failed: {description}")

        return parsed


def extract_recent_chats(updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chats_by_id: dict[str, dict[str, Any]] = {}

    for update in updates:
        if not isinstance(update, dict):
            continue
        chat = _chat_from_update(update)
        if not isinstance(chat, dict):
            continue

        chat_id = chat.get("id")
        if chat_id in {None, ""}:
            continue

        key = str(chat_id)
        chats_by_id[key] = {
            "chat_id": chat_id,
            "type": str(chat.get("type", "")),
            "title": str(chat.get("title", "")),
            "username": str(chat.get("username", "")),
            "display_name": _display_name(chat),
        }

    return sorted(chats_by_id.values(), key=lambda item: str(item["chat_id"]))


def _chat_from_update(update: dict[str, Any]) -> dict[str, Any] | None:
    for key in _ALLOWED_UPDATE_TYPES:
        container = update.get(key)
        if isinstance(container, dict):
            chat = container.get("chat")
            if isinstance(chat, dict):
                return chat
    return None


def _display_name(chat: dict[str, Any]) -> str:
    if chat.get("title"):
        return str(chat["title"])

    first_name = str(chat.get("first_name", "")).strip()
    last_name = str(chat.get("last_name", "")).strip()
    name = " ".join(part for part in (first_name, last_name) if part)
    if name:
        return name

    username = str(chat.get("username", "")).strip()
    if username:
        return f"@{username}"

    return str(chat.get("id", ""))


def _truncate_text(text: str) -> str:
    cleaned = text.strip()
    if len(cleaned) <= TELEGRAM_MAX_TEXT_LENGTH:
        return cleaned
    return f"{cleaned[: TELEGRAM_MAX_TEXT_LENGTH - 3]}..."


def _error_description(exc: error.HTTPError, *, fallback: str) -> str:
    try:
        raw_body = exc.read().decode("utf-8")
        parsed = json.loads(raw_body or "{}")
    except Exception:
        return fallback

    description = parsed.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()
    return fallback
