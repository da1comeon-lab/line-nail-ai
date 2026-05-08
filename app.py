from flask import Flask, request, send_from_directory
from linebot import LineBotApi, WebhookHandler
from linebot.models import *
from linebot.exceptions import InvalidSignatureError
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from openai import OpenAI
import os, uuid, base64

app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

BASE_URL = os.getenv("BASE_URL", "https://line-nail-ai.onrender.com")
IMAGE_DIR = "static/images"
os.makedirs(IMAGE_DIR, exist_ok=True)

user_shop = {}

SHOPS = {
    "八尾店": {
        "name": "ネイルサロン スマイリー八尾店",
        "info": "〒581-0869 大阪府八尾市桜ヶ丘3丁目119 加島ビル1F\nTEL 072-920-7313",
        "style": "親しみやすく、少しラフ。お客様目線でわかりやすい文章。"
    },
    "住道店": {
        "name": "ネイルサロン スマイリー住道店",
        "info": "〒574-0046 大阪府大東市赤井1丁目15-27 ポップタウン住道5番館 2F\nTEL 072-870-0585",
        "style": "ナチュラルで女性らしく、普段使いしやすい文章。"
    },
    "心斎橋店": {
        "name": "ネイルサロン スマイリー心斎橋店",
        "info": "〒542-0086 大阪府大阪市中央区西心斎橋1丁目8-22 4階\nTEL 06-4708-7318",
        "style": "大人っぽく、落ち着いた上品な文章。"
    },
    "マカナ": {
        "name": "ネイルサロン マカナ河内山本店",
        "info": "〒581-0013 大阪府八尾市山本町南4丁目1-3 岩田ビル506号\nTEL 070-9009-1440",
        "style": "韓国っぽさ、透明感、トレンド感のある文章。"
    }
}

@app.route("/")
def home():
    return "LINE Nail AI Running"

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

def crop_square_nail_focus(img):
    w, h = img.size
    size = min(w, h)

    left = (w - size) // 2
    top = int((h - size) * 0.28)
    top = max(0, min(top, h - size))

    return img.crop((left, top, left + size, top + size))

def natural_nail_retouch(filepath):
    img = Image.open(filepath).convert("RGB")
    img = ImageOps.exif_transpose(img)

    # 額縁なし：元画像をそのまま正方形トリミング
    img = crop_square_nail_focus(img)
    img = img.resize((1080, 1080), Image.LANCZOS)

    # 全体を少し明るく
    img = ImageEnhance.Brightness(img).enhance(1.10)
    img = ImageEnhance.Contrast(img).enhance(1.04)

    # 赤み・黄ばみを軽く抑えて、清潔感寄せ
    r, g, b = img.split()
    r = r.point(lambda i: min(255, int(i * 0.975)))
    g = g.point(lambda i: min(255, int(i * 1.005)))
    b = b.point(lambda i: min(255, int(i * 1.018)))
    img = Image.merge("RGB", (r, g, b))

    # 彩度を少しだけ控える
    img = ImageEnhance.Color(img).enhance(0.96)

    # 肌のシワ感を少しだけなめらかに
    soft = img.filter(ImageFilter.GaussianBlur(radius=0.45))
    img = Image.blend(img, soft, 0.18)

    # 爪のツヤ感を戻す
    img = ImageEnhance.Sharpness(img).enhance(1.22)

    # 最終調整
    img = ImageEnhance.Brightness(img).enhance(1.03)
    img = ImageEnhance.Contrast(img).enhance(1.03)

    img.save(filepath, "JPEG", quality=95, optimize=True)

def shop_message():
    return """店舗名を送信してください。

・八尾店
・住道店
・心斎橋店
・マカナ

設定後にネイル画像を送ると、
画像加工＋ブログ文章を自動作成します。"""

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    if text in SHOPS:
        user_shop[user_id] = text
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"{SHOPS[text]['name']}で設定しました。\nネイル画像を送ってください。")
        )
        return

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=shop_message()))

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id

    if user_id not in user_shop:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=shop_message()))
        return

    shop_key = user_shop[user_id]
    shop = SHOPS[shop_key]

    message_content = line_bot_api.get_message_content(event.message.id)

    filename = f"{uuid.uuid4().hex}.jpg"
    filepath = os.path.join(IMAGE_DIR, filename)

    with open(filepath, "wb") as f:
        for chunk in message_content.iter_content():
            f.write(chunk)

    natural_nail_retouch(filepath)

    image_url = f"{BASE_URL}/static/images/{filename}"

    with open(filepath, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode("utf-8")

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        temperature=0.65,
        messages=[
            {
                "role": "system",
                "content": f"""
あなたはネイルサロンのスタッフです。
Hot Pepper Beautyのブログ文を、実際のスタッフが書いたように自然に作成してください。

絶対ルール：
・絵文字は禁止
・AIっぽい説明文は禁止
・「洗練」「演出」「魅力を引き立てる」「効いた」「ぴったり」は使わない
・文章は短め
・売り込みすぎない
・少しだけカジュアル
・ネイルの特徴は拾うが、説明しすぎない
・同じ意味の言葉を繰り返さない
・季節感は無理に入れない
・本文は80〜140文字程度

文章構成：
【タイトル】
15〜22文字くらい。自然で短め。

本文：
2〜3文。
ネイリストが投稿するような口調。
最後は「ご予約お待ちしております。」で締める。

ハッシュタグ：
5個。地域名タグを1個入れる。

店舗情報：
{shop['name']}
{shop['info']}

店舗の文体：
{shop['style']}
"""
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "このネイル画像のHot Pepper Beauty用ブログ文を作成してください。"},
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
