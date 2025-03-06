from flask import Flask
from enum import Enum
import random, time, threading, json, os, paho.mqtt.client as mqtt

app = Flask(__name__)

class LED_STATE(Enum):
    ON = 1
    OFF = 0

class LED:
    def __init__(self):
        self._STATE = LED_STATE.OFF
        self._POWER_CONSUMPTION  = 0
        self._lock = threading.Lock()

    def toggle(self):
        with self._lock:
            if self._STATE == LED_STATE.OFF:
                self._STATE = LED_STATE.ON
            else:
                self._STATE = LED_STATE.OFF

    def get_state(self):
        with self._lock:
            return self._STATE
    
    def get_power_consumption(self):
        with self._lock:
            return random.random() if self._STATE == LED_STATE.ON else 0.0
    
led = LED()

# MQTT
MQTT_BROKER = os.environ.get("MQTT_BROKER")
MQTT_PORT = os.environ.get("MQTT_PORT")
MQTT_TOPIC = os.environ.get("MQTT_TOPIC")

if MQTT_BROKER is None or \
    MQTT_PORT is None or \
    MQTT_TOPIC is None:
    print("Required vars for MQTT connection are not correctly configured.")
    exit(1)

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f"Connected to MQTT Broker at {MQTT_BROKER}")

mqtt_client.on_connect = on_connect
mqtt_client.connect(MQTT_BROKER, MQTT_PORT)

# Endpoints for PT
@app.route("/power_consumption")
def access_power_consumption():
    global led
    data = {
        "value": led.get_power_consumption(),
        "timestamp": time.time()
    }
    return json.dumps(data)

@app.route("/led_state")
def access_led_state():
    global led
    data = {
        "value": led.get_state().name,
        "timestamp": time.time()
    }
    return json.dumps(data)

@app.route("/toggle")
def toggle():
    global led
    led.toggle()
    return json.dumps({
        "message": "LED toggled",
        "new_state": led.get_state().name
        })

# Threads
def publish_to_mqtt_thread():
    global led, mqtt_client

    mqtt_client.loop_start()

    while True:
        data = {
            "state": led.get_state().name,
            "power_consumption": led.get_power_consumption(),
            "timestamp": time.time()
        }

        mqtt_client.publish(MQTT_TOPIC, json.dumps(data))
        print(f"Published message: {data}")
        time.sleep(1)

def toggle_thread():
    global led
    while True:
        wait_time = random.randint(5, 30)
        time.sleep(wait_time)
        led.toggle()

if __name__ == "__main__":
    toggle_t = threading.Thread(target=toggle_thread, daemon=True)
    toggle_t.start()

    publish_t = threading.Thread(target=publish_to_mqtt_thread, daemon=True)    
    publish_t.start()

    app.run(host='0.0.0.0', port=8000)