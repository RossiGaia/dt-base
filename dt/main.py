from flask import Flask
import paho.mqtt.client as mqtt, collections, json, time, threading

app = Flask(__name__)

messages_deque = collections.deque(maxlen=100)
current_average = None
current_led_state = None

#odte
observations = collections.deque(maxlen=100)

MQTT_BROKER = "192.168.58.2"
MQTT_PORT = 31095
MQTT_TOPIC = "led_1"

# WARN: lunghezza window = numero di elementi perche
#       invia un aggiornamento al secondo

def compute_timeliness(desired_timeliness_sec: float) -> float:
    global observations
    obs_list = list(observations)

    if len(obs_list) == 0:
        return 0.0

    count = 0
    for obs in obs_list:
        if obs <= desired_timeliness_sec:
            count += 1

    percentile = float(count/len(obs_list))

    return percentile

def compute_reliability(window_length_sec: int, expected_msg_sec: int) -> float:
    global messages_deque
    end_window_time = time.time()
    start_window_time = time.time() - window_length_sec

    msg_list = list(messages_deque)
    msg_required = msg_list[-window_length_sec:]

    if len(msg_required) == 0:
        return 0.0

    count = 0
    for msg in msg_required:
        if msg["timestamp"] >= start_window_time and msg["timestamp"] <= end_window_time:
            count += 1

    if window_length_sec >= len(msg_list):
        expected_msg_tot = len(msg_list) * expected_msg_sec
    else:
        expected_msg_tot = window_length_sec * expected_msg_sec

    return float(count/expected_msg_tot)

def compute_availability() -> float:
    return 1.0

def compute_odte_phytodig(window_length_sec, desired_timeliness_sec, expected_msg_sec):
    timeliness = compute_timeliness(desired_timeliness_sec)
    reliability = compute_reliability(window_length_sec, expected_msg_sec)
    availability = compute_availability()
    print(f"Availability: {availability}\tReliability: {reliability}\tTimeliness: {timeliness}")
    return timeliness * reliability * availability

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f"Connected to MQTT Broker at {MQTT_BROKER}")

def on_message(client, userdata, message):
    global messages_deque, current_average, current_led_state, observations
    received_timestamp = time.time()
    start_exec_time = time.time()
    # print(f"Received message {message.payload} on topic {message.topic}")
    data = json.loads(message.payload)
    messages_deque.append(data)

    current_led_state = data["state"]

    tot = 0
    for payload in messages_deque:
        tot += payload["power_consumption"]
    current_average = tot/len(messages_deque)
    # print(f"Current average is {current_average} and current state is {current_led_state}")

    end_exec_time = time.time()
    execution_timestamp = end_exec_time - start_exec_time
    message_timestamp = data["timestamp"]

    # odte timeliness computation
    observations.append(received_timestamp - message_timestamp + execution_timestamp)
    

def odte_thread():
    while True:
        computed_odte = compute_odte_phytodig(30, 0.5 ,1)
        print(f"ODTE computed {computed_odte}")   
        time.sleep(1)  

@app.route("/metrics")
def odte_prometheus():
    odte = compute_odte_phytodig(30, 0.5 ,1)
    prometheus_template = f"odte[pt=\"led_1\"] {str(odte)}".replace("[", "{").replace("]", "}")
    return prometheus_template

if __name__ == "__main__":

    odte_t = threading.Thread(target=odte_thread, daemon=True)
    odte_t.start()

    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    mqtt_client.connect(MQTT_BROKER, MQTT_PORT)
    mqtt_client.subscribe(MQTT_TOPIC)

    mqtt_client.loop_start()

    app.run(host='0.0.0.0', port=8000)
