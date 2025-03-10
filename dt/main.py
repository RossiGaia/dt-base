from flask import Flask, request
from enum import Enum
import paho.mqtt.client as mqtt, collections, json, time, threading, os

POWER_CONSUMPTION_THRESHOLD = os.environ.get("POWER_CONSUMPTION_THRESHOLD", 0.2)

MQTT_BROKER = os.environ.get("MQTT_BROKER")
MQTT_PORT = os.environ.get("MQTT_PORT")
MQTT_TOPIC = os.environ.get("MQTT_TOPIC")

if MQTT_BROKER is None or \
    MQTT_PORT is None or \
    MQTT_TOPIC is None:
    print("Required vars for MQTT connection are not correctly configured.")
    exit(1)

ODTE_THRESHOLD = 0.6

class VIRTUAL_LED_STATE(Enum):
    ON = 1
    OFF = 0

class VIRTUAL_LED(object):
    def __init__(self, state = VIRTUAL_LED_STATE.OFF, power_consumption = 0):
        self._STATE = state
        self._POWER_CONSUMPTION  = power_consumption

    def get_state(self):
        return self._STATE
    
    def get_power_consumption(self):
        return self._POWER_CONSUMPTION

class DIGITAL_TWIN_STATE(Enum):
    UNBOUND = 0
    BOUND = 1
    ENTANGLED = 2
    DISENTANGLED = 3
    DONE = 4

