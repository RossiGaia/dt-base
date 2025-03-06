from flask import Flask, request
from enum import Enum
import collections, time, threading, os

ODTE_THRESHOLD = 0.6
POWER_CONSUMPTION_THRESHOLD = os.environ.get("POWER_CONSUMPTION_THRESHOLD", 0.2)

class VIRTUAL_LED_STATE(Enum):
    ON = 1
    OFF = 0

class VIRTUAL_LED:
    def __init__(self):
        self._STATE = VIRTUAL_LED_STATE.OFF
        self._POWER_CONSUMPTION  = 0

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

    def handle_update(self, data: dict):
        received_timestamp = data["received_timestamp"]
        start_exec_time = data["start_exec_timestamp"]

        data.pop("received_timestamp")
        data.pop("start_exec_timestamp")

        self._MESSAGES_DEQUE.append(data)

        self._OBJECT._STATE = VIRTUAL_LED_STATE.ON if "ON" in data["state"] else VIRTUAL_LED_STATE.OFF
        self._OBJECT._POWER_CONSUMPTION = float(data["power_consumption"])

        tot = 0
        for payload in self._MESSAGES_DEQUE:
            tot += float(payload["power_consumption"])
        self._POWER_CONSUMPTION_AVERAGE = tot/len(self._MESSAGES_DEQUE)
        print(f"Current average is {self._POWER_CONSUMPTION_AVERAGE}")

        if self._POWER_CONSUMPTION_AVERAGE > POWER_CONSUMPTION_THRESHOLD:
            print("ALERT: power consumption over threshold!")

        end_exec_time = time.time()
        execution_timestamp = end_exec_time - start_exec_time
        message_timestamp = data["timestamp"]

        # odte timeliness computation
        self._OBSERVATIONS.append(received_timestamp - message_timestamp + execution_timestamp)


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
    odte = DT.compute_odte_phytodig(10, 0.5 ,1)
    prometheus_template = f"odte[pt=\"led_1\"] {str(odte)}".replace("[", "{").replace("]", "}")
    return prometheus_template

@app.route("/receive_status", methods=["POST"])
def handle_update():
    global DT
    data = request.get_json()
    data["received_timestamp"] = time.time()
    data["start_exec_timestamp"] = time.time()
    DT.handle_update(data)
    return {"message": "update received"}, 201

app.run(host='0.0.0.0', port=8001)
