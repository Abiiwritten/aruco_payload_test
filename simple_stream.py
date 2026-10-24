#!/usr/bin/env python3
"""
simple_stream.py - The original ArUco + YOLO script, adapted to stream to the
ground-station web server (gcs_server.py) instead of showing cv2.imshow windows.

Changes from the original:
  * no cv2.imshow / drawing on the Pi - the ground station draws both feeds
    onto one image from the detection data
  * no NN passthrough stream (less USB traffic)
  * the OAK-D's hardware encoder makes the JPEG that is sent (no Pi CPU)
  * lower camera rate, rate-limited model and 1 inference thread (power)
  * results go out with telemetry.py in the same format as camera_feed.py,
    so gcs_server.py works unchanged

Run on the Pi (telemetry.py and models/ alongside):  python3 simple_stream.py
Then on the laptop:                                  py gcs_server.py --pi <pi-ip>
"""
import json
import os
import time
import logging
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from drill import drill_sample  
from drill import get_state
import cv2
import depthai as dai
import numpy as np
import threading

from telemetry import TelemetryPublisher

# --- Model configuration ---
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
BLOB_PATH = SCRIPT_DIR / "models" / "best.blob"
CONFIG_PATH = SCRIPT_DIR / "models" / "config_v2_latest.json"
SENSOR_JSON_PATH = "/tmp/enviroplus_sensors.json"

with open(CONFIG_PATH) as f:
    config = json.load(f)

nn_config = config["nn_config"]
nn_meta = nn_config["NN_specific_metadata"]
LABELS = config["mappings"]["labels"]
NN_W = nn_config["input_size_width"]    # 640
NN_H = nn_config["input_size_height"]   # 640

# --- ArUco configuration ---
ARUCO_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
ARUCO_PARAMS = cv2.aruco.DetectorParameters()
MARKER_LENGTH_M = 0.200  # 200mm x 200mm markers

ARUCO_RES = (1920, 1080)
CAMERA_SOCKET = dai.CameraBoardSocket.CAM_A  # OAK-D Lite's RGB camera

# --- Load / streaming settings ---
CAMERA_FPS = 10            # was 30
NN_FPS = 1                 # model runs on ~this many frames/s (None = every frame)
NN_INFERENCE_THREADS = 1   # was 2; 1 lowers peak power draw
STREAM_FPS = 5             # images/s sent to the ground station
JPEG_QUALITY = 70
TELEMETRY_PORT = 5555
cv2.setNumThreads(2)       # leave CPU cores free for the rest of the Pi

# Marker object points (centered at origin, Z=0), used with solvePnP.
# Order matches cv2.aruco corner order: top-left, top-right, bottom-right, bottom-left.
_half = MARKER_LENGTH_M / 2
OBJ_POINTS = np.array([
    [-_half,  _half, 0],
    [ _half,  _half, 0],
    [ _half, -_half, 0],
    [-_half, -_half, 0],
], dtype=np.float32)

# Pose axes (origin, X, Y, Z) - projected here, drawn by the ground station.
_axis = MARKER_LENGTH_M * 0.5
AXIS_POINTS = np.array([[0, 0, 0], [_axis, 0, 0], [0, _axis, 0], [0, 0, _axis]], dtype=np.float32)


def build_pipeline():
    pipeline = dai.Pipeline()

    # RGB camera: 1080p video stream for ArUco, 640x640 preview for the NN.
    cam = pipeline.create(dai.node.ColorCamera)
    cam.setBoardSocket(CAMERA_SOCKET)
    cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
    cam.setVideoSize(*ARUCO_RES)
    cam.setPreviewSize(NN_W, NN_H)
    cam.setInterleaved(False)
    cam.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)
    cam.setFps(CAMERA_FPS)

    # YOLO detection network, configured from the v2 JSON.
    nn = pipeline.create(dai.node.YoloDetectionNetwork)
    nn.setBlobPath(str(BLOB_PATH))
    nn.setNumClasses(nn_meta["classes"])
    nn.setCoordinateSize(nn_meta["coordinates"])
    nn.setAnchors(nn_meta["anchors"])
    nn.setAnchorMasks(nn_meta["anchor_masks"])
    nn.setIouThreshold(nn_meta["iou_threshold"])
    nn.setConfidenceThreshold(nn_meta["confidence_threshold"])
    nn.setNumInferenceThreads(NN_INFERENCE_THREADS)
    nn.setNumNCEPerInferenceThread(1)
    nn.input.setBlocking(False)
    nn.input.setQueueSize(1)

    if NN_FPS and NN_FPS < CAMERA_FPS:
        # Frame skipper running on the OAK-D: only every Nth preview frame
        # reaches the model.
        skip = max(1, round(CAMERA_FPS / NN_FPS))
        gate = pipeline.create(dai.node.Script)
        gate.setScript(f"""
n = 0
while True:
    frame = node.io['in'].get()
    if n % {skip} == 0:
        node.io['out'].send(frame)
    n += 1
""")
        gate.inputs['in'].setBlocking(False)
        gate.inputs['in'].setQueueSize(1)
        cam.preview.link(gate.inputs['in'])
        gate.outputs['out'].link(nn.input)
    else:
        cam.preview.link(nn.input)

    # Hardware JPEG encoder (same frames as the 1080p video stream).
    encoder = pipeline.create(dai.node.VideoEncoder)
    encoder.setDefaultProfilePreset(CAMERA_FPS, dai.VideoEncoderProperties.Profile.MJPEG)
    encoder.setQuality(JPEG_QUALITY)
    cam.video.link(encoder.input)

    # Outputs to host.
    xout_video = pipeline.create(dai.node.XLinkOut)
    xout_video.setStreamName("video")
    cam.video.link(xout_video.input)

    xout_jpeg = pipeline.create(dai.node.XLinkOut)
    xout_jpeg.setStreamName("jpeg")
    encoder.bitstream.link(xout_jpeg.input)

    xout_det = pipeline.create(dai.node.XLinkOut)
    xout_det.setStreamName("detections")
    nn.out.link(xout_det.input)

    return pipeline


