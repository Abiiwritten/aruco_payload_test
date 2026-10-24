"""
overlay.py - Draws detections onto a frame. Shared by the Pi (LCD) and the
ground station (web stream).

Works on the plain JSON-style result dict (FrameResult.to_dict()), so the
ground station needs only OpenCV + NumPy, not DepthAI.
"""
import cv2
import numpy as np

YOLO_COLOUR = (0, 255, 0)      # BGR green
ARUCO_COLOUR = (255, 255, 0)   # BGR cyan
AXIS_COLOURS = [(0, 0, 255), (0, 255, 0), (255, 0, 0)]  # X red, Y green, Z blue
FONT = cv2.FONT_HERSHEY_SIMPLEX


def _pt(p):
    return int(round(float(p[0]))), int(round(float(p[1])))


def render(frame, result, out_w, out_h):
    """Return a BGR image of size (out_w, out_h): the frame downscaled
    (aspect kept, letterboxed) with detections drawn on it.

    `frame` is never modified. `result` may be None (plain resize).
    Detection coordinates are in result["frame_size"] pixels; they are rescaled
    if `frame` has a different resolution.
    """
    fh, fw = frame.shape[:2]
    scale = min(out_w / fw, out_h / fh)
    nw, nh = int(round(fw * scale)), int(round(fh * scale))
    small = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)

    if result:
        src_w = result.get("frame_size", [fw, fh])[0]
        s = scale * (fw / src_w)  # detection pixels -> output pixels

        thick = max(1, int(round(out_w / 640)))
        fscale = max(0.3, out_w / 1600)
        min_text_y = int(22 * fscale) + 1

        for obj in result.get("objects", []):
            x1, y1, x2, y2 = (v * s for v in obj["bbox_px"])
            cv2.rectangle(small, _pt((x1, y1)), _pt((x2, y2)), YOLO_COLOUR, thick)
            cv2.putText(
                small, f"{obj['label']} {obj['confidence'] * 100:.0f}%",
                _pt((x1 + 1, max(y1 - 3, min_text_y))), FONT, fscale, YOLO_COLOUR, thick, cv2.LINE_AA,
            )

        for m in result.get("markers", []):
            pts = np.round(np.asarray(m["corners_px"], dtype=np.float32) * s).astype(np.int32)
            cv2.polylines(small, [pts], True, ARUCO_COLOUR, thick)

            if m.get("axis_px"):
                axis = np.asarray(m["axis_px"], dtype=np.float32) * s
                origin = _pt(axis[0])
                for end, colour in zip(axis[1:], AXIS_COLOURS):
                    cv2.line(small, origin, _pt(end), colour, thick)

            text = f"id{m['id']}"
            if m.get("distance_m") is not None:
                text += f" {m['distance_m']:.2f}m"
            tx, ty = _pt(pts[0])
            cv2.putText(small, text, (tx, max(ty - 3, min_text_y)), FONT, fscale, ARUCO_COLOUR, thick, cv2.LINE_AA)

    if (nw, nh) == (out_w, out_h):
        return small
    canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)
    ox, oy = (out_w - nw) // 2, (out_h - nh) // 2
    canvas[oy:oy + nh, ox:ox + nw] = small
    return canvas