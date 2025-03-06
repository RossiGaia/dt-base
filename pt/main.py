from flask import Flask
from enum import Enum
import random, time, threading, json, requests, os

app = Flask(__name__)

DT_URL = os.environ("DT_URL")
if DT_URL is None:
    print("No DT URL specified.")
    exit(1)

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

@app.route("/toggle", methods=["POST"])
def toggle():
    global led
    led.toggle()
    return json.dumps({
        "message": "LED toggled",
        "new_state": led.get_state().name
        })


def send_to_dt_thread():
    global led
    headers = {
        "content-type": "application/json"
    }

    while True:
        data = {
            "state": led.get_state().name,
            "power_consumption": led.get_power_consumption(),
            "timestamp": time.time()
        }

        try:
            resp = requests.post(DT_URL, data=json.dumps(data), headers=headers)
            if resp.status_code == 201:
                print(f"Message sent: {data}")
            time.sleep(1)
        except Exception as e:
            print(f"Errore nella richiesta: {e}")
        

def toggle_thread():
    global led
    while True:
        wait_time = random.randint(5, 30)
        time.sleep(wait_time)
        led.toggle()

if __name__ == "__main__":
    toggle_t = threading.Thread(target=toggle_thread, daemon=True)
    toggle_t.start()

    send_to_dt_t = threading.Thread(target=send_to_dt_thread, daemon=True)
    send_to_dt_t.start()

    app.run(host='0.0.0.0', port=8000)