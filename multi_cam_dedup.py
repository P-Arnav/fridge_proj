"""
multi_cam_dedup.py — Multi-camera Grounding DINO detection with cross-camera deduplication.

Uses 3 USB cameras to detect items from multiple angles and deduplicates
detections via MobileNetV3 feature embeddings + cosine similarity clustering.

Install deps:
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
    pip install transformers pillow opencv-python

Usage:
    # Default: cameras 0, 1, 2
    python multi_cam_dedup.py

    # Custom camera indices
    python multi_cam_dedup.py --cams 0 1 2

    # Adjust thresholds
    python multi_cam_dedup.py --threshold 0.5 --sim 0.85

Controls:
    SPACE  — capture from all cameras, detect, and deduplicate
    R      — reset session counter
    Q      — quit
"""

import argparse
import sys
from collections import defaultdict, Counter

import cv2
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


# ── Model loading ────────────────────────────────────────────────────────────

def load_detector():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading Grounding DINO on {device.upper()}…")
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(MODEL_ID).to(device)
    print("Grounding DINO loaded.")
    return processor, model, device


def load_feature_extractor(device):
    """MobileNetV3-Small backbone for 576-dim pooled embeddings."""
    print("Loading MobileNetV3 feature extractor…")
    net = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)
    net.classifier = torch.nn.Identity()
    net.eval().to(device)
    print("Feature extractor loaded.")
    return net


# ── Detection & embedding ────────────────────────────────────────────────────

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
    """Return a normalised 576-dim embedding for a PIL crop."""
    tensor = EMBED_TRANSFORM(crop_pil).unsqueeze(0).to(device)
    with torch.no_grad():
        emb = extractor(tensor).squeeze()
    return F.normalize(emb, dim=0)


# ── Deduplication ─────────────────────────────────────────────────────────────

def deduplicate(all_detections, extractor, device, sim_threshold):
    """
    Cluster detections across cameras by label + visual similarity.

    all_detections: list of (cam_id, label, score, crop_pil)
    Returns dict of label → {count, best_confidence, cam_sources, raw_detections}
    """
    by_label = defaultdict(list)
    for cam_id, label, score, crop in all_detections:
        emb = extract_embedding(crop, extractor, device)
        by_label[label].append({"cam": cam_id, "score": score, "emb": emb})

    results = {}
    for label, detections in by_label.items():
        # Greedy clustering: assign each detection to an existing cluster
        # if cosine similarity with its centroid >= threshold, else start new cluster.
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
            "best_confidence": max(d["score"] for d in detections),
            "cam_sources": sorted(set(d["cam"] for d in detections)),
            "raw_detections": len(detections),
        }

    return results


# ── Camera helpers ────────────────────────────────────────────────────────────

def open_cameras(indices):
    caps = []
    for idx in indices:
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            print(f"WARNING: Cannot open camera {idx}, skipping.")
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        caps.append((idx, cap))
    if not caps:
        print("ERROR: No cameras could be opened.")
        sys.exit(1)
    print(f"Opened {len(caps)} camera(s): {[i for i, _ in caps]}")
    return caps


