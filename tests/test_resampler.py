"""Test cases derived from README.md.

Each test states the README statement it checks. Times are simulated; T0 is
the start of the simulation, and h.tick(t) is one run of the aggregation loop
(which main.py runs every `min_interval` seconds).
"""

import copy
import math
import os
import time
import types

import pytest

from conftest import (COUNTER, CURRENT, MAX_10S, README_CONFIG, SUM_1H, SUM_1M,
                      T0, FakeClock)


def ticks(start, end, step=10):
    """Aggregation ticks start+step, start+2*step, ... up to end (inclusive)."""
    t = start + step
    while t <= end + 1e-9:
        yield t
        t += step


# ---------------------------------------------------------------------------
# A. Message input: "Messages on MQTT need to be plain values."
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload, expected", [
    ("42", 42.0),
    ("3.5", 3.5),
    ("-1.25", -1.25),
    ("  7\n", 7.0),
    ("0", 0.0),
])
def test_A1_plain_numeric_values_are_collected(h, payload, expected):
    """A1: Plain numeric payloads are collected with their numeric value."""
    h.send(CURRENT, payload, at=T0)
    assert [v for v, _ in h.userdata["message_map"][CURRENT]] == [expected]


@pytest.mark.parametrize("payload", [
    "abc",
    '{"value": 5}',      # JSON is explicitly not supported
    "",
    "1,5",               # decimal comma
    b"\xff\xfe",         # not UTF-8
])
def test_A2_unsupported_payload_does_not_raise(h, payload):
    """A2: An unsupported payload must be ignored, not raise.

    paho 1.6 re-raises exceptions from on_message (suppress_exceptions=False),
    which ends the network thread: after one bad message the resampler would
    silently stop receiving anything.
    """
    h.send(CURRENT, payload, at=T0)


def test_A3_valid_messages_after_invalid_one_are_still_aggregated(h):
    """A3: An invalid message must not affect the aggregation of valid ones."""
    h.send(CURRENT, "5", at=T0 + 1)
    try:
        h.send(CURRENT, "not-a-number", at=T0 + 2)
    except Exception:
        pass
    h.send(CURRENT, "7", at=T0 + 3)
    for t in ticks(T0, T0 + 60):
        h.tick(t)
    assert h.values(SUM_1M) == [12.0]


@pytest.mark.parametrize("payload", ["nan", "inf", "-inf"])
def test_A4_non_finite_values_do_not_poison_aggregates(h, payload):
    """A4: 'nan'/'inf' are not meaningful plain values.

    float() accepts them; a single such message turns every sum/avg/max of
    the window into nan/inf.
    """
    h.send(CURRENT, "5", at=T0 + 1)
    try:
        h.send(CURRENT, payload, at=T0 + 2)
    except Exception:
        pass
    for t in ticks(T0, T0 + 60):
        h.tick(t)
    assert all(math.isfinite(v) for v in h.values(SUM_1M))


# ---------------------------------------------------------------------------
# B. Aggregation functions: "performs aggregations (sum, average, max)"
# ---------------------------------------------------------------------------

def _single_aggregate_config(name, interval=10):
    return {
        "min_interval": 10,
        "mqtt": {"host": "localhost", "port": 1883},
        "topics": [{"name": "in", "aggregates": [
            {"name": name, "interval": interval, "topic": "out"}]}],
    }


@pytest.mark.parametrize("name, values, expected", [
    ("sum", [1, 2, 3.5], 6.5),
    ("sum", [-4, 4], 0.0),
    ("avg", [1, 2, 6], 3.0),
    ("avg", [2.5], 2.5),
    ("max", [3, 9, 4], 9.0),
    ("max", [-7, -3, -5], -3.0),
])
def test_B1_aggregate_functions(make_harness, name, values, expected):
    """B1: sum / avg / max over all messages of one interval."""
    h = make_harness(_single_aggregate_config(name))
    for i, v in enumerate(values):
        h.send("in", str(v), at=T0 + 1 + i)
    h.tick(T0 + 10)
    assert h.values("out") == [expected]


