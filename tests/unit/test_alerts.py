import datetime as dt

from google.transit import gtfs_realtime_pb2

from app.gtfs.realtime import parse_service_alerts

NOW = dt.datetime(2026, 9, 16, 12, 0, tzinfo=dt.UTC)


# Build an alerts feed by hand, so parsing is tested without touching any agency endpoint. Each
# entry in `alerts` describes one alert loosely, the way the different agencies really publish them.
def build_feed(alerts: list[dict]) -> gtfs_realtime_pb2.FeedMessage:
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    for spec in alerts:
        entity = message.entity.add()
        entity.id = spec["id"]
        alert = entity.alert
        if "cause" in spec:
            alert.cause = spec["cause"]
        if "effect" in spec:
            alert.effect = spec["effect"]
        for start, end in spec.get("periods", []):
            period = alert.active_period.add()
            if start is not None:
                period.start = int(start.timestamp())
            if end is not None:
                period.end = int(end.timestamp())
        for language, text in spec.get("header", []):
            translation = alert.header_text.translation.add()
            translation.language = language
            translation.text = text
        for route_id in spec.get("routes", []):
            alert.informed_entity.add().route_id = route_id
    return message


# An ordinary alert is read whole: its cause and effect become enum names, its period keeps both
# ends, and the routes it names are kept in order.
def test_parses_cause_effect_period_and_routes() -> None:
    feed = build_feed(
        [
            {
                "id": "a1",
                "cause": gtfs_realtime_pb2.Alert.ACCIDENT,
                "effect": gtfs_realtime_pb2.Alert.SIGNIFICANT_DELAYS,
                "periods": [(NOW, NOW + dt.timedelta(hours=2))],
                "header": [("en", "Crash on Main Street")],
                "routes": ["10", "13"],
            }
        ]
    )
    alert = parse_service_alerts(feed)[0]
    assert (alert.alert_id, alert.cause, alert.effect) == ("a1", "ACCIDENT", "SIGNIFICANT_DELAYS")
    assert alert.header == "Crash on Main Street"
    assert alert.route_ids == ("10", "13")
    assert alert.periods[0].starts_at == NOW
    assert alert.periods[0].ends_at == NOW + dt.timedelta(hours=2)


# English wins when an agency publishes the same alert in several languages (the MBTA publishes
# eight), so the site never shows a reader text in a language it did not ask for.
def test_prefers_english_translation() -> None:
    feed = build_feed(
        [{"id": "a2", "header": [("es-419", "Retraso"), ("en", "Delay"), ("fr-FR", "Retard")]}]
    )
    assert parse_service_alerts(feed)[0].header == "Delay"


# Most agencies leave the language blank. That text is used when there is no English translation.
def test_falls_back_to_untagged_text() -> None:
    feed = build_feed([{"id": "a3", "header": [("", "Detour in effect")]}])
    assert parse_service_alerts(feed)[0].header == "Detour in effect"


# An alert with no active period at all (Torrance publishes one) becomes a single open-ended period,
# so "active now" is one rule for every alert instead of a special case.
def test_alert_without_period_becomes_open_ended() -> None:
    feed = build_feed([{"id": "a4", "header": [("en", "Masks encouraged")]}])
    alert = parse_service_alerts(feed)[0]
    assert len(alert.periods) == 1
    assert (alert.periods[0].starts_at, alert.periods[0].ends_at) == (None, None)


# A period with only a start means "until further notice", and one with only an end means it has
# been in force since before the feed said anything.
def test_half_open_periods_keep_their_missing_end() -> None:
    feed = build_feed([{"id": "a5", "periods": [(NOW, None), (None, NOW)]}])
    alert = parse_service_alerts(feed)[0]
    assert (alert.periods[0].starts_at, alert.periods[0].ends_at) == (NOW, None)
    assert (alert.periods[1].starts_at, alert.periods[1].ends_at) == (None, NOW)


# An alert naming the same route twice (once per stop, as LADOT does) is stored once per route.
def test_duplicate_routes_are_collapsed() -> None:
    feed = build_feed([{"id": "a6", "routes": ["566", "566", "603"]}])
    assert parse_service_alerts(feed)[0].route_ids == ("566", "603")


# An entity with no id is skipped: there would be no way to recognise it again on the next poll.
def test_entity_without_id_is_skipped() -> None:
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "2.0"
    entity = message.entity.add()
    entity.id = ""
    entity.alert.header_text.translation.add().text = "No id"
    assert parse_service_alerts(message) == []
