from weather_alerts.text import modify_description, telegram_chunks


def test_modify_description_expands_mph_and_headers():
    text = modify_description("Wind gusts 60 mph. *WHAT. Severe weather", 20)
    assert "60 miles per hour" in text
    assert "*WHAT:" in text


def test_telegram_chunks_stay_below_limit():
    chunks = list(telegram_chunks("a" * 8000, limit=3900))
    assert len(chunks) == 3
    assert all(len(chunk) <= 3900 for chunk in chunks)
