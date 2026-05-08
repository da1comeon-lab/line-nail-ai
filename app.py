from flask import Flask, request, send_from_directory
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage, ImageSendMessage
from linebot.exceptions import InvalidSignatureError
from PIL import Image, ImageEnhance
from openai import OpenAI
import os, base64, uuid

app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

BASE_URL = os.getenv("BASE_URL", "https://line-nail-ai.onrender.com")
IMAGE_DIR = "static/images"
os.makedirs(IMAGE_DIR, exist_ok=True)

user_shop = {}

SHOPS = {
    "八尾店": "ネイルサロン スマイリー八尾店\n〒581-0869 大阪府八尾市桜ヶ丘3丁目119 加島ビル1F\nTEL 072-920-7313",
    "住道店": "ネイルサロン スマイリー住道店\n〒574-0046 大阪府大東市赤井1丁目15-27 ポップタウン住道5番館 2F\nTEL 072-870-0585",
    "心斎橋店": "ネイルサロン スマイリー心斎橋店\n〒542-0086 大阪府大阪市中央区西心斎橋1丁目8-22 4階\nTEL 06-4708-7318",
    "マカナ": "ネイルサロン マカナ河内山本店\n〒581-0013 大阪府八尾市山本町南4丁目1-3 岩田ビル506号\nTEL 070-9009-1440"
}

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

    # 1080正方形
    img = img.resize((1080, 1080))

    # 自然補正：明るめ・清潔感・実物感重視
    img = ImageEnhance.Brightness(img).enhance(1.10)
    img = ImageEnhance.Contrast(img).enhance(1.05)
    img = ImageEnhance.Color(img).enhance(1.03)
    img = ImageEnhance.Sharpness(img).enhance(1.10)

    img.save(filepath, "JPEG", quality=94)

    try:
        os.remove(temp_path)
    except:
        pass

    return filename

def shop_menu_text():
    return (
        "最初に店舗名を送ってください。\n\n"
        "例：\n"
        "八尾店\n"
        "住道店\n"
        "心斎橋店\n"
        "マカナ\n\n"
        "店舗設定後にネイル画像を送ると、加工画像とブログ文を作成します。"
    )

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    if text in SHOPS:
        user_shop[user_id] = text
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"{text}で設定しました。\n次にネイル画像を送ってください。")
        )
        return

    if text in ["店舗", "店舗変更", "店", "設定"]:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=shop_menu_text()))
        return

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=shop_menu_text())
    )

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    shop_key = user_shop.get(user_id)

    if not shop_key:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=shop_menu_text())
        )
        return

    message_content = line_bot_api.get_message_content(event.message.id)
    image_data = b""
    for chunk in message_content.iter_content():
        image_data += chunk

    filename = process_image(image_data)
    image_url = f"{BASE_URL}/static/images/{filename}"

    base64_image = base64.b64encode(image_data).decode("utf-8")
    shop_info = SHOPS[shop_key]

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": f"""
あなたはネイルサロンのHot Pepper Beautyブログ担当です。

ネイル画像を見て、サロンらしい自然なブログ文を作成してください。

文章ルール：
・少しカジュアルで親しみやすい
・でも安っぽくしない
・絵文字は絶対に使わない
・売り込みすぎない
・本文は100〜180文字
・Hot Pepper Beautyにそのまま貼れる形
・タイトルを最初に入れる
・最後に自然な予約誘導を入れる
・ハッシュタグは5個
・最後に必ず以下の店舗情報を入れる

店舗情報：
{shop_info}
"""
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "このネイル画像のブログ文章を作成してください。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ]
    )

    blog_text = response.choices[0].message.content

    line_bot_api.reply_message(
        event.reply_token,
        [
            ImageSendMessage(original_content_url=image_url, preview_image_url=image_url),
            TextSendMessage(text=blog_text)
        ]
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
