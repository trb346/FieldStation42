import json
import logging
import time
import os
import sys
import subprocess
import re
import urllib.request
import urllib.error

from gpiozero import Button
import tm1637

_l = logging.getLogger("CABLEBOX")

PINOUT_FILE = "runtime/cable_box.json"

DEFAULT_PINOUT = {
    "buttons": {
        "center": 16,     # Pin 36 (CENTER # - Guide/Home)
        "tune_up": 20,    # Pin 38 (TUNE ▲ - Channel Up)
        "tune_down": 26,  # Pin 37 (TUNE ▼ - Channel Down)
        "select_up": 19,  # Pin 35 (SELECT + - Volume Up)
        "select_down": 13 # Pin 33 (SELECT - - Volume Down)
    },
    "display": {"clk": 17, "dio": 18},
}


def load_pinout():
    pinout = dict(DEFAULT_PINOUT)
    if os.path.exists(PINOUT_FILE):
        _l.info(f"Loading pinout from {PINOUT_FILE}")
        try:
            with open(PINOUT_FILE) as fp:
                overrides = json.load(fp)
            for section in ("buttons", "display"):
                if section in overrides:
                    pinout[section] = overrides[section]
        except Exception as e:
            _l.error(f"Error loading pinout from {PINOUT_FILE}, using defaults: {e}")
            pinout = dict(DEFAULT_PINOUT)
    return pinout


def get_temperature():
    a = str(subprocess.check_output(["vcgencmd", "measure_temp"]))
    _l.debug(f"Temperature reading: {a}")
    b = a.split("=")[1]
    c = float(b.split("'")[0])
    f = round((c * 1.8) + 32)
    return f


def channel_label(num):
    return f"CH{num:02d}"


def volume_label(vol_val):
    """Formats volume level for TM1637 display showing ONLY numbers right-aligned (e.g., '  30' or ' 100')."""
    try:
        clean_val = int(re.sub(r"[^\d]", "", str(vol_val)))
        return f"{clean_val:4d}"
    except (ValueError, TypeError):
        return "    "


