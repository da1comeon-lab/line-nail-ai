from flask import Flask, request, send_from_directory, redirect, session
from linebot import LineBotApi, WebhookHandler
from linebot.models import *
from linebot.exceptions import InvalidSignatureError
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from openai import OpenAI
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

import os
import uuid
import base64
import random
import secrets
import requests
import numpy as np
import cv2

try:
    import mediapipe as mp
    MEDIAPIPE_AVAILABLE = True
except Exception:
    MEDIAPIPE_AVAILABLE = False


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

BASE_URL = os.getenv("BASE_URL", "https://line-nail-ai.onrender.com")
IMAGE_DIR = "static/images"
os.makedirs(IMAGE_DIR, exist_ok=True)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")
GOOGLE_REDIRECT_URI = "https://line-nail-ai.onrender.com/oauth2callback"

SCOPES = ["https://www.googleapis.com/auth/business.manage"]

user_shop = {}

SHOPS = {
    "八尾店": {
        "name": "ネイルサロン スマイリー八尾店",
        "info": "〒581-0869 大阪府八尾市桜ヶ丘3丁目119 加島ビル1F\nTEL 072-920-7313",
        "area_tag": "#八尾ネイル",
    },
    "住道店": {
        "name": "ネイルサロン スマイリー住道店",
        "info": "〒574-0046 大阪府大東市赤井1丁目15-27 ポップタウン住道5番館 2F\nTEL 072-870-0585",
        "area_tag": "#住道ネイル",
    },
    "心斎橋店": {
        "name": "ネイルサロン スマイリー心斎橋店",
        "info": "〒542-0086 大阪府大阪市中央区西心斎橋1丁目8-22 4階\nTEL 06-4708-7318",
        "area_tag": "#心斎橋ネイル",
    },
    "マカナ": {
        "name": "ネイルサロン マカナ河内山本店",
        "info": "〒581-0013 大阪府八尾市山本町南4丁目1-3 岩田ビル506号\nTEL 070-9009-1440",
        "area_tag": "#河内山本ネイル",
    }
}

GOOD_EXAMPLES = """
【タイトル】
ブラックフレンチ×パールネイル

【本文】
黒フレンチにパールを合わせたデザインです。
片手は黒ベースにして、少し雰囲気を変えています。
落ち着いたカラーでも少しポイントが欲しい方におすすめです。

ご予約お待ちしております。
"""

NG_REPLACE = {
    "個性的": "少し雰囲気のある",
    "個性": "雰囲気",
    "洗練": "すっきり",
    "演出": "仕上がり",
    "魅力": "良さ",
    "アクセント": "ポイント",
    "存在感": "ほどよいポイント感",
    "ワンランク": "",
    "映える": "写真でもきれいに見える",
    "ポツポツ": "少し",
    "散らして": "合わせて",
    "シンプルながら": "シンプルですが",
}

ENDINGS = [
    "ご予約お待ちしております。",
    "ご来店お待ちしております。",
    "気になる方はぜひお試しください。"
]


def google_client_config():
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI]
        }
    }


def get_google_credentials():
    if not GOOGLE_REFRESH_TOKEN:
        return None

    return Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES
    )


def get_access_token():
    creds = get_google_credentials()
    if not creds:
        return None

    from google.auth.transport.requests import Request
    creds.refresh(Request())
    return creds.token


@app.route("/")
def home():
    return "LINE Nail AI Running"


@app.route("/google-login")
def google_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return "Googleの環境変数が設定されていません。"

    flow = Flow.from_client_config(
        google_client_config(),
        scopes=SCOPES,
        autogenerate_code_verifier=True
    )

    flow.redirect_uri = GOOGLE_REDIRECT_URI

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )

    session["oauth_state"] = state
    session["code_verifier"] = flow.code_verifier

    return redirect(authorization_url)


