import json
import micropython
import network
import random
import time
import ubinascii
import usocket

from machine import PWM, Pin, Timer, unique_id, I2C, ADC

# micropython-ssd1306
from ssd1306 import SSD1306_I2C
from time import sleep
from umqtt.simple import MQTTClient

# MQTT client settings
client_id: str = "scotty_{0}".format(ubinascii.hexlify(unique_id()).decode())
username: str = "Scotty"
all_client_id: str = "all"  # keyword for all clients
# TODO: Cleanup subs and pubs
topic_pub_list = ["config", "time", "msg", "here", "youThere", "response", "squeeze"]
topic_sub: list = [
    b"lightMsg",
    b"time",
    b"test",
    b"getConfig",
    b"msg",
    b"youThere",
    b"here",
    b"question",
    b"response",
    b"squeeze",
]

# mothership pinout
left_button = Pin(22, Pin.IN, Pin.PULL_UP)
right_button = Pin(20, Pin.IN, Pin.PULL_UP)
select_button = Pin(21, Pin.IN, Pin.PULL_UP)

# encoder pinout
pin_clk = 15
pin_dt = 14
encoder_value = 0
last_clk_state = 0

# SSD1306 OLED screen configuration
i2c = I2C(0, sda=Pin(0), scl=Pin(1), freq=400000)

# User selectable characters
characters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.!@#$%^&*()_-+=[]{};:,<>/? "

tim = Timer()


class OLED:
    def __init__(self, width, height, i2c, rows=3):
        self.oled = SSD1306_I2C(width, height, i2c)
        self.rows = rows
        self.sleep_timer = time.time()
        self.awake = True

    def wake_up(self):
        self.sleep_timer = time.time()
        self.awake = True

    def sleep(self):
        self.clear()
        self.show()
        self.awake = False

    def clear(self):
        self.oled.fill(0)

    def display_text(self, text, y):
        self.oled.text(text, 0, y)

    def display_long_text(self, text):
        self.clear()
        max_chars_per_line = (
            self.oled.width // 8
        )  # Assuming each character is 8 pixels wide
        lines = [
            text[i : i + max_chars_per_line]
            for i in range(0, len(text), max_chars_per_line)
        ]
        num_lines = min(
            len(lines), self.rows
        )  # Limit the number of lines displayed to the available rows

        # Display the lines of text on the OLED screen
        for i in range(num_lines):
            self.display_text(lines[i], i * 10)

        # Display the content on the OLED screen
        self.oled.show()

    def show(self):
        self.oled.show()

    def display_msg(self, username, message):
        self.clear()

        # Format the message with username, and line breaks
        formatted_msg = "{}: {}".format(username, message)
        max_chars_per_line = (
            self.oled.width // 8
        )  # Assuming each character is 8 pixels wide

        # Split the message into lines based on the maximum characters per line
        lines = [
            formatted_msg[i : i + max_chars_per_line]
            for i in range(0, len(formatted_msg), max_chars_per_line)
        ]
        num_lines = min(
            len(lines), self.rows
        )  # Limit the number of lines displayed to the available rows

        # Display the lines of text on the OLED screen
        for i in range(num_lines):
            self.display_text(lines[i], i * 10)

        # Display the content on the OLED screen
        self.oled.show()


class Messages:
    def __init__(self, user_from, message):
        self.user_from = user_from
        self.message = message


class Mothership:
    def __init__(self, oled):
        self.sleep_timer = time.time()


