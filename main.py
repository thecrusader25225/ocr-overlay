import sys
import time
import dxcam
import numpy as np
import cv2
import ctypes
from ctypes import wintypes
from PyQt5.QtCore import QAbstractNativeEventFilter, Qt, QTimer, QRect, QEvent, QPoint
from PyQt5.QtGui import QPainter, QColor, QFont
from paddleocr import PaddleOCR
from deep_translator import GoogleTranslator
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton,
    QListWidget, QColorDialog, QSlider, QLabel, QApplication, QGroupBox, QHBoxLayout
)
from difflib import SequenceMatcher
import psutil
import os
from opencc import OpenCC
cc = OpenCC('t2s')  # Traditional → Simplified

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

model_dir = resource_path("paddleocr")
print("MODEL DIR:", model_dir)
print("CONTENTS:", os.listdir(model_dir))
ocr = PaddleOCR(
    use_angle_cls=True,
    lang='ch',
    show_log=False,
    det_model_dir=os.path.join(model_dir, "det"),
    rec_model_dir=os.path.join(model_dir, "rec"),
    cls_model_dir=os.path.join(model_dir, "cls"),
    download=False 
)
translator = GoogleTranslator(source='auto', target='en')

user32 = ctypes.windll.user32

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

WM_HOTKEY = 0x0312
HOTKEY_ID = 1

camera = dxcam.create()
camera.start(target_fps=5)


cache = {}
detections = []
text_box_heights = {}

stable_texts = {}        # accepted raw text
stable_translations = {} # accepeted translated/region

candidate_texts = {}     # unstable texts 
candidate_counts = {}    # how many consistent frames
prev_regions = {}


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

def normalize_text(t):
    return " ".join(t.split()).strip().lower()

def is_significant_change(a, b, threshold=0.85):
    if not a or not b:
        return True
    return similar(a, b) < threshold

