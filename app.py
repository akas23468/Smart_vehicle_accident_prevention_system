from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import base64
import cv2
import numpy as np
import mysql.connector
from ultralytics import YOLO
from twilio.rest import Client

app = Flask(__name__)
CORS(app)

# 🔹 MySQL Connection (XAMPP)
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="vision_ai"
)
cursor = db.cursor()

# Load YOLOv8 Nano
model = YOLO("yolov8n.pt")

# ---------------- CONFIG ----------------
MAX_TRIGGER_DISTANCE = 10
CRITICAL_DISTANCE = 3
WARNING_DISTANCE = 5
VEHICLE_CLASSES = ["car", "bus", "truck", "motorcycle", "bicycle"]

# ----------- TWILIO CONFIG -----------
ACCOUNT_SID = "YOUR_SID"
AUTH_TOKEN = "YOUR_TOKEN"
client = Client(ACCOUNT_SID, AUTH_TOKEN)

# ---------------- ROUTES ----------------

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/control")
def control():
    return render_template("index1.html")

@app.route("/dros")
def dros():
    return render_template("dros.html")

# ---------------- AUTH ----------------

@app.route("/register", methods=["POST"])
def register():
    data = request.json

    vehicle = data.get("vehicle")
    driver = data.get("driver")
    phone = data.get("phone")
    password = data.get("password")

    cursor.execute("SELECT * FROM users WHERE vehicle=%s", (vehicle,))
    if cursor.fetchone():
        return jsonify({"status": "exists"})

    cursor.execute(
        "INSERT INTO users (vehicle, driver, phone, password) VALUES (%s,%s,%s,%s)",
        (vehicle, driver, phone, password)
    )
    db.commit()

    return jsonify({"status": "success"})


@app.route("/login", methods=["POST"])
def login():
    data = request.json

    vehicle = data.get("vehicle")
    password = data.get("password")

    cursor.execute(
        "SELECT * FROM users WHERE vehicle=%s AND password=%s",
        (vehicle, password)
    )

    if cursor.fetchone():
        return jsonify({"status": "success"})
    else:
        return jsonify({"status": "fail"})


@app.route("/reset", methods=["POST"])
def reset():
    data = request.json

    phone = data.get("phone")
    password = data.get("password")

    cursor.execute(
        "UPDATE users SET password=%s WHERE phone=%s",
        (password, phone)
    )
    db.commit()

    if cursor.rowcount > 0:
        return jsonify({"status": "success"})
    else:
        return jsonify({"status": "notfound"})

# ---------------- AI FUNCTIONS ----------------

def decode_frame(b64_string):
    try:
        data = b64_string.split(",")[1]
        img_bytes = base64.b64decode(data)
        np_array = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(np_array, cv2.IMREAD_COLOR)
        return frame
    except:
        return None


def estimate_distance(box_height):
    if box_height <= 0:
        return 999
    return round(800 / box_height, 2)


# ---------------- SOS ----------------

@app.route("/api/sos", methods=["POST"])
def send_sos():
    try:
        data = request.json or {}

        lat = data.get("lat")
        lon = data.get("lon")

        link = f"https://maps.google.com/?q={lat},{lon}"

        client.messages.create(
            body=f"🚨 ACCIDENT ALERT!\nLocation: {link}",
            from_="+17193261327",
            to="+91XXXXXXXXXX"
        )

        return jsonify({"status": "sent"})

    except Exception as e:
        print(e)
        return jsonify({"status": "error"})


# ---------------- AI RISK ----------------

@app.route("/api/risk-check", methods=["POST"])
def risk_check():

    payload = request.json
    if not payload or "frame" not in payload:
        return jsonify({"error": "No frame"}), 400

    frame = decode_frame(payload["frame"])
    if frame is None:
        return jsonify({"error": "Invalid frame"}), 400

    results = model(frame, conf=0.3, imgsz=640, verbose=False)[0]

    risk_score = 0
    is_hazard = False
    instruction = "Road Clear"
    voice_response = "The road ahead is clear."
    nearest_distance = None
    detected_vehicle = None

    if results.boxes:
        for box in results.boxes:

            cls_id = int(box.cls[0])
            label = model.names[cls_id]

            if label not in VEHICLE_CLASSES:
                continue

            coords = box.xyxy[0]
            box_height = float(coords[3] - coords[1])
            distance = estimate_distance(box_height)

            if nearest_distance is None or distance < nearest_distance:
                nearest_distance = distance
                detected_vehicle = label

            if distance > MAX_TRIGGER_DISTANCE:
                continue

            if distance <= CRITICAL_DISTANCE:
                return jsonify({
                    "risk_score": 95,
                    "is_hazard": True,
                    "instruction": "IMMEDIATE HAZARD! BRAKE!",
                    "voice_response": "Brake immediately!"
                })

            elif distance <= WARNING_DISTANCE:
                risk_score = 70
                instruction = "OBJECT TOO CLOSE"
                voice_response = "Vehicle too close."

            else:
                risk_score = 40
                instruction = "CAUTION"
                voice_response = "Maintain distance."

    return jsonify({
        "risk_score": risk_score,
        "is_hazard": is_hazard,
        "instruction": instruction,
        "voice_response": voice_response,
        "distance_m": nearest_distance,
        "vehicle_type": detected_vehicle
    })


# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
