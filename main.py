import paho.mqtt.client as mqtt
import yaml
import time

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
    userdata["message_map"][topic].append(float(message))

    # Print the collected message and timestamp
    print(f"Collected message from topic '{topic}': {message}")

def sum_aggregate(messages):
    # Placeholder for sum aggregation
    return sum(messages)

def avg_aggregate(messages):
    # Placeholder for average aggregation
    return sum(messages) / len(messages)

def max_aggregate(messages):
    # Placeholder for max aggregation
    return max(messages)

def aggregate_data(userdata):
    # Perform aggregation for each topic
    for topic, messages in userdata["message_map"].items():
        topic_config = next((t for t in userdata["topics"] if t["name"] == topic), None)
        if topic_config:
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
                    aggregate_result = aggregate_func(messages)
                    print(f"Aggregated result for topic '{topic}' using '{aggregate_name}': {aggregate_result}")
                    # Add your code to process the aggregate result here

    # Clear the collected messages after aggregation
    userdata["message_map"] = {}

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
    while True:
        time.sleep(config["aggregation_interval"])
        aggregate_data(client._userdata)

except KeyboardInterrupt:
    # Stop the MQTT network loop
    client.loop_stop()
