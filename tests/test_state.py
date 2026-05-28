from weather_alerts.state import alert_key, load_state, save_state


def test_state_round_trip(tmp_path):
    path = tmp_path / "state.json"
    state = [{"id": "alert-1", "zone": "NCC013", "Description": "x"}]
    save_state(path, state)
    assert load_state(path) == state


def test_alert_key_uses_id_and_zone():
    assert alert_key({"id": "abc", "zone": "NCC013"}) == "abc:NCC013"
