import paho.mqtt.client as mqtt
import yaml
import time
from datetime import datetime, timedelta

# Dictionary to store collected messages
message_map = {}

class MyMQTTClient(mqtt.Client):
    def __init__(self, userdata):
        super().__init__()
        self._userdata = userdata

def on_connect(client, userdata, flags, rc):
    print("Connected with result code " + str(rc))
    # Subscribe to MQTT topics upon successful connection
    for topic_config in userdata["topics"]:
        topic = topic_config["name"]
        client.subscribe(topic)
    # Add more topics as needed

def on_message(client, userdata, msg):
    # Retrieve the topic and message payload
    topic = msg.topic
    message = msg.payload.decode("utf-8")

    # Check if the topic exists in the message_map dictionary
    if topic not in userdata["message_map"]:
        userdata["message_map"][topic] = []

    # Append the message and timestamp to the array for the corresponding topic
    userdata["message_map"][topic].append((float(message), time.time()))

    # Print the collected message and timestamp
    print(f"Collected message from topic '{topic}': {message}")

def sum_aggregate(messages):
    # Placeholder for sum aggregation
    return sum([msg[0] for msg in messages])

def avg_aggregate(messages):
    # Placeholder for average aggregation
    values = [msg[0] for msg in messages]
    return sum(values) / len(values)

def max_aggregate(messages):
    # Placeholder for max aggregation
    return max([msg[0] for msg in messages])

def publish_mqtt(topic, payload):
    # Configure MQTT client
    client = mqtt.Client()
    # Connect to MQTT broker
    client.connect(config["mqtt"]["host"], config["mqtt"]["port"])
    # Publish message
    client.publish(topic, payload)
    # Disconnect from MQTT broker
    client.disconnect()    

def aggregate_data(userdata):
    # Get the minimum interval from the configuration
    # min_interval = userdata.get("min_interval")

    # Initialize the last_execution dictionary if it doesn't exist
    if "last_execution" not in userdata:
        userdata["last_execution"] = {}

    # Determine the maximum interval among all topics and aggregates
    max_interval = min_interval
    for topic, messages in userdata["message_map"].items():
        topic_config = next((t for t in userdata["topics"] if t["name"] == topic), None)
        if topic_config:
            for aggregate_config in topic_config.get("aggregates", []):
                interval = aggregate_config.get("interval", min_interval)
                max_interval = max(max_interval, interval)

    # Perform aggregation for each topic
    now = datetime.now()
    for topic, messages in userdata["message_map"].items():
        topic_config = next((t for t in userdata["topics"] if t["name"] == topic), None)
        if topic_config:
            topic_last_execution = userdata["last_execution"].get(topic, {})
            for aggregate_config in topic_config.get("aggregates", []):
                aggregate_name = aggregate_config["name"]
                aggregate_func = None
                if aggregate_name == "sum":
                    aggregate_func = sum_aggregate
                elif aggregate_name == "avg":
                    aggregate_func = avg_aggregate
                elif aggregate_name == "max":
                    aggregate_func = max_aggregate

                if aggregate_func:
                    interval = aggregate_config.get("interval", min_interval)
                    last_execution = topic_last_execution.get(aggregate_name, now - timedelta(seconds=interval))
                    if now - last_execution >= timedelta(seconds=interval):
                        start_time = max(last_execution, now - timedelta(seconds=interval))
                        filtered_messages = [msg for msg in messages if datetime.fromtimestamp(msg[1]) >= start_time]
                        if filtered_messages:
                            aggregate_result = aggregate_func(filtered_messages)
                            print(f"Aggregated result for topic '{topic}' using '{aggregate_name}': {aggregate_result}")

                            # Publish the aggregate result to MQTT topic if specified
                            mqtt_topic = aggregate_config.get("topic")
                            if mqtt_topic:
                                publish_mqtt(mqtt_topic, str(aggregate_result))

                        # Update the last execution timestamp for the topic and aggregate
                        topic_last_execution[aggregate_name] = now
                        userdata["last_execution"][topic] = topic_last_execution

    # Clear old messages
    for topic, messages in userdata["message_map"].items():
        userdata["message_map"][topic] = [msg for msg in messages if datetime.fromtimestamp(msg[1]) >= now - timedelta(seconds=max_interval)] if max_interval is not None else messages

# Load configuration from YAML file
with open("config.yaml", "r") as config_file:
    config = yaml.safe_load(config_file)

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
    min_interval = config["min_interval"]

    while True:
        time.sleep(min_interval)

        # Perform aggregation
        aggregate_data(client._userdata)

except KeyboardInterrupt:
    # Stop the MQTT network loop
    client.loop_stop()
