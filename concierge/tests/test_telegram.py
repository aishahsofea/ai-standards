import io
import json
import traceback
import urllib.error

import pytest

from concierge.chat import Event
from concierge.notifier import Choice
from concierge.telegram import MAX_VOICE_BYTES, TelegramChat, TelegramError, bot_download, bot_http

OWNER = 42
TOKEN = "123456:SECRET-token"


def message(text="hi", *, update_id=1, user=OWNER, chat="private", reply_to=None, **extra):
    body = {"message_id": 100 + update_id, "from": {"id": user}, "chat": {"id": user, "type": chat}, "text": text, **extra}
    if reply_to:
        body["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": update_id, "message": body}


def click(data="approve", *, update_id=1, user=OWNER, on=9, chat="private"):
    query = {"id": f"q{update_id}", "from": {"id": user}, "data": data, "message": {"message_id": on, "chat": {"id": user, "type": chat}}}
    return {"update_id": update_id, "callback_query": query}


class FakeHttp:
    def __init__(self, *batches):
        self.batches = list(batches)
        self.calls = []
        self.failures = {}

    def __call__(self, method, payload, timeout):
        self.calls.append((method, payload, timeout))
        failure = self.failures.get(method)
        if isinstance(failure, str):
            return {"ok": False, "description": failure}
        if failure:
            raise failure
        if method == "getUpdates":
            return {"ok": True, "result": self.batches.pop(0) if self.batches else []}
        results = {"sendMessage": {"message_id": 77}, "getFile": {"file_path": "voice/file_1.oga"}}
        return {"ok": True, "result": results.get(method, True)}

    def sent(self, method):
        return [payload for name, payload, _ in self.calls if name == method]


class FakeDownload:
    def __init__(self, audio=b"ogg"):
        self.audio, self.calls, self.failure = audio, [], None

    def __call__(self, file_path, max_bytes):
        self.calls.append((file_path, max_bytes))
        if self.failure:
            raise self.failure
        return self.audio


def chat_with(*batches, download=None):
    http, naps, logs = FakeHttp(*batches), [], []
    return TelegramChat(OWNER, http, naps.append, logs.append, download), http, naps, logs


def voice(*, file_id="f1", size=2_000, update_id=1, user=OWNER, chat="private", reply_to=None):
    update = message(update_id=update_id, user=user, chat=chat, reply_to=reply_to)
    del update["message"]["text"]
    update["message"]["voice"] = {"file_id": file_id, "file_size": size, "duration": 3}
    return update


def test_owner_text_becomes_a_text_event():
    chat, *_ = chat_with([message("make it a modal")])
    assert chat.poll(0) == [Event("text", text="make it a modal")]


def test_a_reply_carries_the_replied_to_message_id():
    chat, *_ = chat_with([message("ok", reply_to=5)])
    assert chat.poll(0) == [Event("text", text="ok", message_id="5")]


def test_a_button_click_carries_its_message_and_is_answered():
    chat, http, *_ = chat_with([click("allow:1", on=9)])
    assert chat.poll(0) == [Event("button", data="allow:1", message_id="9")]
    assert http.sent("answerCallbackQuery") == [{"callback_query_id": "q1"}]


def test_a_failed_answer_still_delivers_the_click():
    chat, http, *_ = chat_with([click()])
    http.failures["answerCallbackQuery"] = TelegramError("answerCallbackQuery: HTTP 400")
    assert chat.poll(0) == [Event("button", data="approve", message_id="9")]


@pytest.mark.parametrize(
    "update",
    [
        message(user=7),
        message(chat="group"),
        message(chat="supergroup"),
        message(chat="channel"),
        {"update_id": 1, "channel_post": {"message_id": 1, "chat": {"id": OWNER, "type": "channel"}, "text": "hi"}},
        {"update_id": 1, "edited_message": message()["message"]},
        {"update_id": 1, "message": {"message_id": 1, "from": {"id": OWNER}, "chat": {"id": OWNER, "type": "private"}, "voice": {}}},
        {"update_id": 1, "message": {"message_id": 1, "chat": {"id": OWNER, "type": "private"}, "text": "no sender"}},
        click(user=7),
        click(chat="group"),
    ],
)
def test_everything_but_the_owners_private_text_and_clicks_is_ignored(update):
    chat, http, *_ = chat_with([update])
    assert chat.poll(0) == []
    assert http.sent("answerCallbackQuery") == []


