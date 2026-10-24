#!/usr/bin/env python3

from gpiozero import PWMOutputDevice
from time import sleep

SERVO_GPIO = 13
PWM_HZ = 50

PULSE_NEUTRAL_US = 1500
PULSE_SPAN_US = 500

# Retract speed: -1.0 = full reverse
RETRACT_SPEED = -1.0

# How long to retract
RETRACT_TIME_S = 5

servo = PWMOutputDevice(
    SERVO_GPIO,
    frequency=PWM_HZ,
    initial_value=0
)

def set_servo(speed):
    pulse_us = PULSE_NEUTRAL_US + (speed * PULSE_SPAN_US)
    duty = (pulse_us / 1_000_000) * PWM_HZ
    servo.value = duty

try:
    print("Retracting drill...")

    set_servo(RETRACT_SPEED)
    sleep(RETRACT_TIME_S)

    set_servo(0)
    print("Retract complete.")

finally:
    servo.close()