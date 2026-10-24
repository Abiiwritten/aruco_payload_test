"""
camera_view.py - Shows simple_stream.py's output on the Enviro+ LCD.

Subscribes to the same telemetry stream the ground station uses (on the Pi
itself, tcp://127.0.0.1:5555), so aq.py never touches the OAK-D. Each message
carries a clean JPEG plus the ArUco + model results for that exact frame;
this draws both onto an LCD-sized image with overlay.render().

Cost on the Pi: the receiving thread only stores the latest message. JPEG
decoding and drawing happen in get_frame(), i.e. only while the camera page
is shown. The JPEG is decoded at 1/4 resolution, which is plenty for 160x80.
"""
import json
import threading
import time

import cv2
import numpy as np
import zmq

from overlay import render


class CameraView:
    def __init__(self, size, address="tcp://127.0.0.1:5555", stale_after_s=3.0):
        self.width, self.height = size
        self.address = address
        self.stale_after_s = stale_after_s

        self._lock = threading.Lock()
        self._latest = None        # (msg_id, payload_bytes, jpeg_bytes)
        self._last_rx = 0.0
        self._msg_id = 0

        self._cached_id = None     # avoid re-drawing the same frame
        self._cached_frame = None

    def start(self):
        threading.Thread(target=self._run, name="camera-view", daemon=True).start()

    def get_frame(self):
        """Returns (rgb_image, None) or (None, short status text for the LCD)."""
        with self._lock:
            latest, last_rx = self._latest, self._last_rx

        if latest is None:
            return None, "No camera"
        if time.time() - last_rx > self.stale_after_s:
            return None, "Cam stopped"

        msg_id, payload, jpeg = latest
        if msg_id == self._cached_id:
            return self._cached_frame, None

        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_REDUCED_COLOR_4)
        if frame is None:
            return self._cached_frame, None
        result = json.loads(payload).get("result")
        lcd = render(frame, result, self.width, self.height)   # rescales coords to the 1/4 frame
        self._cached_frame = cv2.cvtColor(lcd, cv2.COLOR_BGR2RGB)
        self._cached_id = msg_id
        return self._cached_frame, None

    def _run(self):
        sock = zmq.Context.instance().socket(zmq.SUB)
        sock.setsockopt(zmq.RCVHWM, 2)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.SUBSCRIBE, b"detections")
        sock.connect(self.address)   # reconnects automatically if simple_stream restarts

        while True:
            try:
                parts = sock.recv_multipart()
            except zmq.ZMQError:
                time.sleep(0.5)
                continue
            if len(parts) != 3:
                continue
            with self._lock:
                self._last_rx = time.time()
                if parts[2]:   # only messages that carry an image are drawable
                    self._msg_id += 1
                    self._latest = (self._msg_id, parts[1], parts[2])