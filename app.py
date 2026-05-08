from flask import Flask, request, send_from_directory
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent,
    TextMessage,
    TextSendMessage,
    ImageMessage,
    ImageSendMessage
)
from linebot.exceptions import InvalidSignatureError
from PIL import Image, ImageEnhance
from openai import OpenAI
import os
import base64
import uuid

app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

BASE_URL = os.getenv("BASE_URL", "https://line-nail-ai.onrender.com")
IMAGE_DIR = "static/images"
os.makedirs(IMAGE_DIR, exist_ok=True)

@app.route("/")
def home():
    return "LINE Nail AI Bot Running"

@app.route("/static/images/<filename>")
def serve_image(filename):
    return send_from_directory(IMAGE_DIR, filename)

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "Invalid signature", 400

    return "OK"

def process_image(image_data):
    filename = f"{uuid.uuid4().hex}.jpg"
    filepath = os.path.join(IMAGE_DIR, filename)

    temp_path = os.path.join(IMAGE_DIR, f"temp_{filename}")
    with open(temp_path, "wb") as f:
        f.write(image_data)

    img = Image.open(temp_path).convert("RGB")

    # 正方形トリミング
    w, h = img.size
    size = min(w, h)
    left = (w - size) // 2
    top = (h - size) // 2
    img = img.crop((left, top, left + size, top + size))

    # サイズ統一
    img = img.resize((1080, 1080))

    # 自然補正
    img = ImageEnhance.Brightness(img).enhance(1.08)
    img = ImageEnhance.Contrast(img).enhance(1.06)
    img = ImageEnhance.Color(img).enhance(1.04)
    img = ImageEnhance.Sharpness(img).enhance(1.08)

    img.save(filepath, "JPEG", quality=92)

    try:
        os.remove(temp_path)
    except:
        pass

    return filename, filepath

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_message = event.message.text

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": "あなたはネイルサロンSmilyのAIスタッフです。丁寧で自然な日本語で返信してください。"
            },
            {
                "role": "user",
                "content": user_message
            }
        ]
    )

    reply = response.choices[0].message.content

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    message_content = line_bot_api.get_message_content(event.message.id)

    image_data = b""
    for chunk in message_content.iter_content():
        image_data += chunk

    filename, filepath = process_image(image_data)

    image_url = f"{BASE_URL}/static/images/{filename}"

    base64_image = base64.b64encode(image_data).decode("utf-8")

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": """
あなたはネイルサロンSmilyのHot Pepper Beautyブログ担当AIです。

添付されたネイル画像を見て、ブログ投稿用の文章を作成してください。

条件：
・タイトルを作成
・本文は100〜180文字
・上品で大人っぽい
・売り込みすぎない
・絵文字なし
・最後に自然な予約誘導を入れる
・ハッシュタグを5個
・Hot Pepper Beautyにそのまま貼れる形
"""
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "このネイル画像のHot Pepper Beauty用ブログ文章を作成してください。"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ]
    )

    blog_text = response.choices[0].message.content

    line_bot_api.reply_message(
        event.reply_token,
        [
            ImageSendMessage(
                original_content_url=image_url,
                preview_image_url=image_url
            ),
            TextSendMessage(text=blog_text)
        ]
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
