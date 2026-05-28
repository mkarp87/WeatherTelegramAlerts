from weather_alerts.web import (
    county_chat_links_by_code,
    county_chat_links_by_label,
    normalize_telegram_chat_link,
)


def test_normalize_telegram_chat_link_accepts_common_link_forms():
    assert normalize_telegram_chat_link("https://t.me/example") == "https://t.me/example"
    assert normalize_telegram_chat_link("t.me/example") == "https://t.me/example"
    assert normalize_telegram_chat_link("@example") == "https://t.me/example"
    assert normalize_telegram_chat_link("+abc123") == "https://t.me/+abc123"
    assert normalize_telegram_chat_link("example") == "https://t.me/example"


def test_normalize_telegram_chat_link_rejects_bot_api_chat_ids():
    assert normalize_telegram_chat_link("-1000000000000") == ""
    assert normalize_telegram_chat_link("1234567890") == ""


def test_county_chat_links_are_mapped_to_dashboard_labels():
    cfg = {
        "Alerting": {
            "CountyLabels": {"NCC147": "Pitt County"},
            "CountyChatLinks": {"NCC147": "@pitt_alerts"},
        }
    }

    assert county_chat_links_by_code(cfg) == {"NCC147": "https://t.me/pitt_alerts"}
    assert county_chat_links_by_label(cfg) == {"Pitt County": "https://t.me/pitt_alerts"}