def test_B2_published_value_is_a_plain_value(make_harness):
    """B2: Results are published as plain values (same format as input)."""
    h = make_harness(_single_aggregate_config("sum"))
    h.send("in", "2", at=T0 + 1)
    h.tick(T0 + 10)
    (_, _, payload), = h.published
    assert isinstance(payload, str)
    float(payload)


# ---------------------------------------------------------------------------
# C. Intervals: "based on the defined intervals"
# ---------------------------------------------------------------------------

def test_C1_aggregate_without_interval_uses_min_interval(h):
    """C1: README example 'max_10s' has no interval -> runs every min_interval (10 s)."""
    for i, t in enumerate(ticks(T0, T0 + 60)):
        h.send(COUNTER, str(100 + i), at=t - 5)
        h.tick(t)
    assert h.values(MAX_10S) == [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]


def test_C2_sum_1m_published_once_per_minute(h):
    """C2: A 60 s aggregate is published once per 60 s, not on every tick."""
    for t in ticks(T0, T0 + 300):
        h.send(CURRENT, "1", at=t - 5)
        h.tick(t)
    times = h.times(SUM_1M)
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert gaps and all(g == pytest.approx(60) for g in gaps), times


def test_C3_first_sum_1m_covers_a_full_minute(h):
    """C3: The first 'sum_1m' value must cover a full minute.

    Currently the first value is published after the first 10 s tick and
    contains only 10 s of data, but is published as a 1-minute sum.
    """
    for s in range(0, 60):
        h.send(CURRENT, "1", at=T0 + s + 0.5)   # 1 message per second
        if (s + 1) % 10 == 0:
            h.tick(T0 + s + 1)
    assert h.values(SUM_1M) == [60.0]


def test_C4_two_aggregates_with_same_name_on_one_topic(h):
    """C4: README example has sum/60 s and sum/3600 s on the same topic.

    Both must be published independently. Today the last execution time is
    stored per aggregate *name*, so 'sum_1h' is never published.
    """
    for t in ticks(T0, T0 + 3600):
        h.send(CURRENT, "1", at=t - 5)
        h.tick(t)
    assert len(h.values(SUM_1M)) >= 59
    assert h.values(SUM_1H), "sum_1h was never published"


def test_C5_sum_1h_contains_the_whole_hour(h):
    """C5: The hourly sum equals the sum of all messages of that hour."""
    for t in ticks(T0, T0 + 7200):
        h.send(CURRENT, "1", at=t - 5)
        h.tick(t)
    hourly = h.values(SUM_1H)
    assert hourly and hourly[-1] == 360.0, hourly


def test_C6_message_on_window_boundary_counted_once(h):
    """C6: Consecutive windows must not overlap.

    A message whose timestamp equals the tick time is included in the
    window ending at that tick (>= start, no upper bound) and again in the
    next window (>= last_execution).
    """
    for t in ticks(T0, T0 + 60):
        h.tick(t)
    h.send(CURRENT, "1", at=T0 + 120)
    for t in ticks(T0 + 60, T0 + 180):
        h.tick(t)
    assert sum(h.values(SUM_1M)) == 1.0, h.values(SUM_1M)


def test_C7_no_messages_lost_with_tick_drift(h):
    """C7: Every message is counted in exactly one 1-minute window.

    The loop sleeps min_interval and then works, so ticks drift (here
    10.01 s). The next window starts at max(last_execution, now-interval),
    which skips the slice between last_execution and now-interval.
    """
    step = 10.01
    sent = 0
    t_msg = T0 + 0.25
    end = T0 + 30 * 60
    # Send 2 messages/s for 30 minutes, then keep ticking 2 more minutes
    # without messages so that every window is closed and published.
    for t in ticks(T0, end + 120, step):
        while t_msg < min(t, end):
            h.send(CURRENT, "1", at=t_msg)
            sent += 1
            t_msg += 0.5
        h.tick(t)
    assert sum(h.values(SUM_1M)) == sent
    # every value covers exactly one minute (2 messages/s * 60 s)
    assert set(h.values(SUM_1M)) == {120.0}


