"""Test harness for main.py.

main.py executes its whole program at import time (loads config, connects to
the broker, runs an endless loop). To test its functions without changing it,
the module is imported with:

- CONFIG_FILE pointing to a temporary config,
- paho's Client.connect / loop_start / loop_stop replaced by no-ops,
- time.sleep raising KeyboardInterrupt, which ends the main loop right away.

Time is simulated with FakeClock: main.datetime.now(), datetime.fromtimestamp()
and time.time() all read the same fake clock.
"""

import importlib.util
import os
import socket
import sys
import time
import types
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as paho
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "main.py"

# Example configuration copied verbatim from README.md ("Configuration").
README_CONFIG = {
    "min_interval": 10,
    "mqtt": {"host": "192.168.191.14", "port": 1883},
    "topics": [
        {
            "name": "gridmeter/sensor/powerconsumecurrent/state",
            "aggregates": [
                {"name": "sum", "interval": 60,
                 "topic": "gridmeter/sensor/powerconsumecurrent/sum_1m"},
                {"name": "sum", "interval": 3600,
                 "topic": "gridmeter/sensor/powerconsumecurrent/sum_1h"},
            ],
        },
        {
            "name": "gridmeter/sensor/powerconsumecounter/state",
            "aggregates": [
                {"name": "max",
                 "topic": "gridmeter/sensor/powerconsumecounter/max_10s"},
            ],
        },
    ],
}

CURRENT = "gridmeter/sensor/powerconsumecurrent/state"
COUNTER = "gridmeter/sensor/powerconsumecounter/state"
SUM_1M = "gridmeter/sensor/powerconsumecurrent/sum_1m"
SUM_1H = "gridmeter/sensor/powerconsumecurrent/sum_1h"
MAX_10S = "gridmeter/sensor/powerconsumecounter/max_10s"

# 2026-01-01 00:00:00 UTC, far away from any DST switch.
T0 = 1767225600.0


class FakeClock:
    def __init__(self, t=T0):
        self.t = t


def load_main(tmp_path, monkeypatch, config):
    """Import main.py as a fresh module with the given config dict."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(config))
    monkeypatch.setenv("CONFIG_FILE", str(cfg))
    monkeypatch.setattr(paho.Client, "connect", lambda self, *a, **k: 0)
    monkeypatch.setattr(paho.Client, "loop_start", lambda self: None)
    monkeypatch.setattr(paho.Client, "loop_stop", lambda self, *a, **k: None)

    def stop_loop(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(time, "sleep", stop_loop)

    spec = importlib.util.spec_from_file_location("resampler_main", MAIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.undo()  # restore time.sleep etc. for the rest of the test
    return module


class FakeMsg:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload if isinstance(payload, bytes) else str(payload).encode()


class Harness:
    """Drives main.py's callbacks with a simulated clock."""

    def __init__(self, module, clock):
        self.m = module
        self.clock = clock
        self.published = []  # list of (simulated time, topic, payload)

        clk = clock

        class FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.fromtimestamp(clk.t, tz)

        module.datetime = FakeDatetime
        module.time = types.SimpleNamespace(time=lambda: clk.t, sleep=time.sleep)
        self.original_publish_mqtt = module.publish_mqtt
        module.publish_mqtt = self._record_publish

    def _record_publish(self, topic, payload):
        self.published.append((self.clock.t, topic, payload))

    @property
    def userdata(self):
        return self.m.client._userdata

    def send(self, topic, payload, at=None):
        """Deliver an MQTT message to on_message at simulated time `at`."""
        if at is not None:
            self.clock.t = at
        self.m.on_message(self.m.client, self.userdata, FakeMsg(topic, payload))

    def tick(self, at):
        """Run one aggregation cycle at simulated time `at`."""
        self.clock.t = at
        self.m.aggregate_data(self.userdata)

    def values(self, topic):
        return [float(p) for _, t, p in self.published if t == topic]

    def times(self, topic):
        return [ts for ts, t, _ in self.published if t == topic]


@pytest.fixture
def make_harness(tmp_path, monkeypatch):
    def factory(config=README_CONFIG, clock=None):
        module = load_main(tmp_path, monkeypatch, config)
        return Harness(module, clock or FakeClock())

    return factory


@pytest.fixture
def h(make_harness):
    """Harness with the README example configuration."""
    return make_harness()


def broker_address():
    host = os.environ.get("MQTT_TEST_HOST", "mosquitto")
    port = int(os.environ.get("MQTT_TEST_PORT", "1883"))
    return host, port


def broker_available():
    host, port = broker_address()
    try:
        socket.create_connection((host, port), timeout=1).close()
        return True
    except OSError:
        return False


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: needs a running MQTT broker (MQTT_TEST_HOST)")
    sys.dont_write_bytecode = True