# App
class ControlPanel(QWidget):
    def __init__(self, state, overlay):
        super().__init__()

        self.state = state
        self.overlay = overlay
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.Window
        )

        self.setWindowTitle("OCR Control Panel")
        self.setGeometry(100, 100, 300, 400)

        layout = QVBoxLayout()

        self.region_list = QListWidget()
        layout.addWidget(self.region_list)

        self.hotkey_label = QLabel("Overlay HotKey: Ctrl + 1")
        layout.addWidget(self.hotkey_label)

        btn_delete = QPushButton("Delete Selected Region")
        btn_delete.clicked.connect(self.delete_region)
        layout.addWidget(btn_delete)


        global_box = QGroupBox("Global Parameters")
        global_layout = QVBoxLayout()

        # OCR Interval
        row = QHBoxLayout()
        row.addWidget(QLabel("OCR Interval"))
        row.addStretch()
        self.ocr_value = QLabel(f"{self.state.ocr_interval} ms")
        row.addWidget(self.ocr_value)
        global_layout.addLayout(row)

        self.ocr_slider = QSlider(Qt.Horizontal)
        self.ocr_slider.setRange(100, 2000)
        self.ocr_slider.setValue(self.state.ocr_interval)
        self.ocr_slider.valueChanged.connect(self.update_ocr_interval)
        global_layout.addWidget(self.ocr_slider)

        # Stability Frames
        row = QHBoxLayout()
        row.addWidget(QLabel("Stability Frames"))
        row.addStretch()
        self.stability_value = QLabel(str(self.state.stability_frames))
        row.addWidget(self.stability_value)
        global_layout.addLayout(row)

        self.stability_slider = QSlider(Qt.Horizontal)
        self.stability_slider.setRange(1, 10)
        self.stability_slider.setValue(self.state.stability_frames)
        self.stability_slider.valueChanged.connect(self.update_stability)
        global_layout.addWidget(self.stability_slider)

        # Diff Threshold
        row = QHBoxLayout()
        row.addWidget(QLabel("Diff Threshold"))
        row.addStretch()
        self.diff_value = QLabel(str(self.state.diff_threshold))
        row.addWidget(self.diff_value)
        global_layout.addLayout(row)

        self.diff_slider = QSlider(Qt.Horizontal)
        self.diff_slider.setRange(0, 20)
        self.diff_slider.setValue(self.state.diff_threshold)
        self.diff_slider.valueChanged.connect(self.update_diff)
        global_layout.addWidget(self.diff_slider)

        # Confidence
        row = QHBoxLayout()
        row.addWidget(QLabel("OCR Confidence"))
        row.addStretch()
        self.conf_value = QLabel(f"{self.state.conf_threshold:.2f}")
        row.addWidget(self.conf_value)
        global_layout.addLayout(row)

        self.conf_slider = QSlider(Qt.Horizontal)
        self.conf_slider.setRange(50, 100)
        self.conf_slider.setValue(int(self.state.conf_threshold * 100))
        self.conf_slider.valueChanged.connect(self.update_conf)
        global_layout.addWidget(self.conf_slider)

        global_box.setLayout(global_layout)
        layout.addWidget(global_box)

        region_box = QGroupBox("Per-Region Parameters")
        region_layout = QVBoxLayout()

        # Y Offset
        row = QHBoxLayout()
        row.addWidget(QLabel("Y Offset"))
        row.addStretch()
        self.offset_value = QLabel("0")
        row.addWidget(self.offset_value)
        region_layout.addLayout(row)

        self.offset_slider = QSlider(Qt.Horizontal)
        self.offset_slider.setRange(-200, 200)
        self.offset_slider.valueChanged.connect(self.update_offset)
        region_layout.addWidget(self.offset_slider)

        # X Offset
        row = QHBoxLayout()
        row.addWidget(QLabel("X Offset"))
        row.addStretch()
        self.x_offset_value = QLabel("0")
        row.addWidget(self.x_offset_value)
        region_layout.addLayout(row)

        self.x_offset_slider = QSlider(Qt.Horizontal)
        self.x_offset_slider.setRange(-200, 200)
        self.x_offset_slider.valueChanged.connect(self.update_x_offset)
        region_layout.addWidget(self.x_offset_slider)

        # Color Picker
        btn_color = QPushButton("Pick Background Color")
        btn_color.clicked.connect(self.pick_color)
        region_layout.addWidget(btn_color)

        region_box.setLayout(region_layout)
        layout.addWidget(region_box)
        
        metrics_box = QGroupBox("Runtime Metrics")
        metrics_layout = QVBoxLayout()

        self.cpu_label = QLabel("CPU: 0%")
        self.ocr_label = QLabel("OCR/sec: 0")

        metrics_layout.addWidget(self.cpu_label)
        metrics_layout.addWidget(self.ocr_label)

        metrics_box.setLayout(metrics_layout)
        layout.addWidget(metrics_box)

        self.metrics_timer = QTimer()
        self.metrics_timer.timeout.connect(self.update_metrics)
        self.metrics_timer.start(1000)



        self.setLayout(layout)
        self.region_list.currentRowChanged.connect(self.on_region_selected)

    def update_ocr_interval(self, val):
        self.state.ocr_interval = val
        self.overlay.update_timer()
        self.ocr_value.setText(f"{val} ms")

    def update_stability(self, val):
        self.state.stability_frames = val
        self.stability_value.setText(str(val))

    def update_diff(self, val):
        self.state.diff_threshold = val
        self.diff_value.setText(str(val))

    def update_conf(self, val):
        self.state.conf_threshold = val / 100.0
        self.conf_value.setText(f"{self.state.conf_threshold:.2f}")

    def update_offset(self, val):
        idx = self.region_list.currentRow()
        if 0 <= idx < len(self.state.regions):
            self.state.regions[idx]["offset"] = val
            self.offset_value.setText(str(val))
            self.overlay.update()

    def update_x_offset(self, val):
        idx = self.region_list.currentRow()
        if 0 <= idx < len(self.state.regions):
            self.state.regions[idx]["x_offset"] = val
            self.x_offset_value.setText(str(val))
            self.overlay.update()
            
    def refresh(self):
        self.region_list.clear()
        for i, r in enumerate(self.state.regions):
            x1, y1, x2, y2 = r["coords"]
            w = x2 - x1
            h = y2 - y1
            self.region_list.addItem(f"R{i} | ({x1},{y1}) [{w}x{h}]")

    def on_region_selected(self, idx):
        if idx < 0 or idx >= len(self.state.regions):
            return

        region = self.state.regions[idx]

        self.offset_slider.blockSignals(True)
        self.x_offset_slider.blockSignals(True)

        self.offset_slider.setValue(region.get("offset", 0))
        self.x_offset_slider.setValue(region.get("x_offset", 0))

        self.offset_slider.blockSignals(False)
        self.x_offset_slider.blockSignals(False)

    def delete_region(self):
        idx = self.region_list.currentRow()
        if idx < 0 or idx >= len(self.state.regions):
            return

        del self.state.regions[idx]
        self.state.dirty = True
        self.refresh()
        self.overlay.update()

    def pick_color(self):
        # temporarily lower overlay so dialog is usable
        self.overlay.lower()

        dlg = QColorDialog(self)
        dlg.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dlg.exec()

        self.overlay.raise_()        
        self.raise_()                
        self.activateWindow()        

        if dlg.selectedColor().isValid():
            color = dlg.selectedColor()
            idx = self.region_list.currentRow()
            if idx >= 0:
                self.state.regions[idx]["bg_color"] = (
                    color.red(), color.green(), color.blue(), 200
                )
                self.overlay.update()

    def update_metrics(self):
        cpu = psutil.cpu_percent()
        self.cpu_label.setText(f"CPU: {cpu}%")

        now = time.time()
        elapsed = now - self.overlay.last_ocr_time

        if elapsed > 0:
            ocr_rate = self.overlay.ocr_count / elapsed
            self.ocr_label.setText(f"OCR/sec: {ocr_rate:.2f}")

        self.overlay.ocr_count = 0
        self.overlay.last_ocr_time = now
    
    def closeEvent(self, event):
        if hasattr(self, "overlay"):
            self.overlay.close()

        event.accept()
        os._exit(0)
        