@app.route("/oauth2callback")
def oauth2callback():
    try:
        state = session.get("oauth_state")
        code_verifier = session.get("code_verifier")

        if not state or not code_verifier:
            return "Google連携エラー：セッション情報が切れています。もう一度 /google-login からやり直してください。"

        flow = Flow.from_client_config(
            google_client_config(),
            scopes=SCOPES,
            state=state
        )

        flow.redirect_uri = GOOGLE_REDIRECT_URI
        flow.code_verifier = code_verifier

        flow.fetch_token(authorization_response=request.url)

        credentials = flow.credentials
        refresh_token = credentials.refresh_token

        if not refresh_token:
            return "Google連携は成功しましたが、refresh_token が取得できませんでした。もう一度 /google-login を開いて許可し直してください。"

        return f"""
        Google連携成功<br><br>
        次にRenderのEnvironmentへ下記を追加してください。<br><br>
        KEY：GOOGLE_REFRESH_TOKEN<br>
        VALUE：{refresh_token}<br><br>
        この画面の内容は他人に見せないでください。
        """

    except Exception as e:
        return f"Google連携エラー：{e}"


@app.route("/google-locations")
def google_locations():
    try:
        token = get_access_token()

        if not token:
            return "GOOGLE_REFRESH_TOKEN が設定されていません。"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        accounts_res = requests.get(
            "https://mybusinessaccountmanagement.googleapis.com/v1/accounts",
            headers=headers,
            timeout=30
        )

        if accounts_res.status_code != 200:
            return f"""
            Googleアカウント取得エラー<br>
            ステータス: {accounts_res.status_code}<br>
            本文: {accounts_res.text}
            """

        accounts = accounts_res.json().get("accounts", [])

        if not accounts:
            return "Googleビジネスアカウントが見つかりませんでした。"

        html = "<h2>Googleビジネス 店舗一覧</h2>"

        for account in accounts:
            account_name = account.get("name")
            account_title = account.get("accountName", "")

            html += f"<h3>{account_title}<br>{account_name}</h3>"

            locations_res = requests.get(
                f"https://mybusinessbusinessinformation.googleapis.com/v1/{account_name}/locations?readMask=name,title,storefrontAddress",
                headers=headers,
                timeout=30
            )

            html += f"<p>locations status: {locations_res.status_code}</p>"

            if locations_res.status_code != 200:
                html += f"<pre>{locations_res.text}</pre>"
                continue

            locations = locations_res.json().get("locations", [])

            if not locations:
                html += "<p>店舗なし</p>"
                continue

            html += "<ul>"
            for loc in locations:
                name = loc.get("name", "")
                title = loc.get("title", "")
                address = loc.get("storefrontAddress", {})
                lines = address.get("addressLines", [])
                postal = address.get("postalCode", "")
                admin = address.get("administrativeArea", "")
                locality = address.get("locality", "")

                html += f"""
                <li>
                    <b>{title}</b><br>
                    location_id: {name}<br>
                    {postal} {admin} {locality} {' '.join(lines)}
                </li><br>
                """
            html += "</ul>"

        return html

    except Exception as e:
        return f"Google店舗取得エラー：{e}"


@app.route("/static/images/<filename>")
def serve_image(filename):
    return send_from_directory(IMAGE_DIR, filename)


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "Invalid signature", 400
    except Exception as e:
        print("callback error:", e)
        return "OK"

    return "OK"


def clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def make_square_box(x1, y1, x2, y2, w, h, margin_ratio=0.28):
    bw = x2 - x1
    bh = y2 - y1

    margin = int(max(bw, bh) * margin_ratio)

    x1 -= margin
    y1 -= margin
    x2 += margin
    y2 += margin

    x1 = clamp(x1, 0, w)
    y1 = clamp(y1, 0, h)
    x2 = clamp(x2, 0, w)
    y2 = clamp(y2, 0, h)

    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2

    box_size = int(max(x2 - x1, y2 - y1))

    # 爪が見切れないよう、少し大きめに取る
    box_size = int(box_size * 1.12)

    # 元画像からはみ出さない範囲で最大化
    box_size = min(box_size, w, h)

    left = cx - box_size // 2
    top = cy - box_size // 2

    left = clamp(left, 0, w - box_size)
    top = clamp(top, 0, h - box_size)

    return left, top, left + box_size, top + box_size


