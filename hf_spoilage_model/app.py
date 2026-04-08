"""
Gradio app for MobileNetV3 spoilage classifier.
Deployed as a HuggingFace Space — provides a free API endpoint.
"""

import torch
import torch.nn as nn
import gradio as gr
from torchvision import models, transforms
from PIL import Image

# ── Load model ───────────────────────────────────────────────────────────────
device = "cuda" if torch.cuda.is_available() else "cpu"

net = models.mobilenet_v3_small(weights=None)
net.classifier = nn.Sequential(
    nn.Linear(576, 256),
    nn.Hardswish(),
    nn.Dropout(0.2),
    nn.Linear(256, 1),
)
net.load_state_dict(torch.load("spoilage_mobilenetv3.pth", map_location=device))
net.eval().to(device)

transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


def classify(image: Image.Image) -> dict[str, float]:
    tensor = transform(image.convert("RGB")).unsqueeze(0).to(device)
    with torch.no_grad():
        logit = net(tensor).squeeze()
        p_spoiled = float(torch.sigmoid(logit).cpu())
    return {"fresh": round(1 - p_spoiled, 4), "spoiled": round(p_spoiled, 4)}


demo = gr.Interface(
    fn=classify,
    inputs=gr.Image(type="pil"),
    outputs=gr.Label(num_top_classes=2),
    title="FridgeAI Spoilage Classifier",
    description="Upload a food image to check if it's fresh or spoiled.",
)

demo.launch()