def translate(text):
    key = normalize_text(text)

    if key in cache:
        return cache[key]

    try:
        simplified = cc.convert(text)
        t = translator.translate(simplified)
        cache[key] = t
        return t
    except:
        return text

#Frame change detection
prev_gray = None

class AppState:
    def __init__(self):
        self.regions = []
        self.dirty = True
        self.ocr_interval = 1000
        self.stability_frames = 4
        self.diff_threshold = 2
        self.conf_threshold = 0.85

#Windows Hotkey Event
class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, eventType, message):
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
        except Exception:
            return False, 0

        if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
            self.callback()
            return True, 0

        return False, 0

#Overlay
class Overlay(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.is_editing = False
        self.force_ocr = False

        if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL, 0x31):
            print("Hotkey registration failed")
        else:
            print("Hotkey registered: CTRL + F3")

        self.hotkey_filter = HotkeyFilter(self.toggle_selection_safe)
        QApplication.instance().installNativeEventFilter(self.hotkey_filter)

        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint | Qt.Tool  
        )

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.showFullScreen()
        self.ocr_count = 0
        self.last_ocr_time = time.time()

        self.selecting = True
        self.is_editing = True
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.start_pos = None
        self.current_rect = None
        self.dim_opacity = 120

        self.latest_frame = None
        self.running = True

        self.dragging_region = None
        self.resizing_region = None
        self.drag_offset = None

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_overlay)
        self.timer.start(100)

        self.watch_timer = QTimer()
        self.watch_timer.timeout.connect(self.watch_regions)
        self.watch_timer.start(self.state.ocr_interval) 
        self.last_edit_time = 0
        # Thread(target=self.ocr_loop, daemon=True).start()

    def update_timer(self):
        self.watch_timer.stop()
        self.watch_timer.start(self.state.ocr_interval)
        
    # Toggle Edit mode
    def toggle_selection_safe(self):
        self.selecting = not self.selecting

        self.setAttribute(
            Qt.WA_TransparentForMouseEvents,
            not self.selecting
        )

        self.is_editing = self.selecting
        if self.selecting:
            self.frozen_heights = text_box_heights.copy()
        else:
            self.frozsen_heights = {}
    
        if hasattr(self, "panel"):
            if self.selecting:
                self.panel.show()

                # force reorder
                self.panel.raise_()
                self.panel.activateWindow()

                # slight delay re-raise
                QTimer.singleShot(10, self.panel.raise_)
            else:
                self.panel.hide()

        print("Selection mode:", self.selecting)
        self.update()
    
    # OCR detection
    def run_ocr_once(self):
        global detections

        frame = self.latest_frame
        if frame is None:
            return

        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        new_detections = []

        for idx, region in enumerate(self.state.regions):
            x1, y1, x2, y2 = region["coords"]
            crop = frame[y1:y2, x1:x2]

            if crop is None or crop.size == 0:
                continue

            results = ocr.ocr(crop)
            if results[0] is None:
                continue

            texts = []
            for line in results[0]:
                text, conf = line[1]
                if conf < self.state.conf_threshold:
                    continue
                if text:
                    texts.append(translate(text))

            if texts:
                new_detections.append((" ".join(texts), idx))

        detections = new_detections
        self.update()

    # Update overlay
    def update_overlay(self):
        frame = camera.get_latest_frame()
        if frame is None:
            return

        self.latest_frame = frame
        self.update()

    # Draw bounding boxes
    def paintEvent(self, event):
        painter = QPainter(self)

        # if self.is_editing:
        #     detections.clear()

        if self.selecting:
            painter.setBrush(QColor(0, 0, 0, self.dim_opacity))
            painter.setPen(Qt.NoPen)
            painter.drawRect(self.rect())

        painter.setFont(QFont("Arial", 14))

        for text, idx in detections:
            if idx >= len(self.state.regions):
                continue

            region = self.state.regions[idx]
            x1, y1, x2, y2 = region["coords"]

            box_w = x2 - x1
            padding = 10
            max_width = box_w

            text_rect = painter.boundingRect(
                0, 0,
                max_width,
                1000,
                Qt.TextWordWrap | Qt.TextWrapAnywhere,
                text
            )

            new_height = text_rect.height() + padding * 2
            prev_height = text_box_heights.get(idx, new_height)

            # freeze during edit mode
            new_height = text_rect.height() + padding * 2

            # 🔥 HARD FREEZE
            if self.is_editing:
                box_h = self.frozen_heights.get(idx, text_box_heights.get(idx, new_height))
            else:
                prev_height = text_box_heights.get(idx, new_height)

                if new_height > prev_height:
                    text_box_heights[idx] = new_height
                else:
                    text_box_heights[idx] = int(prev_height * 0.9 + new_height * 0.1)

                box_h = text_box_heights[idx]

            # STEP 2: position
            margin = 10
            y_off = region["offset"]

            if y_off >= 0:
                # BELOW the region
                box_y = y2 + margin + y_off
            else:
                # ABOVE the region
                box_y = y1 - box_h - margin + y_off

            # prevent overlap with OCR region
            if (box_y < y2) and (box_y + box_h > y1):
                if y_off >= 0:
                    box_y = y2 + margin
                else:
                    box_y = y1 - box_h - margin

            box_x = x1 + region["x_offset"]

            r, g, b, a = region["bg_color"]

            painter.save()

            # background
            painter.setBrush(QColor(r, g, b, a))
            painter.setPen(Qt.NoPen)
            painter.drawRect(box_x, box_y, max_width + 2*padding, box_h)

            # resize handle (bottom-right corner)
            if self.selecting:
                handle_size = 10

                hx = x2 - handle_size
                hy = y2 - handle_size

                painter.setBrush(QColor(0, 255, 0))
                painter.setPen(Qt.NoPen)

                # triangle indicator
                points = [
                    (x2, y2),
                    (hx, y2),
                    (x2, hy)
                ]

                painter.drawPolygon(
                    QPoint(points[0][0], points[0][1]),
                    QPoint(points[1][0], points[1][1]),
                    QPoint(points[2][0], points[2][1])
                )

            # 🔥 draw text using drawText(rect), NOT boundingRect again
            text_draw_rect = QRect(
                box_x + padding,
                box_y + padding,
                max_width,
                box_h - 2*padding
            )

            painter.setPen(QColor(0, 0, 0))
            painter.drawText(text_draw_rect, Qt.TextWordWrap | Qt.TextWrapAnywhere, text)

            painter.restore()

        for region in self.state.regions:
            painter.save()
            painter.setPen(QColor(0, 255, 0))
            painter.setBrush(Qt.NoBrush)

            x1, y1, x2, y2 = region["coords"]
            painter.drawRect(x1, y1, x2 - x1, y2 - y1)

            painter.restore()
            
        if self.current_rect:
            p1, p2 = self.current_rect
            painter.setPen(QColor(255, 0, 0))
            painter.drawRect(
                p1.x(), p1.y(),
                p2.x() - p1.x(),
                p2.y() - p1.y()
            )

    # When mouse pressed
    def mousePressEvent(self, event):
        if not self.selecting:
            return

        pos = event.pos()
        self.is_editing= True

        for i, region in enumerate(self.state.regions):
            x1, y1, x2, y2 = region["coords"]

            # RESIZE (bottom-right corner)
            if abs(pos.x() - x2) < 10 and abs(pos.y() - y2) < 10:
                self.resizing_region = i
                return

            # MOVE (inside box) 
            if x1 <= pos.x() <= x2 and y1 <= pos.y() <= y2:
                self.dragging_region = i
                self.drag_offset = (pos.x() - x1, pos.y() - y1)
                return

        # NEW REGION 
        self.start_pos = pos

    def mouseMoveEvent(self, event):
        
        self.last_edit_time = time.time() 
        pos = event.pos()

        if self.selecting:
            cursor_set = False

            for region in self.state.regions:
                x1, y1, x2, y2 = region["coords"]

                # resize zone
                if abs(pos.x() - x2) < 10 and abs(pos.y() - y2) < 10:
                    self.setCursor(Qt.SizeFDiagCursor)
                    cursor_set = True
                    break

                # inside region
                if x1 <= pos.x() <= x2 and y1 <= pos.y() <= y2:
                    self.setCursor(Qt.SizeAllCursor)
                    cursor_set = True
                    break

            if not cursor_set:
                self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        
        if not self.selecting:
            return
        # MOVE REGION
        if self.dragging_region is not None:
            region = self.state.regions[self.dragging_region]
            x1, y1, x2, y2 = region["coords"]

            dx, dy = self.drag_offset
            new_x1 = pos.x() - dx
            new_y1 = pos.y() - dy

            w = x2 - x1
            h = y2 - y1

            screen_w = self.width()
            screen_h = self.height()

            nx1 = max(0, min(new_x1, screen_w - w))
            ny1 = max(0, min(new_y1, screen_h - h))

            region["coords"] = (
                nx1,
                ny1,
                nx1 + w,
                ny1 + h
            )

            self.state.dirty = True
            self.update()
            return
        # RESIZE REGION
        if self.resizing_region is not None:
            region = self.state.regions[self.resizing_region]
            x1, y1, _, _ = region["coords"]

            x2 = pos.x()
            y2 = pos.y()

            # normalize
            nx1 = min(x1, x2)
            ny1 = min(y1, y2)
            nx2 = max(x1, x2)
            ny2 = max(y1, y2)

            # clamp to screen
            screen_w = self.width()
            screen_h = self.height()

            nx1 = max(0, min(nx1, screen_w))
            ny1 = max(0, min(ny1, screen_h))
            nx2 = max(0, min(nx2, screen_w))
            ny2 = max(0, min(ny2, screen_h))

            # enforce minimum size
            min_size = 20
            if (nx2 - nx1) < min_size:
                nx2 = nx1 + min_size
            if (ny2 - ny1) < min_size:
                ny2 = ny1 + min_size

            region["coords"] = (nx1, ny1, nx2, ny2)

            self.state.dirty = True
            self.update()
            return
        # NEW REGION DRAW 
        if self.start_pos:
            self.current_rect = (self.start_pos, pos)
            self.update()

    def mouseReleaseEvent(self, event):
        if not self.selecting:
            return
        self.is_editing = False
        # FINISH MOVE / RESIZE 
        if self.dragging_region is not None:
            self.dragging_region = None
            return

        if self.resizing_region is not None:
            self.resizing_region = None
            return

        #  CREATE NEW REGION
        if self.start_pos:
            end = event.pos()

            x1 = min(self.start_pos.x(), end.x())
            y1 = min(self.start_pos.y(), end.y())
            x2 = max(self.start_pos.x(), end.x())
            y2 = max(self.start_pos.y(), end.y())

            self.state.regions.append({
                "coords": (x1, y1, x2, y2),
                "offset": 0,
                "x_offset": 0,
                "bg_color": (255, 255, 255, 200),
                "enabled": True
            })
            self.state.dirty = True
            if hasattr(self, "panel"):
                self.panel.refresh()

        self.start_pos = None
        self.current_rect = None
        self.update()

    def event(self, event):
        if event.type() == QEvent.WindowActivate:
            if hasattr(self, "panel"):
                self.panel.raise_()
                self.panel.activateWindow()
            return True

        return super().event(event)

    # Exit
    def closeEvent(self, event):
        # unregister hotkey
        user32.UnregisterHotKey(None, HOTKEY_ID)

        # 🔥 REMOVE native event filter (CRITICAL)
        QApplication.instance().removeNativeEventFilter(self.hotkey_filter)

        # stop timers
        self.timer.stop()
        self.watch_timer.stop()

        # stop camera
        camera.stop()

        # close panel too (important)
        if hasattr(self, "panel"):
            self.panel.close()

        event.accept()

    def watch_regions(self):
        if self.is_editing:
            return

        if time.time() - self.last_edit_time < 0.5:
            return

        frame = self.latest_frame
        if frame is None:
            return

        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        global detections

        new_detections = []

        for idx, region in enumerate(self.state.regions):
            coords = region["coords"]
            prev_coords = prev_regions.get(idx)

            geometry_changed = (coords != prev_coords)
            prev_regions[idx] = coords

            x1, y1, x2, y2 = region["coords"]
            crop = frame[y1:y2, x1:x2]

            if crop is None or crop.size == 0:
                continue
            results = ocr.ocr(crop)
            self.ocr_count += 1
            if results[0] is None:
                continue

            texts = []
            for line in results[0]:
                text, conf = line[1]

                if conf < self.state.conf_threshold:
                    continue

                if text:
                    texts.append(text)

            if not texts:
                continue

            raw = normalize_text(" ".join(texts))

           # Stabilize detection
            prev_candidate = candidate_texts.get(idx)

            if raw == prev_candidate:
                candidate_counts[idx] = candidate_counts.get(idx, 0) + 1
            else:
                candidate_texts[idx] = raw
                candidate_counts[idx] = 1

            # Require stability across frames
            if not geometry_changed:
                if candidate_counts[idx] < self.state.stability_frames:
                    if idx in stable_translations:
                        new_detections.append((stable_translations[idx], idx))
                    continue

            prev_stable = stable_texts.get(idx, "")

            if not geometry_changed:
                if not is_significant_change(raw, prev_stable):
                    if idx in stable_translations:
                        new_detections.append((stable_translations[idx], idx))
                    continue

            # Accept new text
            stable_texts[idx] = raw

            translated = translate(raw)
            stable_translations[idx] = translated

            new_detections.append((translated, idx))

        # update once per cycle
        if new_detections:
            detections = new_detections
            self.update()

# Run
app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(True)
state = AppState()

overlay = Overlay(state)
panel = ControlPanel(state, overlay)

overlay.panel = panel
panel.overlay = overlay

overlay.show()
panel.show()

sys.exit(app.exec_())