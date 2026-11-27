"""End-to-end tests: main.py as a separate process against a real broker.

Needs a reachable MQTT broker (default mosquitto:1883 from the dev container,
override with MQTT_TEST_HOST / MQTT_TEST_PORT). Skipped otherwise.
"""

import queue
import subprocess
import sys
import time
import uuid

import paho.mqtt.client as mqtt
import pytest
import yaml

from conftest import MAIN, broker_address, broker_available

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not broker_available(), reason="no MQTT broker reachable"),
]


@pytest.fixture
def prefix():
    return f"resampler-test/{uuid.uuid4().hex[:8]}"


@pytest.fixture
def resampler(tmp_path, prefix):
    host, port = broker_address()
    cfg = {
        "min_interval": 1,
        "mqtt": {"host": host, "port": port},
        "topics": [{
            "name": f"{prefix}/in",
            "aggregates": [
                {"name": "sum", "interval": 3, "topic": f"{prefix}/sum"},
                {"name": "max", "topic": f"{prefix}/max"},
            ],
        }],
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    proc = subprocess.Popen(
        [sys.executable, "-u", str(MAIN)],
        env={"CONFIG_FILE": str(path), "PATH": "/usr/bin:/bin"},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    time.sleep(1.5)  # connect + subscribe
    yield proc
    proc.terminate()
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def mqtt_io(prefix):
    host, port = broker_address()
    received = queue.Queue()
    c = mqtt.Client()
    c.on_message = lambda _c, _u, m: received.put((m.topic, m.payload.decode()))
    c.connect(host, port)
    c.subscribe(f"{prefix}/#")
    c.loop_start()
    time.sleep(0.3)
    yield c, received
    c.loop_stop()
    c.disconnect()


def collect(received, topic, seconds):
    end = time.time() + seconds
    out = []
    while time.time() < end:
        try:
            t, p = received.get(timeout=0.1)
        except queue.Empty:
            continue
        if t == topic:
            out.append(float(p))
    return out


def test_G1_end_to_end_sum_is_published(resampler, mqtt_io, prefix):
    """G1: Values published on the input topic arrive aggregated on the output topic."""
    client, received = mqtt_io
    for v in ("1", "2", "4"):
        client.publish(f"{prefix}/in", v).wait_for_publish()
    sums = collect(received, f"{prefix}/sum", 8)
    # the three values may fall into two consecutive windows
    assert sum(sums) == 7.0, sums


def test_G2_invalid_message_does_not_stop_processing(resampler, mqtt_io, prefix):
    """G2: After a non-numeric message, later valid messages are still aggregated."""
    client, received = mqtt_io
    client.publish(f"{prefix}/in", "hello").wait_for_publish()
    time.sleep(0.5)
    client.publish(f"{prefix}/in", "9").wait_for_publish()
    maxes = collect(received, f"{prefix}/max", 5)
    assert 9.0 in maxes, maxes
    assert resampler.poll() is None, "resampler process died"


def test_G3_process_keeps_running(resampler, mqtt_io, prefix):
    """G3: The resampler keeps running and publishing over several intervals."""
    client, received = mqtt_io
    for _ in range(6):
        client.publish(f"{prefix}/in", "1").wait_for_publish()
        time.sleep(1)
    assert resampler.poll() is None
    assert len(collect(received, f"{prefix}/max", 3)) >= 1