def crop_with_mediapipe(rgb):
    if not MEDIAPIPE_AVAILABLE:
        return None

    h, w, _ = rgb.shape

    try:
        mp_hands = mp.solutions.hands

        with mp_hands.Hands(
            static_image_mode=True,
            max_num_hands=2,
            model_complexity=1,
            min_detection_confidence=0.45
        ) as hands:
            result = hands.process(rgb)

        if not result.multi_hand_landmarks:
            return None

        xs = []
        ys = []

        for hand_landmarks in result.multi_hand_landmarks:
            for lm in hand_landmarks.landmark:
                xs.append(int(lm.x * w))
                ys.append(int(lm.y * h))

        if not xs or not ys:
            return None

        x1 = clamp(min(xs), 0, w)
        y1 = clamp(min(ys), 0, h)
        x2 = clamp(max(xs), 0, w)
        y2 = clamp(max(ys), 0, h)

        # 手全体＋爪先が切れないように余白を広めに
        return make_square_box(x1, y1, x2, y2, w, h, margin_ratio=0.42)

    except Exception as e:
        print("mediapipe crop error:", e)
        return None


def crop_with_opencv_content(rgb):
    h, w, _ = rgb.shape

    try:
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

        # 背景が白系でも、手・爪・影・輪郭を拾う
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]

        mask_saturation = saturation > 22
        mask_not_white = value < 245
        edges = cv2.Canny(gray, 50, 130)
        mask_edges = edges > 0

        mask = (mask_saturation & mask_not_white) | mask_edges
        mask = mask.astype(np.uint8) * 255

        kernel = np.ones((7, 7), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return None

        # 小さいゴミを除外
        valid = []
        image_area = w * h

        for c in contours:
            area = cv2.contourArea(c)
            if area > image_area * 0.015:
                valid.append(c)

        if not valid:
            return None

        all_points = np.vstack(valid)
        x, y, bw, bh = cv2.boundingRect(all_points)

        return make_square_box(x, y, x + bw, y + bh, w, h, margin_ratio=0.35)

    except Exception as e:
        print("opencv content crop error:", e)
        return None


def crop_safe_square(rgb):
    h, w, _ = rgb.shape

    box = crop_with_mediapipe(rgb)

    if box is None:
        box = crop_with_opencv_content(rgb)

    if box is None:
        size = min(w, h)
        left = (w - size) // 2
        top = int((h - size) * 0.35)
        top = clamp(top, 0, h - size)
        box = (left, top, left + size, top + size)

    left, top, right, bottom = box
    cropped = rgb[top:bottom, left:right]

    return cropped


def compress_highlights(rgb):
    img = rgb.astype(np.float32)

    # 白飛び部分だけ少し抑える
    threshold = 238
    mask = img > threshold
    img[mask] = threshold + (img[mask] - threshold) * 0.38

    return np.clip(img, 0, 255).astype(np.uint8)


def auto_light_correction(rgb):
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)

    l, a, b = cv2.split(lab)

    mean_l = float(np.mean(l))
    p95 = float(np.percentile(l, 95))
    p99 = float(np.percentile(l, 99))

    # 白飛びが強い場合は先に抑える
    rgb = compress_highlights(rgb)

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    # 明るすぎる写真は補正を弱く、暗い写真だけ自然に持ち上げる
    if mean_l < 132:
        clip_limit = 1.8
        brightness_alpha = 1.04
        brightness_beta = 8
    elif mean_l < 162:
        clip_limit = 1.45
        brightness_alpha = 1.02
        brightness_beta = 3
    elif p95 > 238 or p99 > 248:
        clip_limit = 1.05
        brightness_alpha = 0.985
        brightness_beta = -2
    else:
        clip_limit = 1.22
        brightness_alpha = 1.00
        brightness_beta = 0

    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    l2 = clahe.apply(l)

    lab2 = cv2.merge((l2, a, b))
    bgr2 = cv2.cvtColor(lab2, cv2.COLOR_LAB2BGR)

    bgr2 = cv2.convertScaleAbs(bgr2, alpha=brightness_alpha, beta=brightness_beta)

    rgb2 = cv2.cvtColor(bgr2, cv2.COLOR_BGR2RGB)

    return rgb2


