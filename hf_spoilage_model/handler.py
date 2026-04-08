"""
Custom Inference Handler for MobileNetV3-Small Spoilage Classifier.

Input:  JPEG/PNG image (binary)
Output: [{"label": "spoiled", "score": 0.87}, {"label": "fresh", "score": 0.13}]
"""

import io
import torch
import torch.nn as nn
from PIL import Image
from torchvision import models, transforms


class EndpointHandler:
    def __init__(self, path=""):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # Load MobileNetV3-Small with custom binary classifier head
        self.model = models.mobilenet_v3_small(weights=None)
        self.model.classifier = nn.Sequential(
            nn.Linear(576, 256),
            nn.Hardswish(),
            nn.Dropout(0.2),
            nn.Linear(256, 1),
        )
        self.model.load_state_dict(
            torch.load(f"{path}/spoilage_mobilenetv3.pth", map_location=self.device)
        )
        self.model.eval().to(self.device)

        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])

    def __call__(self, data):
        """
        Args:
            data: dict with "inputs" key containing image bytes
        Returns:
            list of {"label": str, "score": float}
        """
        inputs = data.get("inputs")
        if isinstance(inputs, bytes):
            image = Image.open(io.BytesIO(inputs)).convert("RGB")
        elif isinstance(inputs, Image.Image):
            image = inputs.convert("RGB")
        else:
            return [{"label": "error", "score": 0.0}]

        tensor = self.transform(image).unsqueeze(0).to(self.device)

        with torch.no_grad():
            logit = self.model(tensor).squeeze()
            p_spoiled = float(torch.sigmoid(logit).cpu())

        return [
            {"label": "spoiled", "score": round(p_spoiled, 4)},
            {"label": "fresh", "score": round(1 - p_spoiled, 4)},
        ]