class CharacterSelector:
    def __init__(self, oled, characters):
        self.oled: OLED = oled
        self.characters = characters
        self.y_n = "YN"
        self.selected_index = 0
        self.full_string = ""
        self.left_button = Pin(20, Pin.IN, Pin.PULL_UP)
        self.right_button = Pin(22, Pin.IN, Pin.PULL_UP)
        self.select_button = Pin(21, Pin.IN, Pin.PULL_UP)

    def custom_choice(self, question: str, options):
        selected_index = 0
        show_question = True
        character_count = len(options)

        while True:
            self.oled.clear()
            if show_question:
                self.oled.display_long_text(question)
            if not show_question:
                selected_character = options[selected_index]
                self.oled.display_text("Selection:", 0)
                self.oled.display_text(selected_character, 10)

            self.oled.show()

            if not self.left_button.value():
                if show_question:
                    time.sleep(0.2)
                    show_question = False
                else:
                    selected_index = (selected_index - 1) % character_count
                    time.sleep(0.2)  # Debounce delay

            if not self.right_button.value():
                if show_question:
                    time.sleep(0.2)
                    show_question = False
                else:
                    selected_index = (selected_index + 1) % character_count
                    time.sleep(0.2)  # Debounce delay

            if not self.select_button.value():
                if show_question:
                    time.sleep(0.2)
                    show_question = False
                else:
                    time.sleep(0.2)
                    self.oled.clear()
                    self.oled.show()
                    return options[selected_index]

    def yes(self, title: str):
        self.selected_index = 1
        character_count = len(self.y_n)

        last_encoder_value = get_encoder_value()

        while True:
            self.oled.clear()
            self.oled.display_text(title, 0)

            selected_character = self.y_n[self.selected_index]
            self.oled.display_text(f"Selected: {selected_character}", 10)

            self.oled.show()

            current_encoder_value = get_encoder_value()
            if current_encoder_value != last_encoder_value:
                if current_encoder_value > last_encoder_value:
                    self.selected_index = (self.selected_index + 1) % character_count
                else:
                    self.selected_index = (self.selected_index - 1) % character_count
                last_encoder_value = current_encoder_value

            if not self.left_button.value():
                self.selected_index = (self.selected_index - 1) % character_count
                time.sleep(0.2)  # Debounce delay

            if not self.right_button.value():
                self.selected_index = (self.selected_index + 1) % character_count
                time.sleep(0.2)  # Debounce delay

            if not self.select_button.value():
                selection = False
                if selected_character == "Y":
                    selection = True
                while True:
                    if not self.select_button.value():
                        time.sleep(0.2)
                        self.oled.clear()
                        self.oled.show()
                        return selection

    def cycle_characters(self, title: str):
        self.full_string = ""
        self.selected_index = 0
        character_count = len(self.characters)

        while True:
            self.oled.clear()
            self.oled.display_text(title, 0)

            selected_character = self.characters[self.selected_index]
            self.oled.display_text(f"Selected: {selected_character}", 10)
            self.oled.display_text(self.full_string, 20)

            self.oled.show()

            if not self.left_button.value():
                self.selected_index = (self.selected_index - 1) % character_count
                time.sleep(0.2)  # Debounce delay

            if not self.right_button.value():
                self.selected_index = (self.selected_index + 1) % character_count
                time.sleep(0.2)  # Debounce delay

            if not self.select_button.value():
                start_time = time.ticks_ms()
                while self.select_button.value():
                    if time.ticks_diff(time.ticks_ms(), start_time) >= 1000:
                        while True:
                            if not self.select_button.value():
                                self.oled.clear()
                                self.oled.display_text("Saved!", 0)
                                self.oled.display_text("Let go.", 10)
                                self.oled.show()
                                time.sleep(1)
                                return self.full_string

                self.full_string += selected_character


class Heartbeat(object):
    def __init__(self, client, mothership: Mothership, freq=1):
        self.tick = 0
        self.client = client
        self.tim = Timer()
        self.freq = freq
        self.tim.init(freq=self.freq, mode=Timer.PERIODIC, callback=self.heartbeat_cb)
        self.mothership = mothership

    def publish_config(self):
        publish_message(
            self.client,
            topic="config",
            payload=json.dumps({"test": "testpayload"}),
        )

    def reset_heartbeat(self, frequency=1):
        self.freq = frequency
        print("reset hb with freq of {0}".format(frequency))
        self.tim.deinit()
        self.tim = Timer()
        self.tim.init(freq=frequency, mode=Timer.PERIODIC, callback=self.heartbeat_cb)

    def heartbeat_cb(self, tim):
        self.tick = (self.tick + 1) % 10
        # print("Heartbeat tick {0}".format(self.tick))