def test_the_offset_moves_past_every_update_including_ignored_ones():
    chat, http, *_ = chat_with([message(update_id=5, user=7), message("hi", update_id=6)], [])
    chat.poll(0)
    chat.poll(0)
    assert [payload["offset"] for payload in http.sent("getUpdates")] == [0, 7]


def test_long_poll_timeout_is_passed_and_the_http_timeout_outlasts_it():
    chat, http, *_ = chat_with()
    chat.poll(25)
    _, payload, timeout = http.calls[0]
    assert payload["timeout"] == 25 and payload["allowed_updates"] == ["message", "callback_query"] and timeout > 25


@pytest.mark.parametrize("failure", [TelegramError("getUpdates: HTTP 409"), "Unauthorized"])
def test_an_api_failure_returns_nothing_and_backs_off(failure):
    chat, http, naps, logs = chat_with()
    http.failures["getUpdates"] = failure
    assert chat.poll(0) == []
    assert len(naps) == 1 and naps[0] > 0 and len(logs) == 1


def test_send_posts_plain_text_with_one_button_per_row_and_returns_the_message_id():
    chat, http, *_ = chat_with()
    assert chat.send("Plan ready", (Choice("Approve", "approve"), Choice("Allow x", "allow:0"))) == "77"
    assert http.sent("sendMessage") == [
        {
            "chat_id": OWNER,
            "text": "Plan ready",
            "reply_markup": {"inline_keyboard": [[{"text": "Approve", "callback_data": "approve"}], [{"text": "Allow x", "callback_data": "allow:0"}]]},
        }
    ]


def test_send_without_choices_has_no_keyboard():
    chat, http, *_ = chat_with()
    chat.send("Done")
    assert "reply_markup" not in http.sent("sendMessage")[0]


def test_send_stays_under_telegrams_limit():
    chat, http, *_ = chat_with()
    chat.send("x" * 10_000)
    assert len(http.sent("sendMessage")[0]["text"]) < 4096


def test_callback_data_over_64_bytes_is_refused():
    chat, http, *_ = chat_with()
    with pytest.raises(ValueError):
        chat.send("x", (Choice("Too long", "é" * 33),))
    assert http.sent("sendMessage") == []


def test_send_errors_are_raised_as_telegram_errors():
    chat, http, *_ = chat_with()
    http.failures["sendMessage"] = TelegramError("sendMessage: HTTP 400")
    with pytest.raises(TelegramError):
        chat.send("x")


class Opener:
    def __init__(self, body=b'{"ok": true, "result": []}', error=None):
        self.body, self.error, self.requests = body, error, []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        return io.BytesIO(self.body)


def test_bot_http_posts_json_to_the_method_url():
    opener = Opener()
    assert bot_http(TOKEN, opener)("getUpdates", {"offset": 3}, 30) == {"ok": True, "result": []}
    request, timeout = opener.requests[0]
    assert request.full_url == f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    assert json.loads(request.data) == {"offset": 3} and request.get_header("Content-type") == "application/json" and timeout == 30


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError(f"https://api.telegram.org/bot{TOKEN}/getUpdates", 401, "Unauthorized", {}, None),
        urllib.error.URLError(f"cannot reach https://api.telegram.org/bot{TOKEN}/getUpdates"),
        TimeoutError(f"timed out: {TOKEN}"),
        OSError(f"reset: {TOKEN}"),
    ],
)
def test_transport_errors_never_carry_the_token(error):
    with pytest.raises(TelegramError) as raised:
        bot_http(TOKEN, Opener(error=error))("getUpdates", {}, 1)
    assert TOKEN not in "".join(traceback.format_exception(raised.value)) and TOKEN not in repr(raised.value)