def test_C8_interval_not_multiple_of_min_interval_loses_no_data(make_harness):
    """C8: interval=15 with min_interval=10: no message may be dropped."""
    h = make_harness(_single_aggregate_config("sum", interval=15))
    for s in range(0, 120):
        h.send("in", "1", at=T0 + s + 0.5)
        if (s + 1) % 10 == 0:
            h.tick(T0 + s + 1)
    h.tick(T0 + 130)
    h.tick(T0 + 140)  # close all remaining windows
    assert sum(h.values("out")) == 120
    # every value covers exactly 15 s (1 message/s)
    assert set(h.values("out")) == {15.0}


def test_C9_dst_switch_does_not_stop_aggregation(make_harness):
    """C9: Aggregation continues across a DST switch.

    main.py mixes naive local datetimes with epoch timestamps. When local
    time falls back one hour, now - last_execution becomes negative and no
    aggregate is published for an hour. (Relevant when TZ is set, e.g.
    TZ=Europe/Berlin in docker-compose.)
    """
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Berlin"
    time.tzset()
    try:
        switch = 1792890000.0  # 2026-10-25 01:00 UTC: CEST -> CET
        start = switch - 120
        h = make_harness(clock=FakeClock(start))
        for t in ticks(start, switch + 600):
            h.send(COUNTER, "1", at=t - 5)
            h.tick(t)
        published_after_switch = [t for t in h.times(MAX_10S) if t > switch]
        assert len(published_after_switch) >= 59, published_after_switch
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()


def test_C10_empty_window_publishes_nothing_and_does_not_crash(h):
    """C10: Ticks without messages must not raise (e.g. avg division by zero)."""
    h.send(CURRENT, "1", at=T0 + 1)
    for t in ticks(T0, T0 + 300):
        h.tick(t)
    assert h.values(SUM_1M) == [1.0]


def test_C11_old_messages_are_eventually_discarded(h):
    """C11: Messages older than the largest interval are not kept forever."""
    for t in ticks(T0, T0 + 2 * 3600):
        h.send(CURRENT, "1", at=t - 5)
        h.tick(t)
    assert len(h.userdata["message_map"][CURRENT]) <= 3600 / 10 + 1


# ---------------------------------------------------------------------------
# D. Output: "Displays the aggregated results on the console" and
#    "Publishes the aggregated results to MQTT topics (if configured)"
# ---------------------------------------------------------------------------

def test_D1_result_published_to_configured_topic(h):
    """D1: Aggregates with 'topic' are published to exactly that topic."""
    h.send(COUNTER, "12", at=T0 + 1)
    h.tick(T0 + 10)
    assert [(t, p) for _, t, p in h.published] == [(MAX_10S, "12.0")]


def test_D2_aggregate_without_topic_only_printed(make_harness, capsys):
    """D2: Aggregate without 'topic' -> console only, no MQTT publish."""
    cfg = _single_aggregate_config("avg")
    del cfg["topics"][0]["aggregates"][0]["topic"]
    h = make_harness(cfg)
    h.send("in", "4", at=T0 + 1)
    h.tick(T0 + 10)
    assert h.published == []
    assert "4.0" in capsys.readouterr().out


def test_D3_result_shown_on_console(h, capsys):
    """D3: Every aggregate result is printed to the console."""
    h.send(COUNTER, "12", at=T0 + 1)
    h.tick(T0 + 10)
    out = capsys.readouterr().out
    assert COUNTER in out and "12.0" in out


def test_D4_publish_uses_configured_broker(h):
    """D4: publish_mqtt connects to mqtt.host / mqtt.port from the config."""
    calls = []

    class FakeClient:
        def connect(self, host, port, *a, **k):
            calls.append(("connect", host, port))

        def publish(self, topic, payload, *a, **k):
            calls.append(("publish", topic, payload))

        def disconnect(self):
            calls.append(("disconnect",))

    h.m.mqtt = types.SimpleNamespace(Client=FakeClient)
    h.original_publish_mqtt("a/b", "1.0")
    assert calls == [("connect", "192.168.191.14", 1883),
                     ("publish", "a/b", "1.0"), ("disconnect",)]


def test_D5_publish_failure_does_not_stop_other_aggregates(h):
    """D5: If publishing one result fails (broker briefly unreachable), the
    other aggregates are still processed and aggregate_data does not raise
    (otherwise the main loop and the whole program end)."""
    def failing_publish(topic, payload):
        if topic == SUM_1M:
            raise ConnectionRefusedError("broker down")
        h.published.append((h.clock.t, topic, payload))

    h.m.publish_mqtt = failing_publish
    h.send(CURRENT, "1", at=T0 + 1)
    h.send(COUNTER, "5", at=T0 + 2)
    h.tick(T0 + 60)
    assert h.values(MAX_10S) == [5.0]