class MqttHandler(object):
    """handle the heart beat check message callback, execute led commands and contain the led configuration"""

    def __init__(
        self,
        oled: OLED,
        mothership: Mothership,
        selector: CharacterSelector,
        heart_beat: Heartbeat = None,
    ):
        self.heart_beat = heart_beat
        self.mothership = mothership
        self.oled = oled
        self.selector = selector

    def check_msg(self, topic, msg):
        """Callback trigger from subscription response"""
        try:
            loadedTopic: str = topic.decode()
            loadedJson: dict = json.loads(msg.decode())

            # topic checks
            if loadedTopic == "time":
                if loadedJson["hzMulti"] > 0 and loadedJson["hzMulti"] <= 4:
                    if self.heart_beat is not None:
                        self.heart_beat.reset_heartbeat(frequency=loadedJson["hzMulti"])
            elif loadedTopic == "getConfig":
                # publish the config on the config topic
                if to_me(loadedJson["client_id"]):
                    self.heart_beat.publish_config()
            elif loadedTopic == "question":
                if (
                    to_me(loadedJson["client_id"])
                    and loadedJson["user_from"] != username
                ):
                    self.mothership.add_unread_message(
                        user_from=loadedJson["user_from"],
                        message=loadedJson["question"],
                    )
                    question_response = self.selector.custom_choice(
                        question=loadedJson["question"], options=loadedJson["options"]
                    )
                    publish_message(
                        client=self.heart_beat.client,
                        topic="response",
                        payload={
                            "client_id": loadedJson["user_from"],
                            "user_from": username,
                            "question": loadedJson["question"],
                            "response": question_response,
                        },
                    )
                    self.mothership.unread_messages.pop()
                    self.oled.clear()
                    self.oled.display_text("Response Sent!", 0)
                    self.oled.show()
            elif loadedTopic == "response":
                if to_me(loadedJson["client_id"]):
                    self.mothership.add_unread_message(
                        user_from=loadedJson["user_from"],
                        message=loadedJson["response"],
                    )
                    msg = "Q:{0} R:{1}".format(
                        loadedJson["question"], loadedJson["response"]
                    )
                    self.oled.display_long_text(text=msg)
                    self.oled.show()
                else:
                    print("not to me")
            elif loadedTopic == "test":
                print("test received")
            else:
                print("No defined action for topic '{0}'".format(loadedTopic))
        except KeyError as e:
            print("Key value was not found in response {0}".format(msg.decode()))
        except ValueError as e:
            print("Error in JSON received {0}".format(msg.decode()))
        except TypeError as e:
            print("Unexpected keyword argument {0} {1}".format(msg.decode(), e))


def publish_message(client, topic, payload):
    if topic in topic_pub_list:
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        client.publish(topic, payload)
    else:
        print(
            "Attempted to publish to an unlisted topic. Add '{0}' to publish list.".format(
                topic
            )
        )


def setupEncoder():
    global clk_pin, dt_pin
    clk_pin = Pin(pin_clk, Pin.IN)
    dt_pin = Pin(pin_dt, Pin.IN)
    clk_pin.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=rotary_callback)


def rotary_callback(pin):
    global last_clk_state, encoder_value
    clk_state = clk_pin.value()
    if clk_state != last_clk_state:
        dt_state = dt_pin.value()
        if dt_state != clk_state:
            encoder_value += 1  # Increment value for clockwise rotation
        else:
            encoder_value -= 1  # Decrement value for counter-clockwise rotation
    last_clk_state = clk_state


def get_encoder_value():
    global encoder_value
    return encoder_value


def to_me(client_id_to_check):
    """check who the message was sent to. returns bool of true if the message is for the client"""
    return (
        client_id_to_check == all_client_id
        or client_id_to_check == client_id
        or client_id_to_check == username
    )


def mqtt_connect(check_handler, mqtt_server, username, pw):
    """Connect to MQTT Broker"""
    client = MQTTClient(
        client_id=client_id,
        server=mqtt_server,
        port=1883,
        # TODO: Add username and passwd once mosquitto settings are changed
        # user=username,
        # password=pw,
        ssl=False,
        keepalive=3600,
    )
    print("Connecting to MQTT Broker")
    try:
        client.set_callback(check_handler.check_msg)
        client.connect()
        print("MQTT Broker Connected to {0}".format(mqtt_server))
        return client
    except Exception as e:
        print("MQTT Broker Connection Failed {0} {1}".format(mqtt_server, e))
        sleep(1)
        return None


