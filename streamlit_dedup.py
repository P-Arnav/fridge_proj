"""
streamlit_dedup.py — Multi-camera detection + deduplication with Streamlit UI.

Usage:
    streamlit run streamlit_dedup.py

Install:
    pip install streamlit torch torchvision transformers pillow opencv-python
"""

import colorsys
from collections import defaultdict, Counter

import cv2
import numpy as np
import streamlit as st
import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import models, transforms
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection

MODEL_ID = "IDEA-Research/grounding-dino-base"

DEFAULT_ITEMS = (
    "milk . eggs . apple . orange . banana . yogurt . cheese . butter . "
    "cream . juice . water . soda . chicken . beef . fish . carrot . "
    "tomato . lettuce . broccoli . onion . potato . garlic . pepper . "
    "strawberry . grape . lemon . bread . leftovers . container . bottle . "
    "jar . can . sauce . condiment . spice . powder . chocolate . snack ."
)

EMBED_TRANSFORM = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])

# Category mapping for adding to FridgeAI backend
CATEGORY_MAP = {
    "milk": "dairy", "yogurt": "dairy", "cheese": "dairy", "butter": "dairy",
    "cream": "dairy",
    "chicken": "meat", "beef": "meat",
    "fish": "fish",
    "eggs": "protein",
    "apple": "fruit", "orange": "fruit", "banana": "fruit", "strawberry": "fruit",
    "grape": "fruit", "lemon": "fruit",
    "carrot": "vegetable", "tomato": "vegetable", "lettuce": "vegetable",
    "broccoli": "vegetable", "onion": "vegetable", "potato": "vegetable",
    "garlic": "vegetable", "pepper": "vegetable",
    "juice": "beverage", "water": "beverage", "soda": "beverage",
    "bread": "cooked", "leftovers": "cooked", "chocolate": "cooked",
    "snack": "cooked",
}


# ── Model loading (cached across reruns) ─────────────────────────────────────

@st.cache_resource(show_spinner="Loading Grounding DINO model...")
def load_detector():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(MODEL_ID).to(device)
    return processor, model, device


@st.cache_resource(show_spinner="Loading feature extractor...")
def load_feature_extractor(_device):
    net = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)
    net.classifier = torch.nn.Identity()
    net.eval().to(_device)
    return net


# ── Detection & deduplication ────────────────────────────────────────────────

def detect_items(pil_image, processor, model, device, items_text, threshold):
    inputs = processor(images=pil_image, text=items_text, return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs)
    results = processor.post_process_grounded_object_detection(
        outputs, inputs.input_ids,
        threshold=threshold, text_threshold=threshold,
        target_sizes=[pil_image.size[::-1]],
    )[0]
    return results["boxes"].cpu().tolist(), results["scores"].cpu().tolist(), results["labels"]


def extract_embedding(crop_pil, extractor, device):
    tensor = EMBED_TRANSFORM(crop_pil).unsqueeze(0).to(device)
    with torch.no_grad():
        emb = extractor(tensor).squeeze()
    return F.normalize(emb, dim=0)


def deduplicate(all_detections, extractor, device, sim_threshold):
    by_label = defaultdict(list)
    for cam_id, label, score, crop in all_detections:
        emb = extract_embedding(crop, extractor, device)
        by_label[label].append({"cam": cam_id, "score": score, "emb": emb})

    results = {}
    for label, detections in by_label.items():
        clusters = []
        for det in detections:
            matched = False
            for cluster in clusters:
                centroid = torch.stack([d["emb"] for d in cluster]).mean(dim=0)
                centroid = F.normalize(centroid, dim=0)
                sim = torch.dot(det["emb"], centroid).item()
                if sim >= sim_threshold:
                    cluster.append(det)
                    matched = True
                    break
            if not matched:
                clusters.append([det])

        results[label] = {
            "count": len(clusters),
            "best_confidence": round(max(d["score"] for d in detections), 3),
            "cam_sources": sorted(set(d["cam"] for d in detections)),
            "raw_detections": len(detections),
        }
    return results


