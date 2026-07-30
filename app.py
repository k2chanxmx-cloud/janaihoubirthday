import base64
import io
import os
import threading
from collections import defaultdict
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from google import genai
from google.genai import types
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
PHOTO_DIR = BASE_DIR / "static" / "photos"

# RenderでGEMINI_IMAGE_MODELを設定していない場合は、このモデルを使います。
MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
PER_IP_LIMIT = int(os.getenv("PER_IP_LIMIT", "3"))
TOTAL_LIMIT = int(os.getenv("TOTAL_LIMIT", "80"))

usage_lock = threading.Lock()
usage_by_ip = defaultdict(int)
total_usage = 0

ALLOWED_PHOTOS = (
    {f"photo{i}.jpg" for i in range(1, 5)}
    | {f"photo{i}.jpeg" for i in range(1, 5)}
    | {f"photo{i}.png" for i in range(1, 5)}
    | {f"photo{i}.webp" for i in range(1, 5)}
)


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

    stem = Path(safe_name).stem
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = PHOTO_DIR / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    return None


def crop_to_portrait_3x4(image: Image.Image) -> Image.Image:
    """生成画像を中央基準で3:4の縦長に切り抜きます。"""
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
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    pad_x, pad_y = 18, 12

    x = max(16, image.width - text_width - pad_x * 2 - 22)
    y = max(16, image.height - text_height - pad_y * 2 - 22)

    draw.rounded_rectangle(
        (x, y, x + text_width + pad_x * 2, y + text_height + pad_y * 2),
        radius=18,
        fill=(255, 255, 255, 185),
    )
    draw.text(
        (x + pad_x, y + pad_y),
        text,
        font=font,
        fill=(255, 79, 149, 235),
    )

    result = Image.alpha_composite(image, overlay).convert("RGB")
    output = io.BytesIO()
    result.save(output, format="JPEG", quality=92, optimize=True)
    return output.getvalue()


def extract_generated_image(response) -> bytes:
    """Geminiの応答から最初の生成画像をJPEGバイト列として取り出します。"""
    for part in response.parts or []:
        if part.inline_data is None:
            continue

        generated = part.as_image()
        if generated is None:
            continue

        generated = generated.convert("RGB")
        output = io.BytesIO()
        generated.save(output, format="JPEG", quality=94)
        return output.getvalue()

    raise RuntimeError("Geminiから画像が返されませんでした。")


@app.get("/")
def index():
    return render_template("index.html", per_ip_limit=PER_IP_LIMIT)


@app.get("/health")
def health():
    return {"ok": True, "image_model": MODEL}


@app.post("/generate")
def generate():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return jsonify(error="GEMINI_API_KEYが設定されていません。"), 500

    data = request.get_json(silent=True) or {}
    photo_name = str(data.get("photo", ""))
    user_prompt = str(data.get("prompt", "")).strip()

    if not user_prompt:
        return jsonify(error="何をさせたいか入力してください。"), 400
    if len(user_prompt) > 200:
        return jsonify(error="入力は200文字以内にしてください。"), 400

    photo_path = resolve_photo(photo_name)
    if not photo_path:
        return jsonify(
            error="写真が見つかりません。static/photos内を確認してください。"
        ), 400

    ip = get_client_ip()
    reserved, message = reserve_generation(ip)
    if not reserved:
        return jsonify(error=message), 429

    birthday_extras = []
    if "ケーキ" in user_prompt:
        birthday_extras.append("誕生日ケーキ、風船、リボン、紙吹雪を自然に追加する")
    if "神" in user_prompt:
        birthday_extras.append("金色に輝く神々しいお祝いの雰囲気を加える")
    if "ラスボス" in user_prompt:
        birthday_extras.append("遊び心のある壮大なラスボス風の雰囲気を加える")
    if "猫" in user_prompt:
        birthday_extras.append("猫耳などのかわいい猫モチーフを加える")

    extra_instruction = ""
    if birthday_extras:
        extra_instruction = "\n追加演出：" + "。".join(birthday_extras) + "。"

    full_prompt = f"""
この入力写真そのものをベースにして、写真編集してください。
新しい人物を一から作らず、入力写真の人物を別人へ置き換えないでください。

最優先で維持するもの：
・同じ人物だと明確に分かる顔立ちと本人らしさ
・元写真の目、鼻、口、輪郭、肌の特徴
・髪型、髪色、眼鏡やアクセサリー
・元写真の表情。変顔なら、その変顔と口・目の形を保つ
・写真らしい質感

禁止事項：
・顔の美化や別人化
・アニメ、漫画、イラスト、CG、ドール風への変更
・頼まれていない顔や表情の変更
・余分な人物、手足の増殖、不自然な手
・読めない文字の追加

ユーザーの希望：
{user_prompt}

ユーザーの希望を実現するために必要な服、背景、小物、照明、周囲の演出だけを変更してください。
可能な限り元写真の構図とポーズを残してください。
完成画像は、元写真の本人を使って加工したリアルな誕生日記念写真にしてください。
人物の顔や重要な部分が切れない、SNS向けの縦長構図にしてください。{extra_instruction}
""".strip()

    try:
        client = genai.Client(api_key=api_key)

        with Image.open(photo_path) as source:
            source_image = source.convert("RGB")
            response = client.models.generate_content(
                model=MODEL,
                contents=[full_prompt, source_image],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                ),
            )

        image_bytes = extract_generated_image(response)
        image_bytes = add_watermark(image_bytes)
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return jsonify(image=f"data:image/jpeg;base64,{encoded}")

    except Exception as exc:
        rollback_generation(ip)
        app.logger.exception("Gemini image editing failed")

        error_text = str(exc).lower()
        if "api key" in error_text or "api_key" in error_text:
            message = "Gemini APIキーを確認してください。"
        elif "billing" in error_text or "quota" in error_text:
            message = "Geminiの請求設定または利用上限を確認してください。"
        elif "safety" in error_text or "blocked" in error_text:
            message = "その内容では生成できませんでした。表現を少し変えてください。"
        else:
            message = "画像生成に失敗しました。少し内容を変えて、もう一度お試しください。"

        return jsonify(error=message), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