def yolo_to_dicts(detections, w, h):
    """YOLO boxes in full-frame pixels.

    The 640x640 preview is a centre crop of the 1080p frame, so the normalised
    coordinates go through that crop. (The original drew them on the 640 crop
    itself; here both feeds share the 1080p frame's coordinates.)
    """
    crop = min(w, h)
    x0, y0 = (w - crop) / 2, (h - crop) / 2
    objects = []
    for det in detections:
        label = LABELS[det.label] if det.label < len(LABELS) else str(det.label)
        objects.append({
            "label": label,
            "confidence": round(float(det.confidence), 3),
            "bbox_px": [
                round(x0 + float(np.clip(det.xmin, 0, 1)) * crop, 1),
                round(y0 + float(np.clip(det.ymin, 0, 1)) * crop, 1),
                round(x0 + float(np.clip(det.xmax, 0, 1)) * crop, 1),
                round(y0 + float(np.clip(det.ymax, 0, 1)) * crop, 1),
            ],
        })
    return objects


def process_aruco(frame, detector, camera_matrix, dist_coeffs):
    """Same detection + pose as the original, but returns data instead of drawing."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detector.detectMarkers(gray)

    markers = []
    if ids is None:
        return markers

    for marker_corners, marker_id in zip(corners, ids.flatten()):
        pts = marker_corners[0]
        center_px = pts.mean(axis=0)
        marker = {
            "id": int(marker_id),
            "corners_px": [[round(float(x), 1), round(float(y), 1)] for x, y in pts],
            "center_px": [round(float(center_px[0])), round(float(center_px[1]))],
            "distance_m": None, "position_m": None, "rvec_deg": None, "axis_px": None,
        }

        ok, rvec, tvec = cv2.solvePnP(OBJ_POINTS, pts, camera_matrix, dist_coeffs)
        if ok:
            axis_px, _ = cv2.projectPoints(AXIS_POINTS, rvec, tvec, camera_matrix, dist_coeffs)
            distance_m = float(np.linalg.norm(tvec))
            x, y, z = tvec.flatten()
            rot_deg = np.degrees(rvec.flatten())  # axis-angle in degrees, not Euler angles
            marker.update({
                "distance_m": round(distance_m, 3),
                "position_m": [round(float(x), 3), round(float(y), 3), round(float(z), 3)],
                "rvec_deg": [round(float(v), 1) for v in rot_deg],
                "axis_px": [[round(float(px), 1), round(float(py), 1)] for px, py in axis_px.reshape(-1, 2)],
            })
            print(
                f"[ArUco] id={marker_id} "
                f"dist={distance_m:.3f}m "
                f"pos(x,y,z)=({x:.3f}, {y:.3f}, {z:.3f})m "
                f"rot(x,y,z)=({rot_deg[0]:.1f}, {rot_deg[1]:.1f}, {rot_deg[2]:.1f})deg "
                f"pixel_center=({center_px[0]:.0f}, {center_px[1]:.0f})",
                flush=True,
            )

        markers.append(marker)
    return markers

def box_center(det):
    return (
        (det.xmin + det.xmax) / 2.0,
        (det.ymin + det.ymax) / 2.0
    )

import math


def calculate_gauge_value(detections):
    base = None
    tip = None

    for det in detections:
        label = LABELS[det.label]

        if label == "Base":
            base = box_center(det)

        elif label == "Tip":
            tip = box_center(det)

    if base is None or tip is None:
        return None

    dx = tip[0] - base[0]
    dy = tip[1] - base[1]

    angle = math.degrees(math.atan2(dy, dx))

    if angle < 0:
        angle += 360.0

    return gauge_angle_to_value(angle)

GAUGE_MIN = 0.0
GAUGE_MAX = 10.0
GAUGE_UNITS = "bar"

ZERO_ANGLE = 135.0
MAX_ANGLE = 45.0

def gauge_angle_to_value(angle):
    total_sweep = (MAX_ANGLE - ZERO_ANGLE) % 360
    needle_sweep = (angle - ZERO_ANGLE) % 360

    # Needle outside calibrated gauge range
    if needle_sweep > total_sweep:
        return None

    fraction = needle_sweep / total_sweep

    value = GAUGE_MIN + fraction * (GAUGE_MAX - GAUGE_MIN)

    return round(value, 2)

# AQ data
def get_sensor_data():
    """Read the latest Enviro+ sensor readings."""

    try:
        with open(SENSOR_JSON_PATH, "r") as f:
            sensor_data = json.load(f)

        return sensor_data

    except FileNotFoundError:
        logging.warning("Sensor data file not found")
        return None

    except json.JSONDecodeError:
        logging.warning("Sensor data file contains invalid JSON")
        return None

    except OSError as e:
        logging.warning(f"Could not read sensor data: {e}")
        return None



def main():
    telemetry = TelemetryPublisher(port=TELEMETRY_PORT)
    pipeline = build_pipeline()
    aruco_detector = cv2.aruco.ArucoDetector(ARUCO_DICT, ARUCO_PARAMS)
    FLAG = 1
    print("Starting device...")
    with dai.Device(pipeline) as device:
        # Intrinsics at the ArUco resolution, for solvePnP.
        calib = device.readCalibration()
        camera_matrix = np.array(
            calib.getCameraIntrinsics(CAMERA_SOCKET, ARUCO_RES[0], ARUCO_RES[1])
        )
        dist_coeffs = np.array(calib.getDistortionCoefficients(CAMERA_SOCKET))

        q_video = device.getOutputQueue("video", maxSize=1, blocking=False)
        q_jpeg = device.getOutputQueue("jpeg", maxSize=30, blocking=False)
        q_det = device.getOutputQueue("detections", maxSize=1, blocking=False)

        detections = []
        jpegs = OrderedDict()      # frame sequence number -> encoded packet
        last_stream = 0.0
        fps, fps_t0, fps_n = 0.0, time.time(), 0

        print(f"Running - streaming on tcp://*:{TELEMETRY_PORT}. Ctrl+C to quit.")
        while True:
            in_det = q_det.tryGet()
            if in_det is not None:
                detections = in_det.detections

            for pkt in q_jpeg.tryGetAll():
                jpegs[pkt.getSequenceNum()] = pkt
            while len(jpegs) > 15:
                jpegs.popitem(last=False)

            in_video = q_video.tryGet()
            if in_video is None:
                time.sleep(0.01)
                continue

            seq = in_video.getSequenceNum()
            frame = in_video.getCvFrame()  # NV12 -> BGR, never drawn on
            h, w = frame.shape[:2]

            gauge_value = calculate_gauge_value(detections)

            if (gauge_value is not None) and (gauge_value < 2):
                drill_sample()

            sensor_data = get_sensor_data()
            
            # Both detections, combined into one result for this frame.
            now = time.time()
            result = {
                "seq": seq,
                "timestamp": now,
                "time_iso": datetime.fromtimestamp(now).isoformat(timespec="milliseconds"),
                "frame_size": [w, h],
                "objects": yolo_to_dicts(detections, w, h),
                "gauge": {
                    "value": gauge_value,
                    "units": GAUGE_UNITS,
                    "valid": gauge_value is not None,
                },
                "sensors": sensor_data,
                "markers": process_aruco(frame, aruco_detector, camera_matrix, dist_coeffs),
                "drill_state": get_state()
            }

            

            # Attach the encoded copy of this exact frame, rate-limited.
            jpeg = b""
            if now - last_stream >= 1.0 / STREAM_FPS:
                for pkt in q_jpeg.tryGetAll():
                    jpegs[pkt.getSequenceNum()] = pkt
                pkt = jpegs.get(seq)
                if pkt is not None:
                    jpeg = pkt.getData().tobytes()
                    last_stream = now

            telemetry.send("detections", {
                "camera_status": "Camera ready",
                "fps": round(fps, 1),
                "result": result,
            }, jpeg)

            fps_n += 1
            if time.time() - fps_t0 >= 1.0:
                fps = fps_n / (time.time() - fps_t0)
                fps_t0, fps_n = time.time(), 0


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass