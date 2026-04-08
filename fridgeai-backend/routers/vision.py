"""
vision.py — POST /vision/scan

Priority order:
  1. HuggingFace Inference API (Llama 4 Scout vision)
  2. Gemini Vision API (fallback)
  3. Local Grounding DINO + MobileNetV3 (fallback, needs torch)
"""

from __future__ import annotations
import asyncio
import base64
import io
import json
import logging
import os
import re
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from pydantic import BaseModel

from routers.lookup import _map_category, get_item_shelf_life, get_item_cost

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vision", tags=["vision"])

HF_TOKEN           = os.getenv("HF_TOKEN", "")
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY", "")
MODEL_ID           = "IDEA-Research/grounding-dino-base"
THRESHOLD          = 0.5
SPOILAGE_MODEL     = Path(__file__).parent.parent / "models" / "spoilage_mobilenetv3.pth"
SPOILAGE_THRESHOLD = 0.5

HF_VISION_MODEL    = "meta-llama/Llama-4-Scout-17B-16E-Instruct"
HF_CHAT_URL        = "https://router.huggingface.co/v1/chat/completions"
HF_SPOILAGE_SPACE  = "https://xyphitos-fridgeai-spoilage.hf.space"


# ── Pydantic models ──────────────────────────────────────────────────────────

class DetectedItem(BaseModel):
    name:                str
    category:            str
    shelf_life:          int
    estimated_cost:      float
    confidence:          float
    count:               int
    spoilage_detected:   bool
    spoilage_confidence: float


class ScanResult(BaseModel):
    items:      list[DetectedItem]
    capture_id: str
    engine:     str = "huggingface"


class MultiScanResult(BaseModel):
    items:          list[DetectedItem]
    capture_id:     str
    engine:         str = "huggingface"
    cameras_used:   int
    raw_total:      int
    dedup_total:    int


# ── Shared prompt for vision LLMs ────────────────────────────────────────────

VISION_PROMPT = (
    "You are a fridge inventory scanner. Identify all food and drink items "
    "visible in this fridge/image. For each distinct item, return:\n"
    '{"name": string, "count": integer}\n\n'
    "Rules:\n"
    "- Return a JSON array only, no markdown, no explanation\n"
    "- count = number of that item visible\n"
    "- Use simple lowercase names (e.g. 'apple', 'milk', 'chicken')\n"
    "- If nothing is visible, return []\n"
    "- Do NOT assess freshness or spoilage\n"
)


def _parse_vision_response(content: str) -> list[DetectedItem]:
    """Parse JSON response from a vision LLM into DetectedItem list."""
    content = re.sub(r"^```(?:json)?\s*", "", content.strip())
    content = re.sub(r"\s*```$", "", content)

    raw: list[dict] = json.loads(content)
    items: list[DetectedItem] = []

    for entry in raw:
        name = str(entry.get("name", "")).strip().lower()
        if not name:
            continue
        category       = _map_category([name])
        shelf_life     = get_item_shelf_life(name, category)
        estimated_cost = get_item_cost(name)
        count          = max(1, int(entry.get("count", 1) or 1))

        items.append(DetectedItem(
            name                = name,
            category            = category,
            shelf_life          = shelf_life,
            estimated_cost      = estimated_cost,
            confidence          = 0.95,
            count               = count,
            spoilage_detected   = False,
            spoilage_confidence = 0.0,
        ))

    items.sort(key=lambda x: (-x.count, x.name))
    return items


# ── HF Spoilage Space API ────────────────────────────────────────────────────

