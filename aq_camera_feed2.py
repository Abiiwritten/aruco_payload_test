#!/usr/bin/env python3

import subprocess

import colorsys

import os

import sys

import time

import json

import logging

import st7735

try:

    # Transitional fix for breaking change in LTR559

    from ltr559 import LTR559

    ltr559 = LTR559()

except ImportError:

    import ltr559

from bme280 import BME280

from fonts.ttf import RobotoMedium as UserFont

from PIL import Image, ImageDraw, ImageFont

from enviroplus import gas

from camera_view import CameraView

# ==================================================

# LOGGING

# ==================================================

logging.basicConfig(
    format="%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s",

    level=logging.INFO,

    datefmt="%Y-%m-%d %H:%M:%S"
)

logging.info("""all-in-one.py - Displays readings from all of Enviro plus' sensors

Press Ctrl+C to exit!

""")

# ==================================================

# SENSOR DATA FILE

# ==================================================

#

# aq_camera_feed.py writes the latest sensor readings here.

# simple_stream.py will later read this file.

#

# /tmp is used because this is temporary runtime data and avoids

# unnecessary writes to the SD card.

# ==================================================

SENSOR_JSON_PATH = "/tmp/enviroplus_sensors.json"

def save_sensor_data(sensor_data):

    """

    Save the latest sensor readings as JSON.

    Data is first written to a temporary file and then atomically

    replaced so another process cannot read a partially-written file.

    """

    temp_path = SENSOR_JSON_PATH + ".tmp"

    try:

        with open(temp_path, "w") as f:

            json.dump(sensor_data, f)

        os.replace(temp_path, SENSOR_JSON_PATH)

    except Exception as e:

        logging.warning(f"Could not save sensor data: {e}")

# ==================================================

# ENVIRO+ SENSOR

# ==================================================

# BME280 temperature/pressure/humidity sensor

bme280 = BME280()

R0_OX = 5576.91
R0_RED = 321769.26
R0_NH3 = 84498.93

OX_A = 0.15584472696778884
OX_B = 0.00014966326713867877

RED_A = -296.9066418267897
RED_B = 1010.592525687529

NH3_A = -72.85980672289692
NH3_B = 203.17677193785747

# ==================================================

# LCD DISPLAY

# ==================================================

# Create ST7735 LCD display class

st7735 = st7735.ST7735(
    port=0,

    cs=1,

    dc="GPIO9",

    backlight="GPIO12",

    rotation=270,

    spi_speed_hz=10000000
)

# Initialize display

st7735.begin()

WIDTH = st7735.width

HEIGHT = st7735.height

# ==================================================

# CANVAS AND FONT

# ==================================================

img = Image.new("RGB", (WIDTH, HEIGHT), color=(0, 0, 0))

draw = ImageDraw.Draw(img)

path = os.path.dirname(os.path.realpath(__file__))

font_size = 20

font = ImageFont.truetype(UserFont, font_size)

message = ""

# The position of the top bar

top_pos = 25

# ==================================================

# CAMERA VIEW

# ==================================================

#

# Camera page (mode 8): shows simple_stream.py's frames

# with the ArUco markers and model boxes drawn on.

#

# simple_stream.py runs as its own program and owns the OAK-D.

# This only listens to its stream on the Pi:

#

# tcp://127.0.0.1:5555

# ==================================================

camera_view = CameraView((WIDTH, HEIGHT))

camera_view.start()

# ==================================================

# LCD FUNCTIONS

# ==================================================

# Displays data and text on the 0.96" LCD

def display_text(variable, data, unit):

    # Maintain length of list

    values[variable] = values[variable][1:] + [data]

    # Scale the values for the variable between 0 and 1

    vmin = min(values[variable])

    vmax = max(values[variable])

    colours = [

        (v - vmin + 1) / (vmax - vmin + 1)

        for v in values[variable]

    ]

    # Format the variable name and value

    message = f"{variable[:4]}: {data:.1f} {unit}"

    logging.info(message)

    draw.rectangle(
        (0, 0, WIDTH, HEIGHT),

        (255, 255, 255)
    )

    for i in range(len(colours)):

        # Convert the values to colours from red to blue

        colour = (1.0 - colours[i]) * 0.6

        r, g, b = [

            int(x * 255.0)

            for x in colorsys.hsv_to_rgb(
                colour,

                1.0,

                1.0
            )

        ]

        # Draw a 1-pixel wide rectangle of colour

        draw.rectangle(
            (i, top_pos, i + 1, HEIGHT),

            (r, g, b)
        )

        # Draw a line graph in black

        line_y = (
            HEIGHT

            - (top_pos + (colours[i] * (HEIGHT - top_pos)))

            + top_pos
        )

        draw.rectangle(
            (i, line_y, i + 1, line_y + 1),

            (0, 0, 0)
        )

    # Write the text at the top in black

    draw.text(
        (0, 0),

        message,

        font=font,

        fill=(0, 0, 0)
    )

    st7735.display(img)

# ==================================================

# IP DISPLAY

# ==================================================

def display_ip(ip):

    draw.rectangle(
        (0, 0, WIDTH, HEIGHT),

        (255, 255, 255)
    )

    draw.text(
        (5, 20),

        "IP Address:",

        font=font,

        fill=(0, 0, 0)
    )

    draw.text(
        (5, 50),

        ip,

        font=font,

        fill=(0, 0, 0)
    )

    st7735.display(img)

# ==================================================

# CAMERA DISPLAY

# ==================================================

