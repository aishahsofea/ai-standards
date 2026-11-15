import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from concierge.chat import Event
from concierge.notifier import Choice, clip

API = "https://api.telegram.org"
MAX_TEXT_CHARS = 4_000
MAX_CALLBACK_BYTES = 64
MAX_VOICE_BYTES = 10_000_000
HTTP_SLACK_SECONDS = 10
BACKOFF_SECONDS = 5

Http = Callable[[str, dict, float], dict]
Download = Callable[[str, int], bytes]


class TelegramError(Exception):
    pass


def bot_http(token: str, opener=urllib.request.urlopen) -> Http:
    """The only place the token exists; errors are rebuilt from the method name and status so none can leak it."""

    def call(method: str, payload: dict, timeout: float) -> dict:
        request = urllib.request.Request(f"{API}/bot{token}/{method}", json.dumps(payload).encode(), {"Content-Type": "application/json"})
        try:
            with opener(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            reason = f"HTTP {error.code}"
        except (OSError, ValueError) as error:
            reason = type(error).__name__
        raise TelegramError(f"{method}: {reason}") from None

    return call


def bot_download(token: str, opener=urllib.request.urlopen) -> Download:
    """Fetches a file from Telegram's file URL, which contains the token, so errors are rebuilt the same way as in `bot_http`."""

    def fetch(file_path: str, max_bytes: int) -> bytes:
        try:
            with opener(urllib.request.Request(f"{API}/file/bot{token}/{file_path}"), timeout=60) as response:
                data = response.read(max_bytes + 1)
        except urllib.error.HTTPError as error:
            raise TelegramError(f"download: HTTP {error.code}") from None
        except OSError as error:
            raise TelegramError(f"download: {type(error).__name__}") from None
        if len(data) > max_bytes:
            raise TelegramError("download: file too large")
        return data

    return fetch


def log_to_stderr(line: str) -> None:
    print(line, file=sys.stderr)


class TelegramChat:
    """Bot API long polling for one owner in a private chat; every other update is dropped."""

    def __init__(
        self,
        owner_id: int,
        http: Http,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = log_to_stderr,
        download: Download | None = None,
    ) -> None:
        self.owner_id = owner_id
        self.http = http
        self.sleep = sleep
        self.log = log
        self.download = download
        self.offset = 0

    def send(self, text: str, choices: tuple[Choice, ...] = (), silent: bool = False) -> str:
        payload: dict = {"chat_id": self.owner_id, "text": clip(text, MAX_TEXT_CHARS)}
        if silent:
            payload["disable_notification"] = True
        if choices:
            if any(len(choice.data.encode()) > MAX_CALLBACK_BYTES for choice in choices):
                raise ValueError(f"callback data over {MAX_CALLBACK_BYTES} bytes")
            payload["reply_markup"] = {"inline_keyboard": [[{"text": choice.label, "callback_data": choice.data}] for choice in choices]}
        return str(self._call("sendMessage", payload, 30)["message_id"])

    def poll(self, timeout: float) -> list[Event]:
        payload = {"offset": self.offset, "timeout": int(timeout), "allowed_updates": ["message", "callback_query"]}
        try:
            updates = self._call("getUpdates", payload, timeout + HTTP_SLACK_SECONDS)
        except TelegramError as error:
            self.log(f"telegram: {error}")
            self.sleep(BACKOFF_SECONDS)
            return []
        events = []
        for update in updates:
            self.offset = max(self.offset, update["update_id"] + 1)
            if event := self._event(update):
                events.append(event)
        return events

    def _call(self, method: str, payload: dict, timeout: float):
        response = self.http(method, payload, timeout)
        if not response.get("ok"):
            raise TelegramError(f"{method}: {response.get('description', 'rejected')}")
        return response["result"]

    def _owner_private(self, sender: dict | None, chat: dict | None) -> bool:
        return (sender or {}).get("id") == self.owner_id and (chat or {}).get("type") == "private"

    def _event(self, update: dict) -> Event | None:
        if query := update.get("callback_query"):
            return self._click(query)
        body = update.get("message")
        if not body or not self._owner_private(body.get("from"), body.get("chat")):
            return None
        reply = body.get("reply_to_message")
        message_id = str(reply["message_id"]) if reply else None
        if isinstance(body.get("text"), str):
            return Event("text", text=body["text"], message_id=message_id)
        if self.download and isinstance(file_id := (body.get("voice") or {}).get("file_id"), str):
            return self._voice(file_id, body["voice"].get("file_size", 0), message_id)
        return None

    def _voice(self, file_id: str, size: int, message_id: str | None) -> Event:
        """A failed fetch is still a voice event, so the app can say why instead of the note vanishing."""
        if size > MAX_VOICE_BYTES:
            return Event("voice", text=f"that voice note is too large (the limit is {MAX_VOICE_BYTES // 1_000_000} MB)", message_id=message_id)
        try:
            path = self._call("getFile", {"file_id": file_id}, 30)["file_path"]
            return Event("voice", audio=self.download(path, MAX_VOICE_BYTES), message_id=message_id)
        except TelegramError as error:
            return Event("voice", text=str(error), message_id=message_id)

    def _click(self, query: dict) -> Event | None:
        shown = query.get("message") or {}
        if not self._owner_private(query.get("from"), shown.get("chat")):
            return None
        try:
            self._call("answerCallbackQuery", {"callback_query_id": query["id"]}, 10)
        except TelegramError as error:
            self.log(f"telegram: {error}")
        if "data" not in query or "message_id" not in shown:
            return None
        return Event("button", data=query["data"], message_id=str(shown["message_id"]))
