import base64
import io
import os
import threading
from collections import defaultdict
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
PHOTO_DIR = BASE_DIR / "static" / "photos"

MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1-mini")
IMAGE_QUALITY = os.getenv("OPENAI_IMAGE_QUALITY", "medium")
PER_IP_LIMIT = int(os.getenv("PER_IP_LIMIT", "3"))
TOTAL_LIMIT = int(os.getenv("TOTAL_LIMIT", "80"))

usage_lock = threading.Lock()
usage_by_ip = defaultdict(int)
total_usage = 0

ALLOWED_PHOTOS = {f"photo{i}.jpg" for i in range(1, 5)} | {f"photo{i}.png" for i in range(1, 5)}


def get_client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def reserve_generation(ip: str):
    global total_usage
    with usage_lock:
        if total_usage >= TOTAL_LIMIT:
            return False, "本日の生成上限に達しました。遊んでくれてありがとう！"
        if usage_by_ip[ip] >= PER_IP_LIMIT:
            return False, f"この端末からの生成は{PER_IP_LIMIT}回までです。"
        usage_by_ip[ip] += 1
        total_usage += 1
    return True, None


def rollback_generation(ip: str):
    global total_usage
    with usage_lock:
        usage_by_ip[ip] = max(0, usage_by_ip[ip] - 1)
        total_usage = max(0, total_usage - 1)


def resolve_photo(filename: str) -> Path | None:
    safe_name = Path(filename).name
    if safe_name not in ALLOWED_PHOTOS:
        return None
    path = PHOTO_DIR / safe_name
    if path.exists():
        return path
    # jpg/pngのどちらでも差し替え可能
    stem = Path(safe_name).stem
    for ext in (".jpg", ".png", ".jpeg", ".webp"):
        candidate = PHOTO_DIR / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    return None


def crop_to_portrait_3x4(image: Image.Image) -> Image.Image:
    """Center-crop generated output to an exact 3:4 portrait ratio."""
    image = image.convert("RGB")
    width, height = image.size
    target_ratio = 3 / 4
    current_ratio = width / height

    if current_ratio > target_ratio:
        new_width = int(height * target_ratio)
        left = max(0, (width - new_width) // 2)
        image = image.crop((left, 0, left + new_width, height))
    elif current_ratio < target_ratio:
        new_height = int(width / target_ratio)
        top = max(0, (height - new_height) // 2)
        image = image.crop((0, top, width, top + new_height))

    return image


def add_watermark(image_bytes: bytes) -> bytes:
    image = Image.open(io.BytesIO(image_bytes))
    image = crop_to_portrait_3x4(image).convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    text = "じゃない方  Birthday 2026"
    font_size = max(22, image.width // 32)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 18, 12
    x = image.width - tw - pad_x * 2 - 22
    y = image.height - th - pad_y * 2 - 22
    draw.rounded_rectangle(
        (x, y, x + tw + pad_x * 2, y + th + pad_y * 2),
        radius=18,
        fill=(255, 255, 255, 185),
    )
    draw.text((x + pad_x, y + pad_y), text, font=font, fill=(255, 79, 149, 235))
    result = Image.alpha_composite(image, overlay).convert("RGB")
    out = io.BytesIO()
    result.save(out, format="JPEG", quality=92, optimize=True)
    return out.getvalue()


@app.get("/")
def index():
    return render_template("index.html", per_ip_limit=PER_IP_LIMIT)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/generate")
def generate():
    if not os.getenv("OPENAI_API_KEY"):
        return jsonify(error="OPENAI_API_KEYが設定されていません。"), 500

    data = request.get_json(silent=True) or {}
    photo_name = str(data.get("photo", ""))
    user_prompt = str(data.get("prompt", "")).strip()

    if not user_prompt:
        return jsonify(error="何をさせたいか入力してください。"), 400
    if len(user_prompt) > 200:
        return jsonify(error="入力は200文字以内にしてください。"), 400

    photo_path = resolve_photo(photo_name)
    if not photo_path:
        return jsonify(error="写真が見つかりません。static/photos内を確認してください。"), 400

    ip = get_client_ip()
    reserved, message = reserve_generation(ip)
    if not reserved:
        return jsonify(error=message), 429

    birthday_extras = ""
    if "ケーキ" in user_prompt:
        birthday_extras += " Include a festive birthday cake, balloons, ribbons and confetti."
    if "神" in user_prompt:
        birthday_extras += " Add a radiant golden, divine celebratory atmosphere."
    if "ラスボス" in user_prompt:
        birthday_extras += " Give the scene an epic final-boss atmosphere while keeping it playful."
    if "猫" in user_prompt:
        birthday_extras += " Add cute cat-themed accessories such as cat ears."

    full_prompt = f"""
Edit the supplied portrait photo according to this Japanese request: {user_prompt}
Preserve the person's recognizable facial identity, facial features, hairstyle, and overall likeness as faithfully as possible.
Create a polished, cute, joyful birthday-celebration image suitable for sharing on social media.
Compose it as a vertical portrait. Keep the person, face, hairstyle, hands, and important props safely inside the central 3:4 frame so nothing important is cropped.
Change clothing, pose, background, props, lighting, and atmosphere only as needed by the request.
Do not add unreadable text, extra people, duplicated limbs, or distorted hands.
Keep the result family-friendly and celebratory.{birthday_extras}
""".strip()

    try:
        client = OpenAI()
        with photo_path.open("rb") as image_file:
            result = client.images.edit(
                model=MODEL,
                image=image_file,
                prompt=full_prompt,
                size="1024x1536",
                quality=IMAGE_QUALITY,
                output_format="jpeg",
            )
        image_bytes = base64.b64decode(result.data[0].b64_json)
        image_bytes = add_watermark(image_bytes)
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return jsonify(image=f"data:image/jpeg;base64,{encoded}")
    except Exception as exc:
        rollback_generation(ip)
        app.logger.exception("Image generation failed")
        msg = str(exc)
        if "verification" in msg.lower():
            msg = "OpenAI側で組織認証が必要です。API管理画面を確認してください。"
        else:
            msg = "画像生成に失敗しました。少し内容を変えて、もう一度お試しください。"
        return jsonify(error=msg), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
