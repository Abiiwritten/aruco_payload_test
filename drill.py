#!/usr/bin/env python3
"""
Drill actuation module (ENC & DM subsystem).

The asynchronous drill script that advances the drill down for one full 
stroke, dwells at depth, then retracts back up to home.
"""

import atexit
import threading
import time

from gpiozero import PWMOutputDevice

# ---------------------------------------------------------------- CONSTANTS
SERVO_GPIO       = 13
PWM_HZ           = 50
PULSE_NEUTRAL_US = 1500
PULSE_SPAN_US    = 500

LEAD_MM_PER_REV = 1
STROKE_MM       = 21  # Target stroke length
S_PER_REV       = 0.63

DWELL_S     = 0.1   # Time between advancing and retracting (e.g. at_depth)
POLL_S      = 0.05  # How often to poll the thread
TIMEOUT_S   = 30.0  # Timeout till module gives up if cant communicate with servo
COOLDOWN_S  = 30.0  # Ignore future calls for cooldown 

STROKE_TIME_S = (STROKE_MM / LEAD_MM_PER_REV) * S_PER_REV

# ------------------------------------------------------------------- STATES
IDLE = "IDLE"
ADVANCING = "ADVANCING"
AT_DEPTH = "AT_DEPTH"
RETRACTING = "RETRACTING"

# --------------------------------------------------------- MODULE VARIABLES
_state = IDLE
_ready_at = 0.0  # monotonic time the next call is allowed
_thread = None
_lock = threading.Lock()

servo = PWMOutputDevice(SERVO_GPIO, frequency=PWM_HZ, initial_value=0)


# Single choke point for the GPIO, so nothing else in the module touches hardware.
def _set_servo(speed):
    pulse_us = PULSE_NEUTRAL_US + (speed * PULSE_SPAN_US)
    servo.value = (pulse_us / 1_000_000) * PWM_HZ


# The full cycle, on the worker thread: down, dwell, up.
def _cycle():
    global _state, _ready_at
    deadline = time.monotonic() + TIMEOUT_S
    try:
        for step, speed, hold_s in ((ADVANCING, +1.0, STROKE_TIME_S),
                                    (AT_DEPTH, 0.0, DWELL_S),
                                    (RETRACTING, -1.0, STROKE_TIME_S)):
            _state = step
            _set_servo(speed)
            end = time.monotonic() + hold_s
            while time.monotonic() < end:
                if time.monotonic() > deadline:
                    return
                time.sleep(POLL_S)
    finally:
        _set_servo(0)
        _ready_at = time.monotonic() + COOLDOWN_S
        _state = IDLE


# The only function TAIP calls to drill. Returns immediately; a call made while
# a cycle is running, or during the cooldown that follows it, is ignored.
def drill_sample():
    global _thread
    with _lock:
        if (_thread is not None and _thread.is_alive()) or time.monotonic() < _ready_at:
            return
        _thread = threading.Thread(target=_cycle, daemon=True)
        _thread.start()


# Passive status query for WVIS, which does the logging.
def get_state():
    return _state


# Runs on a clean interpreter exit, so the servo is never left driving.
@atexit.register
def _on_exit():
    _set_servo(0)
    servo.close()


# Bench test: fire one cycle and poll the state the way WVIS will.
if __name__ == "__main__":
    drill_sample()
    while _thread.is_alive():
        print(f"{time.monotonic():.1f} {get_state()}")
        time.sleep(1.0)
    print(f"{time.monotonic():.1f} {get_state()}")