async def _check_spoilage_hf(image_bytes: bytes) -> float:
    """Send image to HF Space spoilage classifier. Returns P(spoiled) in [0,1]."""
    b64 = base64.b64encode(image_bytes).decode()

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Upload file
        upload_resp = await client.post(
            f"{HF_SPOILAGE_SPACE}/gradio_api/upload",
            files={"files": ("scan.jpg", image_bytes, "image/jpeg")},
        )
        if upload_resp.status_code != 200:
            return 0.0
        file_path = upload_resp.json()[0]

        # Step 2: Call predict
        call_resp = await client.post(
            f"{HF_SPOILAGE_SPACE}/gradio_api/call/predict",
            json={"data": [{"path": file_path, "meta": {"_type": "gradio.FileData"}}]},
        )
        if call_resp.status_code != 200:
            return 0.0
        event_id = call_resp.json()["event_id"]

        # Step 3: Get result (SSE stream)
        result_resp = await client.get(
            f"{HF_SPOILAGE_SPACE}/gradio_api/call/predict/{event_id}",
            timeout=30.0,
        )
        # Parse SSE: "event: complete\ndata: [...]"
        for line in result_resp.text.splitlines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if data and isinstance(data, list):
                    confidences = data[0].get("confidences", [])
                    for c in confidences:
                        if c["label"] == "spoiled":
                            return float(c["confidence"])
    return 0.0


# ── HuggingFace path (Llama 4 Scout vision) ─────────────────────────────────

async def _scan_with_hf(image_bytes: bytes) -> list[DetectedItem]:
    """Send image to HF Inference API via Llama 4 Scout vision model."""
    b64 = base64.b64encode(image_bytes).decode()

    payload = {
        "model": HF_VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": VISION_PROMPT},
            ],
        }],
        "max_tokens": 1024,
        "temperature": 0.1,
    }

    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(3):
            resp = await client.post(HF_CHAT_URL, headers=headers, json=payload)
            if resp.status_code in (429, 503) and attempt < 2:
                wait = (attempt + 1) * 5
                logger.info("HF %d, retrying in %ds (attempt %d/3)", resp.status_code, wait, attempt + 1)
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            break

    content = resp.json()["choices"][0]["message"]["content"]
    return _parse_vision_response(content)


# ── Gemini Vision fallback ───────────────────────────────────────────────────

async def _scan_with_gemini(image_bytes: bytes) -> list[DetectedItem]:
    """Send image to Gemini Vision, return detected items."""
    b64 = base64.b64encode(image_bytes).decode()

    payload = {
        "contents": [{
            "parts": [
                {"text": VISION_PROMPT},
                {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
            ]
        }],
        "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.1},
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent?key={GEMINI_API_KEY}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(3):
            resp = await client.post(url, headers={"Content-Type": "application/json"}, json=payload)
            if resp.status_code == 429 and attempt < 2:
                wait = (attempt + 1) * 5
                logger.info("Gemini 429, retrying in %ds (attempt %d/3)", wait, attempt + 1)
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            break
        content = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    return _parse_vision_response(content)


# ── Local Grounding DINO fallback ────────────────────────────────────────────

GROCERY_PROMPT = (
    "milk . eggs . apple . orange . banana . yogurt . cheese . butter . "
    "cream . juice . water . soda . chicken . beef . fish . carrot . "
    "tomato . lettuce . broccoli . onion . potato . garlic . pepper . "
    "strawberry . grape . lemon . bread . leftovers . container . bottle . "
    "jar . can . sauce . condiment . spice . powder . chocolate . snack ."
)


def _get_dino(app_state):
    if getattr(app_state, "vision_model", None) is not None:
        return app_state.vision_processor, app_state.vision_model, app_state.vision_device
    try:
        import torch
        from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Vision deps missing: {e}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Loading Grounding DINO '%s' on %s…", MODEL_ID, device.upper())
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model     = AutoModelForZeroShotObjectDetection.from_pretrained(MODEL_ID).to(device)
    app_state.vision_processor = processor
    app_state.vision_model     = model
    app_state.vision_device    = device
    return processor, model, device


def _get_spoilage(app_state, device):
    if getattr(app_state, "spoilage_model", None) is not None:
        return app_state.spoilage_model
    try:
        import torch, torch.nn as nn
        from torchvision import models
    except ImportError:
        return None
    if not SPOILAGE_MODEL.exists():
        return None
    net = models.mobilenet_v3_small(weights=None)
    net.classifier = nn.Sequential(nn.Linear(576, 256), nn.Hardswish(), nn.Dropout(0.2), nn.Linear(256, 1))
    net.load_state_dict(torch.load(SPOILAGE_MODEL, map_location=device))
    net.eval().to(device)
    app_state.spoilage_model = net
    return net


def _spoilage_score(crop, spoilage_net, device) -> float:
    import torch
    from torchvision import transforms
    tf = transforms.Compose([
        transforms.Resize((224, 224)), transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    tensor = tf(crop).unsqueeze(0).to(device)
    with torch.no_grad():
        logit = spoilage_net(tensor).squeeze()
        return float(torch.sigmoid(logit).cpu())


async def _scan_with_dino(request: Request, pil_image) -> list[DetectedItem]:
    import torch
    processor, dino, device = _get_dino(request.app.state)
    spoilage_net             = _get_spoilage(request.app.state, device)
    inputs = processor(images=pil_image, text=GROCERY_PROMPT, return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = dino(**inputs)
    results = processor.post_process_grounded_object_detection(
        outputs, inputs.input_ids,
        threshold=THRESHOLD, text_threshold=THRESHOLD,
        target_sizes=[pil_image.size[::-1]],
    )[0]
    labels = results["labels"]
    scores = results["scores"].cpu().tolist()
    boxes  = results["boxes"].cpu().tolist()
    if not labels:
        return []
    w, h = pil_image.size
    label_data: dict[str, dict] = {}
    for label, score, box in zip(labels, scores, boxes):
        if label not in label_data:
            label_data[label] = {"scores": [], "spoilage_scores": []}
        label_data[label]["scores"].append(score)
        if spoilage_net is not None:
            x1, y1, x2, y2 = max(0, int(box[0])), max(0, int(box[1])), min(w, int(box[2])), min(h, int(box[3]))
            if x2 > x1 and y2 > y1:
                crop = pil_image.crop((x1, y1, x2, y2))
                label_data[label]["spoilage_scores"].append(_spoilage_score(crop, spoilage_net, device))
    detected: list[DetectedItem] = []
    for label, data in label_data.items():
        category       = _map_category([label])
        shelf_life     = get_item_shelf_life(label, category)
        estimated_cost = get_item_cost(label)
        sp_scores      = data["spoilage_scores"]
        avg_sp         = round(sum(sp_scores) / len(sp_scores), 3) if sp_scores else 0.0
        detected.append(DetectedItem(
            name=label, category=category, shelf_life=shelf_life, estimated_cost=estimated_cost,
            confidence=round(sum(data["scores"]) / len(data["scores"]), 3), count=len(data["scores"]),
            spoilage_detected=avg_sp >= SPOILAGE_THRESHOLD, spoilage_confidence=avg_sp,
        ))
    detected.sort(key=lambda x: (-x.count, -x.confidence))
    return detected


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("/scan", response_model=ScanResult)
async def scan_image(request: Request, file: UploadFile = File(...)):
    """
    Detect grocery items in an image.
    1. HuggingFace (Llama 4 Scout vision)
    2. Gemini Vision API (fallback)
    3. Local Grounding DINO + MobileNetV3 (fallback)
    """
    from PIL import Image

    raw = await file.read()
    try:
        pil_image = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")

    # Prepare a JPEG for API calls
    pil_image.thumbnail((1600, 1600), Image.LANCZOS)
    buf = io.BytesIO()
    pil_image.save(buf, format="JPEG", quality=90)
    image_bytes = buf.getvalue()

    # Path 1: HuggingFace (Llama 4 Scout)
    if HF_TOKEN:
        try:
            items = await _scan_with_hf(image_bytes)
            items = await _enrich_spoilage(items, image_bytes)
            return ScanResult(items=items, capture_id=str(uuid4()), engine="huggingface")
        except Exception as exc:
            logger.warning("HF scan failed, trying Gemini: %s", exc)

    # Path 2: Gemini Vision API
    if GEMINI_API_KEY:
        try:
            items = await _scan_with_gemini(image_bytes)
            items = await _enrich_spoilage(items, image_bytes)
            return ScanResult(items=items, capture_id=str(uuid4()), engine="gemini")
        except Exception as exc:
            logger.warning("Gemini scan failed, trying local DINO: %s", exc)

    # Path 3: Local Grounding DINO
    try:
        items = await _scan_with_dino(request, pil_image)
        return ScanResult(items=items, capture_id=str(uuid4()), engine="grounding-dino")
    except (ImportError, ModuleNotFoundError):
        raise HTTPException(
            status_code=503,
            detail="No vision backend available. Check HF_TOKEN, GEMINI_API_KEY, or install torch.",
        )


async def _enrich_spoilage(items: list[DetectedItem], image_bytes: bytes) -> list[DetectedItem]:
    """Run the HF Space spoilage model on the full image and apply to all items."""
    try:
        p_spoiled = await _check_spoilage_hf(image_bytes)
        if p_spoiled > 0:
            return [
                DetectedItem(
                    **{**item.model_dump(),
                       "spoilage_detected": p_spoiled >= SPOILAGE_THRESHOLD,
                       "spoilage_confidence": round(p_spoiled, 3)},
                )
                for item in items
            ]
    except Exception as exc:
        logger.warning("Spoilage check failed (non-fatal): %s", exc)
    return items


def _deduplicate_items(per_camera: list[list[DetectedItem]]) -> list[DetectedItem]:
    """Deduplicate items across cameras by taking max count per label."""
    # For each label, keep the best detection across cameras
    best: dict[str, DetectedItem] = {}
    raw_total = 0

    for cam_items in per_camera:
        for item in cam_items:
            raw_total += item.count
            if item.name not in best or item.count > best[item.name].count:
                best[item.name] = item
            elif item.name in best:
                existing = best[item.name]
                # Keep higher confidence even if same count
                if item.confidence > existing.confidence:
                    best[item.name] = DetectedItem(
                        **{**item.model_dump(), "count": max(item.count, existing.count)}
                    )
                # Preserve worst spoilage signal
                if item.spoilage_confidence > existing.spoilage_confidence:
                    best[item.name] = DetectedItem(
                        **{**best[item.name].model_dump(),
                           "spoilage_detected": item.spoilage_detected,
                           "spoilage_confidence": item.spoilage_confidence}
                    )

    dedup_total = sum(i.count for i in best.values())
    items = sorted(best.values(), key=lambda x: (-x.count, x.name))
    return items, raw_total, dedup_total


@router.post("/multi-scan", response_model=MultiScanResult)
async def multi_scan(request: Request, files: list[UploadFile] = File(...)):
    """
    Detect items across multiple camera images and deduplicate.
    Accepts multiple image files, runs detection on each, merges results.
    """
    from PIL import Image as PILImage

    if len(files) < 1:
        raise HTTPException(status_code=400, detail="At least one image required")
    if len(files) > 6:
        raise HTTPException(status_code=400, detail="Maximum 6 cameras supported")

    per_camera: list[list[DetectedItem]] = []
    engine_used = "huggingface"

    for file in files:
        raw = await file.read()
        try:
            pil_image = PILImage.open(io.BytesIO(raw)).convert("RGB")
        except Exception as e:
            logger.warning("Skipping invalid image: %s", e)
            continue

        pil_image.thumbnail((1600, 1600), PILImage.LANCZOS)
        buf = io.BytesIO()
        pil_image.save(buf, format="JPEG", quality=90)
        image_bytes = buf.getvalue()

        items = []

        # Try HF first
        if HF_TOKEN and not items:
            try:
                items = await _scan_with_hf(image_bytes)
                items = await _enrich_spoilage(items, image_bytes)
                engine_used = "huggingface"
            except Exception as exc:
                logger.warning("HF scan failed for camera image: %s", exc)

        # Fallback to Gemini
        if GEMINI_API_KEY and not items:
            try:
                items = await _scan_with_gemini(image_bytes)
                items = await _enrich_spoilage(items, image_bytes)
                engine_used = "gemini"
            except Exception as exc:
                logger.warning("Gemini scan failed for camera image: %s", exc)

        # Fallback to local DINO
        if not items:
            try:
                items = await _scan_with_dino(request, pil_image)
                engine_used = "grounding-dino"
            except (ImportError, ModuleNotFoundError):
                pass

        per_camera.append(items)

    if not any(per_camera):
        raise HTTPException(status_code=503, detail="Detection failed on all images")

    deduped, raw_total, dedup_total = _deduplicate_items(per_camera)

    return MultiScanResult(
        items=deduped,
        capture_id=str(uuid4()),
        engine=engine_used,
        cameras_used=len(per_camera),
        raw_total=raw_total,
        dedup_total=dedup_total,
    )