def draw_results(cv_image, boxes, scores, labels, cam_label=""):
    """Draw bounding boxes on a frame. Returns annotated copy."""
    import colorsys
    img = cv_image.copy()
    colors = {}

    for box, score, label in zip(boxes, scores, labels):
        x1, y1, x2, y2 = (int(v) for v in box)
        if label not in colors:
            h = hash(label) % 179
            r, g, b = (int(c * 255) for c in colorsys.hsv_to_rgb(h / 179, 0.85, 0.95))
            colors[label] = (b, g, r)

        color = colors[label]
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        text = f"{label}  {score:.2f}"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(img, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(img, text, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    if cam_label:
        cv2.putText(img, cam_label, (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 180), 2, cv2.LINE_AA)
    return img


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Multi-camera detection with deduplication")
    parser.add_argument("--cams", type=int, nargs="+", default=[0, 1, 2],
                        help="Camera indices (default: 0 1 2)")
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="Detection confidence threshold (default: 0.5)")
    parser.add_argument("--sim", type=float, default=0.85,
                        help="Cosine similarity threshold for dedup (default: 0.85)")
    parser.add_argument("--items", type=str, default=DEFAULT_ITEMS,
                        help="Dot-separated item list for detection prompt")
    args = parser.parse_args()

    if args.threshold < 0.5:
        print(f"WARNING: threshold {args.threshold} below minimum 0.5, clamping.")
        args.threshold = 0.5

    processor, dino, device = load_detector()
    extractor = load_feature_extractor(device)
    cameras = open_cameras(args.cams)

    items_text = args.items.strip().rstrip(".").strip() + " ."

    session_counter = Counter()
    capture_count = 0

    print("\nControls: SPACE = capture + detect + dedup, R = reset, Q = quit\n")

    while True:
        # Show live feeds side by side
        frames = {}
        for idx, cap in cameras:
            ret, frame = cap.read()
            if ret:
                frames[idx] = frame
                # Overlay session info on live feed
                overlay = frame.copy()
                cv2.putText(overlay, f"Cam {idx}", (10, 28),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 180), 2, cv2.LINE_AA)
                cv2.imshow(f"Camera {idx}", overlay)

        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            break

        if key == ord('r'):
            session_counter.clear()
            capture_count = 0
            print("Session counter reset.")

        if key == ord(' '):
            if not frames:
                print("No frames captured.")
                continue

            capture_count += 1
            print(f"\n{'='*56}")
            print(f"CAPTURE #{capture_count} — {len(frames)} camera(s)")
            print(f"{'='*56}")

            all_detections = []
            per_cam_results = {}

            for idx, frame in frames.items():
                pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                boxes, scores, labels = detect_items(
                    pil, processor, dino, device, items_text, args.threshold
                )
                w, h = pil.size

                cam_dets = []
                for label, score, box in zip(labels, scores, boxes):
                    x1 = max(0, int(box[0]))
                    y1 = max(0, int(box[1]))
                    x2 = min(w, int(box[2]))
                    y2 = min(h, int(box[3]))
                    if x2 > x1 and y2 > y1:
                        crop = pil.crop((x1, y1, x2, y2))
                        all_detections.append((idx, label, score, crop))
                        cam_dets.append(label)

                per_cam_results[idx] = (boxes, scores, labels)
                cam_counts = Counter(cam_dets)
                items_str = ", ".join(f"{l} x{c}" for l, c in cam_counts.most_common())
                print(f"  Cam {idx}: {len(labels)} detection(s)  [{items_str}]")

            if not all_detections:
                print("\nNo items detected across any camera.")
                continue

            # Show annotated frames
            cv2.destroyAllWindows()
            for idx, frame in frames.items():
                if idx in per_cam_results:
                    boxes, scores, labels = per_cam_results[idx]
                    annotated = draw_results(frame, boxes, scores, labels, f"Cam {idx}")
                    cv2.imshow(f"Camera {idx} — Detection", annotated)

            # Deduplicate
            print(f"\nDeduplicating with similarity threshold {args.sim}…")
            results = deduplicate(all_detections, extractor, device, args.sim)

            # Print deduplicated results
            print(f"\n{'─'*56}")
            print("DEDUPLICATED RESULTS")
            print(f"{'─'*56}")
            total_raw = 0
            total_dedup = 0
            for label, info in sorted(results.items(), key=lambda x: -x[1]["count"]):
                total_raw += info["raw_detections"]
                total_dedup += info["count"]
                cams = ", ".join(str(c) for c in info["cam_sources"])
                print(f"  {label:<20} x{info['count']}  "
                      f"(raw: {info['raw_detections']}, "
                      f"conf: {info['best_confidence']:.2f}, "
                      f"cams: [{cams}])")
                session_counter[label] = info["count"]

            print(f"{'─'*56}")
            print(f"  Total raw detections:   {total_raw}")
            print(f"  After deduplication:     {total_dedup}")
            print(f"  Duplicates removed:      {total_raw - total_dedup}")
            print(f"{'='*56}")

            if session_counter:
                print("\nSESSION TOTALS (latest dedup counts):")
                for item, count in session_counter.most_common():
                    print(f"  {item}: {count}")

            print("\nPress any key to return to live feed…")
            cv2.waitKey(0)
            cv2.destroyAllWindows()

    # Cleanup
    for _, cap in cameras:
        cap.release()
    cv2.destroyAllWindows()

    if session_counter:
        print(f"\nFINAL SESSION TOTALS:")
        for item, count in session_counter.most_common():
            print(f"  {item}: {count}")


if __name__ == "__main__":
    main()