def natural_color_adjustment(rgb):
    pil = Image.fromarray(rgb).convert("RGB")

    # やりすぎない自然補正
    pil = ImageEnhance.Color(pil).enhance(1.025)
    pil = ImageEnhance.Contrast(pil).enhance(1.025)

    # 肌や白背景を不自然にしない程度の軽いシャープ
    pil = ImageEnhance.Sharpness(pil).enhance(1.12)

    # ざらつき軽減
    soft = pil.filter(ImageFilter.GaussianBlur(radius=0.25))
    pil = Image.blend(pil, soft, 0.06)

    return np.array(pil)


def improve_nail_image(filepath):
    pil = Image.open(filepath).convert("RGB")
    pil = ImageOps.exif_transpose(pil)

    rgb = np.array(pil)

    # 爪・手が見切れにくい安全トリミング
    rgb = crop_safe_square(rgb)

    # 正方形1080px
    pil = Image.fromarray(rgb).resize((1080, 1080), Image.LANCZOS)
    rgb = np.array(pil)

    # 白飛び防止＋自然な明るさ補正
    rgb = auto_light_correction(rgb)

    # 色味・質感の自然補正
    rgb = natural_color_adjustment(rgb)

    out = Image.fromarray(rgb).convert("RGB")
    out.save(filepath, "JPEG", quality=95, optimize=True)


def clean_text(text):
    for old, new in NG_REPLACE.items():
        text = text.replace(old, new)

    # 余計な空白を少し整理
    text = text.replace("。。", "。")
    text = text.replace("、、", "、")
    text = text.strip()

    return text


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

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=shop_message())
    )


@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id

    if user_id not in user_shop:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=shop_message())
        )
        return

    shop_key = user_shop[user_id]
    shop = SHOPS[shop_key]

    try:
        message_content = line_bot_api.get_message_content(event.message.id)

        filename = f"{uuid.uuid4().hex}.jpg"
        filepath = os.path.join(IMAGE_DIR, filename)

        with open(filepath, "wb") as f:
            for chunk in message_content.iter_content():
                f.write(chunk)

        improve_nail_image(filepath)

        image_url = f"{BASE_URL}/static/images/{filename}"

        with open(filepath, "rb") as img:
            base64_image = base64.b64encode(img.read()).decode("utf-8")

        ending = random.choice(ENDINGS)

        prompt = f"""
あなたは実際のネイルサロンスタッフです。
Hot Pepper BeautyのブログとInstagram投稿に使える文章を作成してください。

目的：
AIっぽくない、実際のネイリストが書いたような自然で短いサロン文章にする。

参考文章：
{GOOD_EXAMPLES}

文章の方向性：
・丁寧だけど、かしこまりすぎない
・説明しすぎない
・写真に写っているデザインだけを書く
・色、質感、パーツ、雰囲気を自然に説明する
・お客様に押し売りする感じにしない
・普通のサロンブログとして違和感のない文章にする

絶対ルール：
・絵文字は禁止
・顔文字は禁止
・大げさな表現は禁止
・変にオシャレに言いすぎない
・「おすすめです」は使っても1回まで
・「個性」「個性的」は使わない
・「洗練」「演出」「魅力」「ワンランク」「映える」「存在感」「ポツポツ」は使わない
・画像にない内容を想像で書かない
・季節感は、明らかに季節デザインの時だけ入れる
・本文は2〜4文
・1文は長くしすぎない
・毎回同じ文章パターンにしない

タイトルのルール：
・20文字前後
・自然なメニュー名っぽく
・無理にキャッチコピーにしない

ハッシュタグのルール：
・5個だけ
・必ず {shop['area_tag']} を1個入れる
・その他は画像に合うタグにする
・関係ないタグは入れない

出力形式は必ずこれ：

【タイトル】
タイトル

【本文】
本文
{ending}

#タグ #タグ #タグ #タグ #タグ

{shop['name']}
{shop['info']}
"""

        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0.28,
            max_tokens=700,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "このネイル画像の投稿文を作成してください。"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ]
        )

        text = response.choices[0].message.content
        text = clean_text(text)

        line_bot_api.reply_message(
            event.reply_token,
            [
                ImageSendMessage(
                    original_content_url=image_url,
                    preview_image_url=image_url
                ),
                TextSendMessage(text=text)
            ]
        )

    except Exception as e:
        print("image error:", e)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="エラーが出ました。もう一度画像を送ってください。")
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