class CableBox:
    def __init__(self, channel_socket="runtime/channel.socket", status_socket="runtime/play_status.socket", press_socket="runtime/press.socket"):
        self.channel_socket = channel_socket
        self.status_socket = status_socket
        self.press_socket = press_socket

        pinout = load_pinout()

        # Display setup
        self.tm = tm1637.TM1637(clk=pinout["display"]["clk"], dio=pinout["display"]["dio"])
        self.tm.brightness(0)
        self.tm.show("FS42")

        # Initialize gpiozero Buttons with internal pull-ups
        btn_config = pinout["buttons"]
        self.buttons = {}
        for action, pin_num in btn_config.items():
            self.buttons[action] = Button(pin_num, pull_up=True)

        self.last_channel = None
        self.last_play_state = None
        self.temp_mode = False
        self.last_button_time = time.monotonic()

        self.show_time = True
        self.time_format = "%I:%M"
        try:
            with open("confs/main_config.json") as fp:
                config = json.load(fp)
                self.show_time = config.get("show_cable_box_time", True)
                self.time_format = config.get("time_format", "%I:%M")
        except Exception:
            pass

    def send_volume_post(self, action):
        """Sends HTTP POST to player API and returns the volume percentage."""
        endpoints = [
            f"http://localhost:4242/player/volume/{action}",
            f"http://localhost:4242/api/player/volume/{action}"
        ]
        
        for url in endpoints:
            try:
                req = urllib.request.Request(
                    url, 
                    data=b"", 
                    headers={"Content-Type": "application/json", "User-Agent": "CableBox-GPIO"}
                )
                with urllib.request.urlopen(req, timeout=1) as resp:
                    if resp.status == 200:
                        body = resp.read().decode("utf-8")
                        data = json.loads(body)
                        vol = data.get("volume")
                        _l.info(f"Volume {action} success: volume={vol}")
                        return vol
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    continue
                _l.error(f"HTTP Error {e.code} for {url}")
            except Exception as e:
                _l.error(f"Failed POST to {url}: {e}")
                
        _l.error(f"Could not reach working volume endpoint for '{action}'")
        return None

    def send_guide_post(self):
        """Sends HTTP POST to trigger channel guide matching remote button behavior."""
        endpoints = [
            "http://localhost:4242/player/channels/guide",
            "http://localhost:4242/api/player/channels/guide"
        ]
        for url in endpoints:
            try:
                req = urllib.request.Request(
                    url,
                    data=b"",
                    headers={"Content-Type": "application/json", "User-Agent": "CableBox-GPIO"}
                )
                with urllib.request.urlopen(req, timeout=1) as resp:
                    if resp.status == 200:
                        _l.info(f"Guide command POST success via {url}")
                        return True
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    continue
                _l.error(f"HTTP Error {e.code} for {url}")
            except Exception as e:
                _l.error(f"Failed POST to {url}: {e}")

        _l.error("Could not reach working guide endpoint")
        return False

    def send_command(self, command, channel=-1):
        as_obj = {"command": command, "channel": channel}
        as_str = json.dumps(as_obj)

        if command == "direct" and channel == 99:
            os.system("pkill -SIGINT -f field_player.py")
            sys.exit(0)
        elif command == "direct" and channel == 97:
            self.temp_mode = True
        elif command == "vol_up":
            _l.info("Sending Volume Up POST request...")
            return self.send_volume_post("up")
        elif command == "vol_down":
            _l.info("Sending Volume Down POST request...")
            return self.send_volume_post("down")
        elif command == "guide":
            _l.info("Sending Guide POST request...")
            return self.send_guide_post()
        else:
            _l.info(f"Sending command: {as_str}")
            with open(self.channel_socket, "w") as fp:
                fp.write(as_str)
            return None

    def check_status(self):
        try:
            with open(self.status_socket) as fp:
                as_str = fp.read().strip()
                if not as_str:
                    return None

                data = json.loads(as_str)
                current_chan = data.get("channel_number")
                current_state = data.get("status")

                if current_chan != self.last_channel or current_state != self.last_play_state:
                    _l.info(f"Status changed: channel={current_chan}, state={current_state}")
                    self.last_channel = current_chan
                    self.last_play_state = current_state
                    return data
        except Exception:
            pass
        return None

    def check_press(self):
        try:
            with open(self.press_socket) as fp:
                as_str = fp.read().strip()
            if not as_str:
                return None
            data = json.loads(as_str)
            with open(self.press_socket, "w") as fp:
                fp.write("")
            if time.time() - data["ts"] < 2.0:
                return data["digits"]
        except Exception:
            pass
        return None

    def read_keys(self):
        for action, btn in self.buttons.items():
            if btn.is_pressed:
                _l.info(f"Hardware input on BCM Pin {btn.pin.number} -> Action: {action}")
                return action
        return None

    def event_loop(self):
        last_pressed = ""
        in_selection = False
        last_selection_tick = -1
        channel_num = 0
        tick_count = 0

        while True:
            key_pressed = self.read_keys()

            if key_pressed:
                self.temp_mode = False
                self.last_button_time = time.monotonic()

                if key_pressed == "tune_up":
                    self.send_command("up")
                    channel_num += 1
                    self.tm.show("----")
                    in_selection = False

                elif key_pressed == "tune_down":
                    if channel_num > 0:
                        self.send_command("down")
                        channel_num -= 1
                        self.tm.show("----")
                    in_selection = False

                elif key_pressed == "select_up":
                    _l.info("Volume Up requested")
                    vol = self.send_command("vol_up")
                    if vol is not None:
                        self.tm.show(volume_label(vol))
                    in_selection = False

                elif key_pressed == "select_down":
                    _l.info("Volume Down requested")
                    vol = self.send_command("vol_down")
                    if vol is not None:
                        self.tm.show(volume_label(vol))
                    in_selection = False

                elif key_pressed == "center":
                    _l.info("Center button pressed. Requesting Channel Guide...")
                    self.send_command("guide")
                    self.tm.show("LIST")
                    in_selection = False

                time.sleep(0.3)

            time.sleep(0.1)

            if not in_selection:
                remote_digits = self.check_press()
                if remote_digits:
                    self.last_button_time = time.monotonic()
                    self.tm.show(channel_label(int(remote_digits)))

            new_stat = self.check_status()
            if new_stat:
                self.temp_mode = False
                try:
                    new_channel_num = int(new_stat["channel_number"])
                    if new_channel_num != channel_num:
                        self.last_button_time = time.monotonic()
                        channel_num = new_channel_num
                    if channel_num >= 0:
                        self.tm.show(channel_label(channel_num))
                        _l.info(f"Set channel: {channel_num}")
                    else:
                        self.tm.show("FS42")
                except Exception:
                    self.tm.show("FS42")

            elapsed_since_press = time.monotonic() - self.last_button_time
            if self.show_time and elapsed_since_press > 15 and not in_selection and (tick_count % 10) == 0:
                formatted = time.strftime(self.time_format, time.localtime())
                if formatted.startswith("0"):
                    formatted = " " + formatted[1:]

                if ":" in formatted:
                    h, m = formatted.split(":", 1)
                    self.tm.numbers(int(h), int(m))
                else:
                    self.tm.show(formatted)
            elif self.temp_mode and (tick_count % 10) == 0:
                temp = get_temperature()
                self.tm.show(f"{temp}*")

            tick_count += 1


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s %(levelname)s:%(name)s:%(message)s", level=logging.INFO)
    cable_box = CableBox()
    try:
        cable_box.event_loop()
    except KeyboardInterrupt:
        _l.info("Shutting down cable box control...")
    finally:
        for btn in cable_box.buttons.values():
            btn.close()
        _l.info("GPIO pins cleanly released.")