def display_camera():

    frame, status = camera_view.get_frame()

    if frame is None:

        # simple_stream.py not running yet, or stopped

        draw.rectangle(
            (0, 0, WIDTH, HEIGHT),

            (0, 0, 0)
        )

        draw.text(
            (5, 30),

            status,

            font=font,

            fill=(255, 255, 255)
        )

        st7735.display(img)

        return

    st7735.display(
        Image.fromarray(frame)
    )

# ==================================================

# IP ADDRESS

# ==================================================

def get_ip_address():

    try:

        ip = subprocess.check_output(
            ["hostname", "-I"],

            text=True
        ).strip().split()[0]

        return ip

    except (
        subprocess.CalledProcessError,

        IndexError
    ):

        return "No IP address"

# ==================================================

# DISPLAY SETTINGS

# ==================================================

delay = 0.5

# The starting mode:

# python3 aq_camera_feed.py 8

# starts on the camera page.

mode = int(sys.argv[1]) if len(sys.argv) > 1 else 0

last_page = 0

# ==================================================

# DISPLAY VARIABLES

# ==================================================

variables = [

    "temperature",

    "pressure",

    "humidity",

    "light",

    "oxidised",

    "reduced",

    "nh3",

    "ip",

    "camera"

]

values = {}

for v in variables:

    values[v] = [1] * WIDTH

# ==================================================

# MAIN LOOP

# ==================================================

try:

    while True:

        # ------------------------------------------

        # Proximity sensor

        # ------------------------------------------

        proximity = ltr559.get_proximity()

        # ------------------------------------------
        # Read ambient temperature
        # ------------------------------------------

        temperature = bme280.get_temperature()

        # ------------------------------------------

        # Read pressure

        # ------------------------------------------

        pressure = bme280.get_pressure()

        # ------------------------------------------

        # Read humidity

        # ------------------------------------------

        humidity = bme280.get_humidity()

        # ------------------------------------------

        # Read light

        # ------------------------------------------

        if proximity < 10:

            light = ltr559.get_lux()

        else:

            light = 1

        # ------------------------------------------

        # Read gas sensors

        # ------------------------------------------

        #

        # Read once and use the same reading for

        # oxidising, reducing and NH3.

        # ------------------------------------------

        gas_data = gas.read_all()

        ox_ratio = gas_data.oxidising / R0_OX

        red_ratio = gas_data.reducing / R0_RED

        nh3_ratio = gas_data.nh3 / R0_NH3

        oxidised = (OX_A * ox_ratio) + OX_B

        reduced = (RED_A * red_ratio) + RED_B

        nh3 = (NH3_A * nh3_ratio) + NH3_B

        # ------------------------------------------

        # Build sensor JSON data

        # ------------------------------------------

        sensor_data = {

            "timestamp": time.time(),

            "temperature": {

                "value": round(temperature, 2),

                "units": "°C"

            },

            "pressure": {

                "value": round(pressure, 2),

                "units": "hPa"

            },

            "humidity": {

                "value": round(humidity, 2),

                "units": "%"

            },

            "light": {

                "value": round(light, 2),

                "units": "Lux"

            },

            "oxidised": {

                "value": round(oxidised, 2),

                "units": "ppm"

            },

            "reduced": {

                "value": round(reduced, 2),

                "units": "ppm"

            },

            "nh3": {

                "value": round(nh3, 2),

                "units": "ppm"

            }

        }

        # ------------------------------------------

        # Save latest sensor readings

        # ------------------------------------------

        save_sensor_data(sensor_data)

        # ------------------------------------------

        # Change LCD page

        # ------------------------------------------

        if (
            proximity > 1500

            and time.time() - last_page > delay
        ):

            mode += 1

            mode %= len(variables)

            last_page = time.time()

        # ------------------------------------------

        # Temperature page

        # ------------------------------------------

        if mode == 0:

            display_text(
                variables[mode],

                temperature,

                "°C"
            )

        # ------------------------------------------

        # Pressure page

        # ------------------------------------------

        if mode == 1:

            display_text(
                variables[mode],

                pressure,

                "hPa"
            )

        # ------------------------------------------

        # Humidity page

        # ------------------------------------------

        if mode == 2:

            display_text(
                variables[mode],

                humidity,

                "%"
            )

        # ------------------------------------------

        # Light page

        # ------------------------------------------

        if mode == 3:

            display_text(
                variables[mode],

                light,

                "Lux"
            )

        # ------------------------------------------

        # Oxidising gas page

        # ------------------------------------------

        if mode == 4:

            display_text(
                variables[mode],

                oxidised,

                "ppm"
            )

        # ------------------------------------------

        # Reducing gas page

        # ------------------------------------------

        if mode == 5:

            display_text(
                variables[mode],

                reduced,

                "ppm"
            )

        # ------------------------------------------

        # NH3 page

        # ------------------------------------------

        if mode == 6:

            display_text(
                variables[mode],

                nh3,

                "ppm"
            )

        # ------------------------------------------

        # IP address page

        # ------------------------------------------

        if mode == 7:

            ip = get_ip_address()

            display_ip(ip)

        # ------------------------------------------

        # Camera page

        # ------------------------------------------

        if mode == 8:

            display_camera()

        # ------------------------------------------

        # Pace loop

        # ------------------------------------------

        #

        # Without this the loop spins as fast as

        # possible and unnecessarily uses a CPU core.

        # ------------------------------------------

        time.sleep(0.1)

# ==================================================

# EXIT

# ==================================================

except KeyboardInterrupt:

    camera_view.stop()

    sys.exit(0)
