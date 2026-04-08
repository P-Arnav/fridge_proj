"""
Upload the spoilage classifier as a HuggingFace Space (Gradio app).
Provides a free API endpoint for spoilage classification.

Usage:
    pip install huggingface_hub
    python upload_to_hf.py
"""

import shutil
import os
from huggingface_hub import HfApi, login

SPACE_NAME = "fridgeai-spoilage"
MODEL_SRC = "fridgeai-backend/models/spoilage_mobilenetv3.pth"
UPLOAD_DIR = "hf_spoilage_model"

# Copy model weights into the upload directory
shutil.copy(MODEL_SRC, os.path.join(UPLOAD_DIR, "spoilage_mobilenetv3.pth"))
print(f"Copied {MODEL_SRC} to {UPLOAD_DIR}/")

login()

api = HfApi()
user = api.whoami()["name"]
repo_id = f"{user}/{SPACE_NAME}"

api.create_repo(repo_id=repo_id, repo_type="space", space_sdk="gradio", exist_ok=True)
print(f"Space: https://huggingface.co/spaces/{repo_id}")

api.upload_folder(
    folder_path=UPLOAD_DIR,
    repo_id=repo_id,
    repo_type="space",
    commit_message="Deploy MobileNetV3 spoilage classifier",
)

print(f"\nDone! Space: https://huggingface.co/spaces/{repo_id}")
print(f"API endpoint: https://{user}-{SPACE_NAME}.hf.space/api/predict")
