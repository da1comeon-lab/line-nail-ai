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

ENDINGS = [
    "ご予約お待ちしております。",
    "ご来店お待ちしております。",
    "気になる方はぜひお試しください。"
]

WRITING_STYLES = [
    "ネイリストがそのまま投稿したような、短く自然な文章。",
    "少しラフで、説明しすぎないサロンブログ風。",
    "色味と雰囲気だけをさらっと書く文章。",
    "落ち着いた言い方で、押し売り感を出さない文章。",
    "きれいにまとめすぎず、日常の投稿っぽい文章。"
]

NG_REPLACE = {
    "個性的": "少し雰囲気のある",
    "個性": "雰囲気",
    "洗練": "すっきり",
    "演出": "仕上がり",
    "魅力": "良さ",
    "存在感": "ポイント感",
    "ワンランク": "",
    "映える": "きれいに見える",
    "アクセント": "ポイント",
    "上品な": "",
    "上品": "",
    "ちょうどいいです": "合わせやすい仕上がりです",
    "おすすめです。おすすめです。": "おすすめです。",
}


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


def save_latest_image(image_url, preview_url):
    try:
        with open(LATEST_IMAGE_FILE, "w", encoding="utf-8") as f:
            f.write(image_url + "\n")
            f.write(preview_url + "\n")
    except Exception as e:
        print("save latest image error:", e)


def read_latest_image():
    try:
        if not os.path.exists(LATEST_IMAGE_FILE):
            return None, None

        with open(LATEST_IMAGE_FILE, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines()]

        image_url = lines[0] if len(lines) > 0 else None
        preview_url = lines[1] if len(lines) > 1 else None
        return image_url, preview_url

    except Exception as e:
        print("read latest image error:", e)
        return None, None


@app.route("/")
def home():
    return """
    LINE Nail AI Running<br><br>
    確認ページ:<br>
    /instagram-status<br>
    /latest-image<br>
    /instagram-test-post<br>
    /google-status<br>
    /google-login<br>
    /google-locations<br>
    """


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
        print(traceback.format_exc())
        return "OK"

    return "OK"


@app.route("/instagram-status")
def instagram_status():
    html = "<h2>Instagram連携 状態確認</h2>"

    html += "<h3>環境変数</h3>"
    html += "<ul>"
    html += f"<li>INSTAGRAM_ACCOUNT_ID: {'設定あり' if INSTAGRAM_ACCOUNT_ID else '未設定'}</li>"
    html += f"<li>INSTAGRAM_ACCESS_TOKEN: {'設定あり' if INSTAGRAM_ACCESS_TOKEN else '未設定'}</li>"
    html += f"<li>INSTAGRAM_ACCOUNT_ID value: {INSTAGRAM_ACCOUNT_ID if INSTAGRAM_ACCOUNT_ID else ''}</li>"
    html += "</ul>"

    if not INSTAGRAM_ACCOUNT_ID or not INSTAGRAM_ACCESS_TOKEN:
        html += """
        <p>Instagramの環境変数が足りません。</p>
        <p>RenderのEnvironmentに以下を追加してください。</p>
        <pre>
INSTAGRAM_ACCOUNT_ID
INSTAGRAM_ACCESS_TOKEN
        </pre>
        """
        return html

    try:
        res = requests.get(
            f"https://graph.facebook.com/v25.0/{INSTAGRAM_ACCOUNT_ID}",
            params={
                "fields": "id,username,media_count",
                "access_token": INSTAGRAM_ACCESS_TOKEN
            },
            timeout=30
        )

        html += "<h3>Instagram API確認</h3>"
        html += f"<p>Instagram API status: {res.status_code}</p>"
        html += f"<pre>{res.text}</pre>"

        if res.status_code == 200:
            html += """
            <p>Instagram連携は確認できました。次に /latest-image で画像URLを確認できます。</p>
            """
        else:
            html += """
            <p>エラーの場合は、INSTAGRAM_ACCESS_TOKENの期限切れ、権限不足、またはInstagram Account ID違いの可能性があります。</p>
            """

        return html

    except Exception as e:
        print("Instagram status error:", e)
        print(traceback.format_exc())
        return html + f"<p>Instagram確認エラー: {e}</p>"


@app.route("/latest-image")
def latest_image():
    image_url, preview_url = read_latest_image()

    html = "<h2>最後に処理した画像</h2>"

    if not image_url:
        html += "<p>まだ画像がありません。先にLINEで画像を送ってください。</p>"
        return html

    test_url = f"/instagram-test-post?image_url={image_url}"

    html += f"<p>image_url:</p><pre>{image_url}</pre>"
    html += f"<p>preview_url:</p><pre>{preview_url if preview_url else ''}</pre>"
    html += f'<p><a href="{image_url}" target="_blank">画像を開く</a></p>'
    html += f'<p><img src="{image_url}" style="max-width:360px;height:auto;border:1px solid #ddd;"></p>'
    html += "<h3>Instagramテスト投稿</h3>"
    html += "<p>下のリンクを開いても、まだ投稿はされません。確認画面が出ます。</p>"
    html += f'<p><a href="{test_url}">Instagramテスト投稿の確認へ進む</a></p>'

    return html


@app.route("/instagram-test-post")
def instagram_test_post():
    if not INSTAGRAM_ACCOUNT_ID or not INSTAGRAM_ACCESS_TOKEN:
        return "Instagramの環境変数 INSTAGRAM_ACCOUNT_ID / INSTAGRAM_ACCESS_TOKEN が設定されていません。"

    image_url = request.args.get("image_url")
    confirm = request.args.get("confirm")

    if not image_url:
        image_url, _ = read_latest_image()

    if not image_url:
        return "投稿する画像URLがありません。先にLINEで画像を送るか、?image_url=画像URL を付けてください。"

    caption = request.args.get("caption") or "Instagram API連携テスト投稿です。\nSmily AI Postから投稿しています。"

    if confirm != "1":
        confirmed_url = f"/instagram-test-post?confirm=1&image_url={image_url}"
        return f"""
        <h2>Instagramテスト投稿 確認</h2>
        <p>この画面ではまだ投稿していません。</p>
        <p>下のリンクを押すと、実際にInstagramへ投稿されます。</p>
        <h3>投稿画像</h3>
        <pre>{image_url}</pre>