def connect_to_wlan(ssid, password):
    """Connect to WLAN"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(ssid, password)
    while wlan.isconnected() == False:
        print("Waiting for connection...")
        sleep(1)
    print(wlan.ifconfig())
    return wlan


class MainMenu:
    def __init__(self, oled: OLED):
        self.oled: OLED = oled
        self.menu_options = ["Login", "MTG", "Info"]
        self.selected_index = 0

    def left(self):
        menu_count = len(self.menu_options)
        self.selected_index = (self.selected_index - 1) % menu_count
        self.display_menu()

    def right(self):
        menu_count = len(self.menu_options)
        self.selected_index = (self.selected_index + 1) % menu_count
        self.display_menu()

    def display_menu(self):
        self.oled.clear()
        self.oled.display_text("Mothership", 0)
        self.oled.display_text("----------------", 10)
        selected_option = self.menu_options[self.selected_index]
        self.oled.display_text(selected_option, 20)
        self.oled.show()

    def select_menu_option(self, mqtt_handler: MqttHandler):
        if self.menu_options[self.selected_index] == "Send":
            time.sleep(0.2)
            new_msg = mqtt_handler.selector.yes("New Message?")
            if new_msg:
                users = get_users()
                message = mqtt_handler.selector.cycle_characters("Message:")
                sel_user = ""
                if len(users) > 0:
                    sel_user = mqtt_handler.selector.custom_choice("User:", users)
                else:
                    sel_user = mqtt_handler.selector.cycle_characters("User:")

                publish_message(
                    client=mqtt_handler.heart_beat.client,
                    topic="msg",
                    payload={
                        "client_id": sel_user,
                        "user_from": "{0}".format(username),
                        "message": "{0}".format(message),
                    },
                )
            else:
                messages = get_messages()
                sel_user = ""
                sel_message = ""

                if len(messages) > 0:
                    sel_message = mqtt_handler.selector.custom_choice(
                        "Message:", messages
                    )
                else:
                    sel_message = mqtt_handler.selector.cycle_characters("Message:")
                if len(users) > 0:
                    sel_user = mqtt_handler.selector.custom_choice("User:", users)
                else:
                    sel_user = mqtt_handler.selector.cycle_characters("User:")

                publish_message(
                    client=mqtt_handler.heart_beat.client,
                    topic="msg",
                    payload={
                        "client_id": sel_user,
                        "user_from": "{0}".format(username),
                        "message": "{0}".format(sel_message),
                    },
                )

            self.oled.clear()
            self.oled.display_text("Message", 0)
            self.oled.display_text("Published!", 10)
            self.oled.show()

        elif self.menu_options[self.selected_index] == "Messages":
            mqtt_handler.mothership.display_oldest_message()
            mqtt_handler.mothership.remove_oldest_message()

        elif self.menu_options[self.selected_index] == "Info":
            self.oled.clear()
            self.oled.display_text(username, 0)
            self.oled.display_text(mqtt_handler.heart_beat.client.server, 10)
            self.oled.display_text(ubinascii.hexlify(unique_id()).decode(), 20)
            self.oled.show()


def rotary_callback(pin):
    global last_clk_state, encoder_value
    clk_state = clk_pin.value()
    if clk_state != last_clk_state:
        dt_state = dt_pin.value()
        if dt_state != clk_state:
            encoder_value += 1  # Increment value for clockwise rotation
        else:
            encoder_value -= 1  # Decrement value for counter-clockwise rotation
    last_clk_state = clk_state


def read_random_line(filename):
    with open(filename, "r") as f:
        lines = f.readlines()

    if lines:
        random_line = random.choice(lines).strip()
        return random_line
    else:
        return None


def save_user(usr_to_add):
    with open("users.txt", "a") as f:
        f.write("{0}\n".format(usr_to_add))


def get_messages():
    # Open and read the messages file
    messages = []
    try:
        # Open and read the configuration file
        with open("msg.txt", "r") as f:
            msg_data = f.read()

        # split line the messages
        messages = msg_data.splitlines()
    except Exception as e:
        open("msg.txt", "w").close()
    return messages


def get_config():
    # Open and read the configuration file
    config = {}
    try:
        # Open and read the configuration file
        with open("config.txt", "r") as f:
            config_data = f.read()

        # Parse the configuration data
        config_lines = config_data.splitlines()
        config = {}
        for line in config_lines:
            key, value = line.split("=")
            config[key.strip()] = value.strip()
    except Exception as e:
        config = {
            "username": "X AE A-12",
            "ssid": "ssid",
            "password": "pass",
            "mqtt_server": "mothership.local",
            "mqtt_pass": "pass",
        }
    return config


def main():
    config = get_config()
    print(config)
    username = config["username"]
    ssid = config["ssid"]
    password = config["password"]
    mqtt_server = config["mqtt_server"]
    mqtt_pass = config["mqtt_pass"]

    # sensor reading variables
    previous_readings = []
    num_previous_readings = 50
    last_interaction_time = 0
    debounce_delay = 1000

    # instantiate the screen and clear it
    oled = OLED(128, 32, i2c)
    oled.clear()
    oled.show()

    # instance of the main menu
    main_menu = MainMenu(oled)

    # encoder setup and value
    setupEncoder()
    last_encoder_value = get_encoder_value()
    last_direction = None

    # Set SSID and password if none entered
    selector = CharacterSelector(oled, characters)
    change_config = selector.yes(title="Change Config?")
    if change_config:
        select_ssid = selector.yes(title="Enter New Wifi?")
        if select_ssid:
            ssid = selector.cycle_characters(title="WiFi SSID:")
            config["ssid"] = ssid
            print(ssid)
        select_pass = selector.yes(title="Enter New Pass?")
        if select_pass:
            password = selector.cycle_characters(title="WiFi Pass:")
            config["password"] = password
            print(password)
        select_ip = selector.yes(title="New Server IP?")
        if select_ip:
            mqtt_server = selector.cycle_characters(title="Server IP:")
            config["mqtt_server"] = mqtt_server
            print(mqtt_server)
        select_mqtt_pass = selector.yes(title="New Server Pass?")
        if select_mqtt_pass:
            mqtt_pass = selector.cycle_characters(title="MQTT Pass:")
            config["mqtt_pass"] = mqtt_pass
            print(mqtt_pass)
        reset_config = selector.yes(title="Reset Config?")
        if reset_config:
            open("config.txt", "w").close()
            username = "X AE A-12"
            ssid = "ssid"
            password = "err"
            mqtt_server = "carrot.garden"
            mqtt_pass = "err"
        # Write updated configuration to file
        with open("config.txt", "w") as f:
            for key, value in config.items():
                f.write(f"{key}={value}\n")

    mothership = Mothership(oled)
    mqtt_handler = MqttHandler(oled=oled, mothership=mothership, selector=selector)
    client = None
    wlan = connect_to_wlan(ssid, password)

    # show connecting to ssid on oled
    oled.clear()
    oled.display_text("Connecting to:", 0)
    oled.display_text(ssid, 10)
    oled.show()
    time.sleep(0.2)
    while wlan.isconnected():
        while client is None:
            # show connecting to MQTT server on oled
            oled.clear()
            oled.display_text("Connecting to", 0)
            oled.display_text("MQTT Server:", 10)
            oled.display_text(mqtt_server, 20)
            oled.show()
            time.sleep(0.2)
            # client = mqtt_connect(
            #     check_handler=mqtt_handler,
            #     mqtt_server=mqtt_server,
            #     username=username,
            #     pw=mqtt_pass,
            # )
            client = mqtt_connect(
                check_handler=mqtt_handler, mqtt_server=mqtt_server, username="", pw=""
            )
            if hasattr(client, "sock") and isinstance(client.sock, usocket.socket):
                print("Connection is encrypted with SSL/TLS.")
            else:
                print("Connection is not encrypted.")
            if client:
                # show connected on oled
                oled.clear()
                oled.display_text("Connected!", 0)
                oled.display_text("Mothership Butt", 10)
                oled.display_text("Synced!", 20)
                oled.show()
                time.sleep(1)
                for sub in topic_sub:
                    client.subscribe(sub)
                micropython.alloc_emergency_exception_buf(100)
                # create heartbeat for message queue
                mqtt_handler.heart_beat = Heartbeat(
                    client=client,
                    mothership=mqtt_handler.mothership,
                )
                mqtt_handler.heart_beat.publish_config()
                main_menu.display_menu()
        else:
            try:
                # oled sleep after seconds have passed without button push
                # elapsed_time = time.time() - oled.sleep_timer
                # if elapsed_time >= 20:
                #     oled.sleep()
                # check incoming published messages
                client.check_msg()

                current_encoder_value = get_encoder_value()
                if current_encoder_value != last_encoder_value:
                    direction = (
                        "clockwise"
                        if current_encoder_value > last_encoder_value
                        else "counter-clockwise"
                    )
                    if current_encoder_value > last_encoder_value:
                        main_menu.right()
                    else:
                        main_menu.left()
                    last_encoder_value = current_encoder_value

                if not left_button.value():
                    main_menu.left(mqtt_handler)
                    time.sleep(0.2)  # Debounce delay

                if not right_button.value():
                    main_menu.right(mqtt_handler)
                    time.sleep(0.2)  # Debounce delay

                if not select_button.value():
                    main_menu.select_menu_option(mqtt_handler)
                    time.sleep(0.2)  # Debounce delay

            except OSError as e:
                # broker stopped
                print("Lost connection to {0} {1}".format(mqtt_server, e))
                client = None
            except Exception as e:
                print("Something unexpected went wrong: {0}".format(e))
    else:
        # set password and SSID to empty string to let user enter again without restarting device
        ssid = ""
        password = ""
        main()


if __name__ == "__main__":
    main()