# ---------------------------------------------------------------------------
# E. Subscription / configuration:
#    "Connects to an MQTT broker and subscribes to specified topics"
# ---------------------------------------------------------------------------

class SubscribeRecorder:
    def __init__(self):
        self.topics = []

    def subscribe(self, topic, *a, **k):
        self.topics.append(topic)


def test_E1_subscribes_to_all_configured_topics(h):
    """E1: on_connect subscribes to every configured input topic."""
    rec = SubscribeRecorder()
    h.m.on_connect(rec, h.userdata, {}, 0)
    assert sorted(rec.topics) == sorted([CURRENT, COUNTER])


def test_E2_resubscribes_after_reconnect(h):
    """E2: After a reconnect (on_connect called again) topics are subscribed again."""
    rec = SubscribeRecorder()
    h.m.on_connect(rec, h.userdata, {}, 0)
    h.m.on_connect(rec, h.userdata, {}, 0)
    assert rec.topics.count(CURRENT) == 2


def test_E3_topic_without_aggregates(make_harness):
    """E3: A topic without 'aggregates' must not break the program."""
    cfg = copy.deepcopy(README_CONFIG)
    cfg["topics"].append({"name": "plain/topic"})
    h = make_harness(cfg)
    h.send("plain/topic", "1", at=T0 + 1)
    h.tick(T0 + 10)


def test_E4_unknown_aggregate_name_is_rejected(make_harness, capsys):
    """E4: README mentions 'average'; the code only knows 'avg'.

    A misspelled/unknown aggregate name must be reported (at startup or on
    the console), not silently ignored.
    """
    h = make_harness(_single_aggregate_config("average"))
    h.send("in", "1", at=T0 + 1)
    h.tick(T0 + 10)
    out = capsys.readouterr().out.lower()
    assert "average" in out and ("unknown" in out or "unsupported" in out or "invalid" in out)


def test_E5_wildcard_topic_subscription(make_harness):
    """E5: MQTT wildcard topics ('+', '#') as input topic.

    The subscription works, but aggregate_data looks the config up by exact
    topic name, so messages from 'sensor/a/state' never match 'sensor/+/state'.
    (README does not mention wildcards explicitly; this documents behaviour.)
    """
    cfg = _single_aggregate_config("sum")
    cfg["topics"][0]["name"] = "sensor/+/state"
    h = make_harness(cfg)
    h.send("sensor/a/state", "1", at=T0 + 1)
    h.tick(T0 + 10)
    assert h.values("out") == [1.0]


# ---------------------------------------------------------------------------
# F. Concurrency: messages arrive in the paho network thread while the main
#    thread aggregates. Interleaving is simulated deterministically by
#    delivering a message from inside publish_mqtt.
# ---------------------------------------------------------------------------

def test_F1_first_message_of_topic_during_aggregation(h):
    """F1: The first message of a topic arriving while aggregate_data iterates
    message_map must not raise 'dictionary changed size during iteration'."""
    def publish_and_receive(topic, payload):
        h.published.append((h.clock.t, topic, payload))
        if COUNTER not in h.userdata["message_map"]:
            h.send(COUNTER, "3")

    h.m.publish_mqtt = publish_and_receive
    h.send(CURRENT, "1", at=T0 + 1)
    h.tick(T0 + 60)
    assert COUNTER in h.userdata["message_map"]


def test_F2_message_during_aggregation_is_not_lost(h):
    """F2: A message arriving during aggregation is counted in the next window."""
    fired = []

    def publish_and_receive(topic, payload):
        h.published.append((h.clock.t, topic, payload))
        if not fired:
            fired.append(1)
            h.clock.t += 0.001
            h.send(COUNTER, "8")

    h.m.publish_mqtt = publish_and_receive
    h.send(COUNTER, "1", at=T0 + 1)
    h.tick(T0 + 10)
    h.tick(T0 + 20)
    assert h.values(MAX_10S) == [1.0, 8.0]