class DIGITAL_TWIN:
    def __init__(self):
        global MQTT_BROKER, MQTT_PORT, MQTT_TOPIC
        self._STATE = DIGITAL_TWIN_STATE.UNBOUND
        self._OBJECT = VIRTUAL_LED()
        self._ODTE = None
        self._MESSAGES_DEQUE = collections.deque(maxlen=100)
        self._POWER_CONSUMPTION_AVERAGE = None
        self._OBSERVATIONS = collections.deque(maxlen=100)

        odte_t = threading.Thread(target=self.odte_thread, daemon=True)
        odte_t.start()

        self.connect_to_mqtt_and_subscribe(MQTT_BROKER, int(MQTT_PORT), MQTT_TOPIC)

    # {"state":{"_MESSAGES_DEQUE":[],"_OBJECT":{"_POWER_CONSUMPTION":0,"_STATE":"OFF"},"_OBSERVATIONS":[],"_ODTE":null,"_POWER_CONSUMPTION_AVERAGE":null,"_STATE":"UNBOUND"}}
    def restore_state(self, data):

        print(self.__dict__.copy())

        obj = data["state"]
        state_name = obj["_STATE"]
        self._STATE = DIGITAL_TWIN_STATE[state_name]

        virtual_led_state = obj["_OBJECT"]["_STATE"]
        virtual_led_pow_cons = obj["_OBJECT"]["_POWER_CONSUMPTION"]
        self._OBJECT = VIRTUAL_LED(VIRTUAL_LED_STATE[virtual_led_state], virtual_led_pow_cons)

        self._ODTE = obj["_ODTE"]

        message_deque_list = obj["_MESSAGES_DEQUE"]
        self._MESSAGES_DEQUE = collections.deque(message_deque_list, maxlen=100)

        self._POWER_CONSUMPTION_AVERAGE = obj["_POWER_CONSUMPTION_AVERAGE"]

        observations_list = obj["_OBSERVATIONS"]
        self._OBSERVATIONS = collections.deque(observations_list, maxlen=100)

        print(self.__dict__.copy())

        # restore connection to the broker after restoring state
        self.connect_to_mqtt_and_subscribe(MQTT_BROKER, int(MQTT_PORT), MQTT_TOPIC)

    def dump_state(self):
        # stop listening to updates so the state doesn t change
        self.disconnect_from_mqtt()

        obj = self.__dict__.copy()

        if "_MQTT_CLIENT" in obj.keys():
            obj.pop("_MQTT_CLIENT")

        obj["_OBJECT"] = self._OBJECT.__dict__.copy()
        obj["_OBJECT"]["_STATE"] = self._OBJECT._STATE.name

        obj["_STATE"] = self._STATE.name
        obj["_MESSAGES_DEQUE"] = list(self._MESSAGES_DEQUE)
        obj["_OBSERVATIONS"] = list(self._OBSERVATIONS)

        return obj

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            print(f"Connected to MQTT Broker at {MQTT_BROKER}")

    def on_message(self, client, userdata, message):

        received_timestamp = time.time()
        start_exec_time = time.time()
        # print(f"Received message {message.payload} on topic {message.topic}")
        data = json.loads(message.payload)
        self._MESSAGES_DEQUE.append(data)

        self._OBJECT._STATE = VIRTUAL_LED_STATE.ON if "ON" in data["state"] else VIRTUAL_LED_STATE.OFF
        self._OBJECT._POWER_CONSUMPTION = float(data["power_consumption"])

        tot = 0
        for payload in self._MESSAGES_DEQUE:
            tot += float(payload["power_consumption"])
        self._POWER_CONSUMPTION_AVERAGE = tot/len(self._MESSAGES_DEQUE)
        # print(f"Current average is {current_average} and current state is {current_led_state}")

        if self._POWER_CONSUMPTION_AVERAGE > POWER_CONSUMPTION_THRESHOLD:
            print("ALERT: power consumption avarage over threshold!")

        end_exec_time = time.time()
        execution_timestamp = end_exec_time - start_exec_time
        message_timestamp = data["timestamp"]

        # odte timeliness computation
        self._OBSERVATIONS.append(received_timestamp - message_timestamp + execution_timestamp)


    def connect_to_mqtt_and_subscribe(self, broker_ip, broker_port, topic):
        self._MQTT_CLIENT = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._MQTT_CLIENT.on_connect = self.on_connect
        self._MQTT_CLIENT.on_message = self.on_message

        self._MQTT_CLIENT.connect(broker_ip, broker_port)
        self._MQTT_CLIENT.subscribe(topic)

        self._STATE = DIGITAL_TWIN_STATE.BOUND

        self._MQTT_CLIENT.loop_start()

    def disconnect_from_mqtt(self):
        self._MQTT_CLIENT.loop_stop()
        self._STATE = DIGITAL_TWIN_STATE.UNBOUND

    def compute_timeliness(self, desired_timeliness_sec: float) -> float:
        obs_list = list(self._OBSERVATIONS)

        if len(obs_list) == 0:
            return 0.0

        count = 0
        for obs in obs_list:
            if obs <= desired_timeliness_sec:
                count += 1

        percentile = float(count/len(obs_list))

        return percentile

    def compute_reliability(self, window_length_sec: int, expected_msg_sec: int) -> float:
        end_window_time = time.time()
        start_window_time = time.time() - window_length_sec

        msg_list = list(self._MESSAGES_DEQUE)
        msg_required = msg_list[-window_length_sec:]

        count = 0
        for msg in msg_required:
            if msg["timestamp"] >= start_window_time and msg["timestamp"] <= end_window_time:
                count += 1

        expected_msg_tot = window_length_sec * expected_msg_sec

        return float(count/expected_msg_tot)

    def compute_availability(self) -> float:
        return 1.0

    def compute_odte_phytodig(self, window_length_sec, desired_timeliness_sec, expected_msg_sec):
        timeliness = self.compute_timeliness(desired_timeliness_sec)
        reliability = self.compute_reliability(window_length_sec, expected_msg_sec)
        availability = self.compute_availability()
        print(f"Availability: {availability}\tReliability: {reliability}\tTimeliness: {timeliness}")
        return timeliness * reliability * availability

    def odte_thread(self):
        global ODTE_THRESHOLD
        while True:
            if self._STATE == DIGITAL_TWIN_STATE.BOUND or \
                self._STATE == DIGITAL_TWIN_STATE.ENTANGLED or \
                self._STATE == DIGITAL_TWIN_STATE.DISENTANGLED:
                    computed_odte = self.compute_odte_phytodig(10, 0.5 ,1)
                    print(f"ODTE computed: {computed_odte}, state: {self._STATE}")
                    if computed_odte < ODTE_THRESHOLD and self._STATE == DIGITAL_TWIN_STATE.ENTANGLED:
                        self._STATE = DIGITAL_TWIN_STATE.DISENTANGLED
                    if computed_odte > ODTE_THRESHOLD and (self._STATE == DIGITAL_TWIN_STATE.DISENTANGLED or self._STATE == DIGITAL_TWIN_STATE.BOUND):
                        self._STATE = DIGITAL_TWIN_STATE.ENTANGLED
            time.sleep(1)  

DT = DIGITAL_TWIN()
app = Flask(__name__)

@app.route("/metrics")
def odte_prometheus():
    global DT
    odte = DT.compute_odte_phytodig(30, 0.5 ,1)
    prometheus_template = f"odte[pt=\"led_1\"] {str(odte)}".replace("[", "{").replace("]", "}")
    return prometheus_template

@app.route("/dump", methods=["POST"])
def dump_state():
    global DT
    obj = DT.dump_state()
    return {"state": obj}, 201

# {"state":{"_MESSAGES_DEQUE":["yo"],"_OBJECT":{"_POWER_CONSUMPTION":0,"_STATE":"OFF"},"_OBSERVATIONS":[],"_ODTE":null,"_POWER_CONSUMPTION_AVERAGE":null,"_STATE":"UNBOUND"}}
@app.route("/restore", methods=["POST"])
def restore_state():
    global DT
    data = request.get_json()
    DT.restore_state(data)

    return {"message": "restored"}, 201

app.run(host='0.0.0.0', port=8001)
