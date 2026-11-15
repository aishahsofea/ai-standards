import json

from concierge.app import TOKEN_ENV, chat_for
from concierge.chat import StdinChat
from concierge.config import Config, load_config
from concierge.telegram import TelegramChat


def test_the_owner_id_is_read_from_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"repos": {}, "telegram_owner_id": 42}))
    assert load_config(path).telegram_owner_id == 42
    path.write_text(json.dumps({"repos": {}}))
    assert load_config(path).telegram_owner_id is None


def test_telegram_needs_both_a_token_and_an_owner():
    owned, unowned = Config({}, telegram_owner_id=42), Config({})
    assert isinstance(chat_for(owned, {TOKEN_ENV: "t"}), TelegramChat)
    assert isinstance(chat_for(owned, {}), StdinChat)
    assert isinstance(chat_for(owned, {TOKEN_ENV: ""}), StdinChat)
    assert isinstance(chat_for(unowned, {TOKEN_ENV: "t"}), StdinChat)