def draw_boxes(pil_image, boxes, scores, labels):
    """Draw bounding boxes on a PIL image. Returns annotated PIL image."""
    img = np.array(pil_image).copy()
    colors = {}
    for box, score, label in zip(boxes, scores, labels):
        x1, y1, x2, y2 = (int(v) for v in box)
        if label not in colors:
            h = hash(label) % 179
            r, g, b = (int(c * 255) for c in colorsys.hsv_to_rgb(h / 179, 0.85, 0.95))
            colors[label] = (r, g, b)
        color = colors[label]
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        text = f"{label}  {score:.2f}"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(img, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(img, text, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return Image.fromarray(img)


# ── Capture from USB cameras ─────────────────────────────────────────────────

def capture_from_cameras(cam_indices):
    """Capture one frame from each camera. Returns dict of {index: PIL image}."""
    import time
    frames = {}
    # Open all cameras first so they start initializing in parallel
    caps = []
    for idx in cam_indices:
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)  # auto exposure
        caps.append((idx, cap))

    # Let all cameras warm up together
    time.sleep(1.0)

    # Discard 30 frames per camera to let auto-exposure settle
    for _ in range(30):
        for idx, cap in caps:
            cap.read()

    time.sleep(0.5)

    # Capture final frame from each
    for idx, cap in caps:
        ret, frame = cap.read()
        cap.release()
        if ret:
            frames[idx] = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    return frames


# ── Streamlit UI ─────────────────────────────────────────────────────────────

st.set_page_config(page_title="FridgeAI — Multi-Camera Detection", layout="wide")
st.title("FridgeAI — Multi-Camera Detection & Dedup")

# Sidebar settings
with st.sidebar:
    st.header("Settings")
    cam_indices = st.multiselect(
        "Camera indices", options=[0, 1, 2, 3, 4], default=[0, 2]
    )
    det_threshold = st.slider("Detection threshold", 0.5, 1.0, 0.5, 0.05)
    sim_threshold = st.slider("Dedup similarity threshold", 0.5, 1.0, 0.85, 0.05)
    backend_url = st.text_input(
        "Backend URL (to add items)",
        value="https://fridgeai-backend-964175866795.us-central1.run.app",
    )
    auth_token = st.text_input("Auth token (from login)", type="password", key="auth_token_input")
    if auth_token:
        st.session_state["auth_token"] = auth_token

    st.markdown("---")
    st.caption("Lower similarity → more aggressive dedup")
    st.caption("Higher detection → fewer false positives")

# Initialize session state
if "results" not in st.session_state:
    st.session_state.results = None
if "annotated_frames" not in st.session_state:
    st.session_state.annotated_frames = {}
if "raw_frames" not in st.session_state:
    st.session_state.raw_frames = {}

# ── Input: camera capture or file upload ─────────────────────────────────────
st.subheader("Input")

input_mode = st.radio("Source", ["USB Cameras", "Upload Images"], horizontal=True)

images = {}

if input_mode == "USB Cameras":
    if st.button("Capture from all cameras", type="primary"):
        with st.spinner(f"Capturing from cameras {cam_indices}..."):
            images = capture_from_cameras(cam_indices)
        if not images:
            st.error("No cameras could be opened. Check indices in sidebar.")
        else:
            st.success(f"Captured from {len(images)} camera(s)")
            st.session_state.raw_frames = images
    elif st.session_state.raw_frames:
        images = st.session_state.raw_frames
else:
    uploaded = st.file_uploader(
        "Upload images (one per camera view)", type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
    )
    if uploaded:
        for i, f in enumerate(uploaded):
            images[i] = Image.open(f).convert("RGB")

# Show input frames
if images:
    cols = st.columns(len(images))
    for col, (idx, img) in zip(cols, images.items()):
        col.image(img, caption=f"Camera {idx}", use_container_width=True)

# ── Detection ────────────────────────────────────────────────────────────────
st.subheader("Detection & Deduplication")

if images and st.button("Detect & Deduplicate", type="primary"):
    processor, dino, device = load_detector()
    extractor = load_feature_extractor(device)
    items_text = DEFAULT_ITEMS

    all_detections = []
    annotated_frames = {}
    progress = st.progress(0, text="Detecting...")

    for i, (idx, pil) in enumerate(images.items()):
        progress.progress((i + 1) / (len(images) + 1), text=f"Detecting on camera {idx}...")
        boxes, scores, labels = detect_items(pil, processor, dino, device, items_text, det_threshold)
        w, h = pil.size

        if labels:
            annotated_frames[idx] = draw_boxes(pil, boxes, scores, labels)
            for label, score, box in zip(labels, scores, boxes):
                x1 = max(0, int(box[0]))
                y1 = max(0, int(box[1]))
                x2 = min(w, int(box[2]))
                y2 = min(h, int(box[3]))
                if x2 > x1 and y2 > y1:
                    crop = pil.crop((x1, y1, x2, y2))
                    all_detections.append((idx, label, score, crop))
        else:
            annotated_frames[idx] = pil

    progress.progress(1.0, text="Deduplicating...")

    if all_detections:
        results = deduplicate(all_detections, extractor, device, sim_threshold)
        st.session_state.results = results
        st.session_state.annotated_frames = annotated_frames
    else:
        st.session_state.results = {}
        st.session_state.annotated_frames = annotated_frames

    progress.empty()

# ── Results ──────────────────────────────────────────────────────────────────
if st.session_state.annotated_frames:
    st.subheader("Annotated Frames")
    cols = st.columns(len(st.session_state.annotated_frames))
    for col, (idx, img) in zip(cols, st.session_state.annotated_frames.items()):
        col.image(img, caption=f"Camera {idx} — Detections", use_container_width=True)

if st.session_state.results:
    results = st.session_state.results

    total_raw = sum(r["raw_detections"] for r in results.values())
    total_dedup = sum(r["count"] for r in results.values())
    removed = total_raw - total_dedup

    st.subheader("Deduplicated Results")

    # Metrics row
    c1, c2, c3 = st.columns(3)
    c1.metric("Raw detections", total_raw)
    c2.metric("After dedup", total_dedup)
    c3.metric("Duplicates removed", removed)

    # Results table
    table_data = []
    for label, info in sorted(results.items(), key=lambda x: -x[1]["count"]):
        cams = ", ".join(str(c) for c in info["cam_sources"])
        table_data.append({
            "Item": label,
            "Count": info["count"],
            "Raw": info["raw_detections"],
            "Confidence": f"{info['best_confidence']:.2f}",
            "Cameras": cams,
            "Category": CATEGORY_MAP.get(label, "vegetable"),
        })
    st.table(table_data)

    # ── Add to backend ───────────────────────────────────────────────────────
    if backend_url:
        st.subheader("Add to FridgeAI")
        if st.button("Add all items to inventory", type="primary"):
            import httpx
            added = 0
            errors = 0
            token = st.session_state.get("auth_token", "")
            headers = {"Authorization": f"Bearer {token}"} if token else {}

            for label, info in results.items():
                try:
                    # Look up shelf life and cost from backend
                    category = CATEGORY_MAP.get(label, "vegetable")
                    shelf_life = 7
                    estimated_cost = 0.0
                    try:
                        lookup = httpx.get(
                            f"{backend_url.rstrip('/')}/lookup/item/{label}",
                            headers=headers, timeout=5,
                        )
                        if lookup.status_code == 200:
                            data = lookup.json()
                            shelf_life = data.get("shelf_life", 7)
                            estimated_cost = data.get("estimated_cost", 0.0)
                            category = data.get("category", category)
                    except Exception:
                        pass

                    resp = httpx.post(
                        f"{backend_url.rstrip('/')}/items",
                        json={
                            "name": label,
                            "category": category,
                            "quantity": info["count"],
                            "shelf_life": shelf_life,
                            "location": "",
                            "estimated_cost": estimated_cost,
                            "storage_temp": 4.0,
                            "humidity": 50.0,
                        },
                        headers=headers,
                        timeout=10,
                    )
                    if resp.status_code in (200, 201):
                        added += 1
                    else:
                        errors += 1
                except Exception:
                    errors += 1

            if added:
                st.success(f"Added {added} item type(s) to inventory!")
            if errors:
                st.warning(f"{errors} item(s) failed — check backend URL or auth token.")
