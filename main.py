import paho.mqtt.client as mqtt
import yaml
import math
import os
import threading
import time


def sum_aggregate(values):
    return sum(values)


def avg_aggregate(values):
    return sum(values) / len(values)


def max_aggregate(values):
    return max(values)


AGGREGATE_FUNCTIONS = {
    "sum": sum_aggregate,
    "avg": avg_aggregate,
    "max": max_aggregate,
}

# Collected messages per configured input topic: list of (value, timestamp).
message_map = {}

# message_map is written by the paho network thread (on_message) and read by
# the main thread (aggregate_data).
lock = threading.Lock()


class MyMQTTClient(mqtt.Client):
    def __init__(self, userdata):
        super().__init__()
        self._userdata = userdata


def on_connect(client, userdata, flags, rc):
    print("Connected with result code " + str(rc))
    # (Re-)subscribe to all configured topics on every (re)connect
    for topic_config in userdata["topics"]:
        client.subscribe(topic_config["name"])


def parse_value(payload):
    """Return the payload as a finite float, or None if it is no plain number."""
    try:
        value = float(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def on_message(client, userdata, msg):
    # Exceptions raised here would end paho's network thread, so invalid
    # messages are reported and dropped instead.
    try:
        topic = msg.topic
    except UnicodeDecodeError:
        print("Ignored message with invalid topic name")
        return

    value = parse_value(msg.payload)
    if value is None:
        print(f"Ignored message from topic '{topic}': not a plain numeric value: {msg.payload!r}")
        return

    # A message may match several configured topics (wildcards '+' and '#').
    matched = [t["name"] for t in userdata["topics"]
               if mqtt.topic_matches_sub(t["name"], topic)]

    with lock:
        # Timestamp taken under the lock: every message appended after an
        # aggregation run is newer than that run's "now".
        received_at = time.time()
        for name in matched:
            userdata["message_map"].setdefault(name, []).append((value, received_at))

    print(f"Collected message from topic '{topic}': {value}")


def publish_mqtt(topic, payload):
    # Configure MQTT client
    client = mqtt.Client()
    # Connect to MQTT broker
    client.connect(config["mqtt"]["host"], config["mqtt"]["port"])
    # Publish message
    client.publish(topic, payload)
    # Disconnect from MQTT broker
    client.disconnect()


def window_start(timestamp, interval):
    """Start of the interval-aligned window containing timestamp."""
    return math.floor(timestamp / interval) * interval


def aggregate_data(userdata):
    """Aggregate and publish all windows that have ended.

    Windows are half-open [start, start + interval) and aligned to multiples
    of the interval (epoch based, so independent of time zone and DST). Every
    message is counted in exactly one window per aggregate, independent of how
    often or how regularly this function is called.
    """
    window_starts = userdata.setdefault("window_start", {})
    results = []

    with lock:
        now = time.time()
        for topic_config in userdata["topics"]:
            topic = topic_config["name"]
            messages = userdata["message_map"].get(topic)
            if not messages:
                continue

            oldest_needed = now
            for index, aggregate_config in enumerate(topic_config.get("aggregates") or []):
                aggregate_func = AGGREGATE_FUNCTIONS.get(aggregate_config["name"])
                if aggregate_func is None:
                    continue
                interval = aggregate_config.get("interval", min_interval)

                # State is kept per aggregate entry, so several aggregates
                # with the same name on one topic do not interfere.
                key = (topic, index)
                start = window_starts.get(key)
                if start is None:
                    start = window_start(min(ts for _, ts in messages), interval)

                while start + interval <= now:
                    end = start + interval
                    values = [v for v, ts in messages if start <= ts < end]
                    if values:
                        results.append((topic, aggregate_config, aggregate_func(values)))
                        start = end
                    else:
                        # Skip empty windows up to the next message.
                        later = [ts for _, ts in messages if ts >= end]
                        start = max(end, window_start(min(later) if later else now, interval))

                window_starts[key] = start
                oldest_needed = min(oldest_needed, start)

            # Drop messages that no pending window needs anymore
            userdata["message_map"][topic] = [m for m in messages if m[1] >= oldest_needed]

    # Print and publish outside the lock so message reception is not blocked.
    for topic, aggregate_config, result in results:
        print(f"Aggregated result for topic '{topic}' using '{aggregate_config['name']}': {result}")
        mqtt_topic = aggregate_config.get("topic")
        if mqtt_topic:
            try:
                publish_mqtt(mqtt_topic, str(result))
            except Exception as err:
                print(f"Failed to publish to '{mqtt_topic}': {err}")


def validate_config(config):
    for topic_config in config["topics"]:
        for aggregate_config in topic_config.get("aggregates") or []:
            name = aggregate_config.get("name")
            if name not in AGGREGATE_FUNCTIONS:
                print(f"Warning: unknown aggregate '{name}' for topic '{topic_config['name']}' "
                      f"is ignored (supported: {', '.join(AGGREGATE_FUNCTIONS)})")


# Load configuration from YAML file (path can be overridden via CONFIG_FILE)
config_path = os.environ.get("CONFIG_FILE", "config.yaml")
with open(config_path, "r") as config_file:
    config = yaml.safe_load(config_file)

validate_config(config)
min_interval = config["min_interval"]

# Create an MQTT client
client = MyMQTTClient(userdata={"topics": config["topics"], "message_map": message_map})

# Set MQTT broker address and port from the configuration
broker_address = config["mqtt"]["host"]
broker_port = config["mqtt"]["port"]

# Set MQTT callbacks
client.on_connect = on_connect
client.on_message = on_message

# Connect to the MQTT broker
client.connect(broker_address, broker_port, 60)

# Start the MQTT network loop
client.loop_start()

# Start the data aggregation loop
try:
    while True:
        time.sleep(min_interval)

        try:
            aggregate_data(client._userdata)
        except Exception as err:
            print(f"Aggregation failed: {err}")

except KeyboardInterrupt:
    # Stop the MQTT network loop
    client.loop_stop()
