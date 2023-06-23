# MQTT Message Resampler

The MQTT Message Collector is a tool that collects MQTT messages from specified topics, performs aggregations on the data, and publishes the aggregated results.

Messages on MQTT need to be plain values. JSON Messages are not supported.

## Functionality

- Connects to an MQTT broker and subscribes to specified topics
- Collects MQTT messages and performs aggregations (sum, average, max) based on the defined intervals
- Displays the aggregated results on the console
- Publishes the aggregated results to MQTT topics (if configured)
- Supports configuration of topics, aggregation intervals, and MQTT broker settings

## Configuration

The configuration of the MQTT Message Collector is done through the `config.yaml` file. You can modify this file to specify the MQTT broker host, port, topics, and their corresponding aggregations and intervals.

Here's an example configuration:

```yaml
min_interval: 10
mqtt:
  host: 192.168.191.14
  port: 1883
topics:
  - name: gridmeter/sensor/powerconsumecurrent/state
    aggregates:
      - name: sum
        interval: 60
        topic: gridmeter/sensor/powerconsumecurrent/sum_1m
      - name: sum
        interval: 3600
        topic: gridmeter/sensor/powerconsumecurrent/sum_1h
      
  - name: gridmeter/sensor/powerconsumecounter/state
    aggregates:
      - name: max
        topic: gridmeter/sensor/powerconsumecounter/max_10s
```

Make sure to adjust the configuration according to your MQTT broker settings and desired topics/aggregations.

# Setup and Usage

1. Clone the repository:
    ```
    git clone https://github.com/tgruenert/mqtt-resampler.git
    ```

2. Install the required Python dependencies:
    ```
    pip install -r requirements.txt
    ```

3. Edit the `config.yaml` file to configure your MQTT broker and topics/aggregations.

4. Run the MQTT Message Collector:
    ```
    python main.py
    ```
    The program will start connecting to the MQTT broker and collecting messages based on the defined intervals.

# Deploying with Docker Compose

To deploy the MQTT Message Collector using Docker Compose, follow these steps:

1. Install Docker and Docker Compose if you haven't already.

2. Create a Docker Compose file docker-compose.yaml or use the one from this repository:
    ```
    version: '3'
    services:
    mqtt-resampler:
        image: tgruenert/mqtt-resampler:v1.0
        volumes:
        - ./config.yaml:/app/config.yaml
        restart: always
    ```
    This Compose file mounts the config.yaml file into the container.

3. Adjust the `config.yaml` file according to your MQTT broker settings and topics/aggregations.

4. Start the MQTT Message Collector using Docker Compose:    
    ```
    docker-compose up -d
    ```
    The container will be started and the MQTT Message Collector will begin collecting and aggregating MQTT messages based on the defined configuration.