def test_a_non_json_body_is_a_telegram_error_without_the_token():
    with pytest.raises(TelegramError) as raised:
        bot_http(TOKEN, Opener(body=f"<html>{TOKEN}</html>".encode()))("getUpdates", {}, 1)
    assert TOKEN not in "".join(traceback.format_exception(raised.value))



def test_a_silent_message_does_not_notify():
    chat, http, *_ = chat_with()
    chat.send("plan posted", silent=True)
    assert http.sent("sendMessage") == [{"chat_id": OWNER, "text": "plan posted", "disable_notification": True}]


def test_an_owner_voice_note_is_fetched_with_get_file_and_returned_as_audio():
    download = FakeDownload(b"opus-bytes")
    chat, http, *_ = chat_with([voice()], download=download)
    assert chat.poll(0) == [Event("voice", audio=b"opus-bytes")]
    assert http.sent("getFile") == [{"file_id": "f1"}]
    assert download.calls == [("voice/file_1.oga", MAX_VOICE_BYTES)]


def test_a_voice_reply_carries_the_replied_to_message_id():
    chat, *_ = chat_with([voice(reply_to=5)], download=FakeDownload())
    assert chat.poll(0)[0].message_id == "5"


@pytest.mark.parametrize("update", [voice(user=7), voice(chat="group"), voice(chat="channel")])
def test_voice_from_anyone_else_or_outside_a_private_chat_is_never_fetched(update):
    download = FakeDownload()
    chat, http, *_ = chat_with([update], download=download)
    assert chat.poll(0) == [] and http.sent("getFile") == [] and download.calls == []


def test_voice_is_ignored_when_no_download_is_configured():
    chat, http, *_ = chat_with([voice()])
    assert chat.poll(0) == [] and http.sent("getFile") == []


def test_a_voice_note_over_the_cap_is_not_fetched():
    download = FakeDownload()
    chat, http, *_ = chat_with([voice(size=MAX_VOICE_BYTES + 1)], download=download)
    [event] = chat.poll(0)
    assert event.kind == "voice" and event.audio == b"" and "too large" in event.text
    assert http.sent("getFile") == [] and download.calls == []


@pytest.mark.parametrize("where", ["getFile", "download"])
def test_a_failed_fetch_becomes_a_voice_event_with_a_reason(where):
    download = FakeDownload()
    chat, http, *_ = chat_with([voice()], download=download)
    failure = TelegramError(f"{where}: HTTP 500")
    if where == "getFile":
        http.failures["getFile"] = failure
    else:
        download.failure = failure
    assert chat.poll(0) == [Event("voice", text=f"{where}: HTTP 500")]


def test_bot_download_reads_the_file_url_and_stops_at_the_cap():
    opener = Opener(body=b"x" * 11)
    assert bot_download(TOKEN, opener)("voice/file_1.oga", 20) == b"x" * 11
    request, _ = opener.requests[0]
    assert request.full_url == f"https://api.telegram.org/file/bot{TOKEN}/voice/file_1.oga"
    with pytest.raises(TelegramError, match="too large"):
        bot_download(TOKEN, opener)("voice/file_1.oga", 10)


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError(f"https://api.telegram.org/file/bot{TOKEN}/voice/f.oga", 404, "Not Found", {}, None),
        urllib.error.URLError(f"cannot reach https://api.telegram.org/file/bot{TOKEN}/voice/f.oga"),
        TimeoutError(f"timed out: {TOKEN}"),
    ],
)
def test_download_errors_never_carry_the_token(error):
    with pytest.raises(TelegramError) as raised:
        bot_download(TOKEN, Opener(error=error))("voice/f.oga", 10)
    assert TOKEN not in "".join(traceback.format_exception(raised.value)) and TOKEN not in repr(raised.value)
