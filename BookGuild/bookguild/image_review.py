"""Vision review shared by chapter illustrations and cover artwork, with bounded refinements."""

from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage

from bookguild import prompts
from bookguild.reliability import PermanentError, TransientError

PASS_SCORE = 70  # must be strictly above this
MAX_IMPROVEMENTS = 3  # initial generation plus at most three feedback-driven generations


def image_data_url(path: Path) -> str:
    image = QImage(str(path))
    if image.isNull():
        raise PermanentError("Cannot review an unreadable image", use_fallback=False)
    if max(image.width(), image.height()) > 1024:
        image = image.scaled(1024, 1024, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(bytes(data)).decode("ascii")


def validate_review(data) -> None:
    if type(data.get("score")) is not int or not 0 <= data["score"] <= 100:
        raise TransientError("Image Reviewer score must be an integer from 0 to 100")
    if not isinstance(data.get("feedback"), str) or not data["feedback"].strip():
        raise TransientError("Image Reviewer must provide feedback")


async def review_image(job, path: Path, purpose: str, context: str, references: list[str], stage: str) -> dict:
    prompt = prompts.render("image_reviewer", style=job.profile.image_style, purpose=purpose, context=context)
    content = [{"type": "text", "text": prompt}] + [
        {"type": "image_url", "image_url": {"url": url}}
        for url in [image_data_url(path), *references]
    ]
    result = await job.gateway.chat_json(agent="Image Reviewer", stage=stage, model=job.models.image_reviewer,
                                         messages=[{"role": "user", "content": content}], max_tokens=1200,
                                         thinking="off", required_keys=("score", "feedback"), validate=validate_review)
    return {"score": result.data["score"], "feedback": result.data["feedback"].strip(), "model": result.model}


def refinement_prompt(base: str, feedback: list[str]) -> str:
    return base + "\nImprove the illustration using this review feedback:\n" + "\n".join(feedback)
