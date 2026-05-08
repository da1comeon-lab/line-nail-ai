from flask import Flask, request
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent,
    TextMessage,
    TextSendMessage,
    ImageMessage
)
from linebot.exceptions import InvalidSignatureError
import openai
import os
import base64

app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@app.route("/")
def home():
    return "LINE AI Bot Running"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return 'Invalid signature', 400

    return 'OK'

# テキスト返信
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

# 画像解析
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):

    message_content = line_bot_api.get_message_content(event.message.id)

    image_data = b''

    for chunk in message_content.iter_content():
        image_data += chunk

    base64_image = base64.b64encode(image_data).decode('utf-8')

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": """
あなたはネイルサロンSmilyのブログ担当AIです。

ネイル画像を解析して、
Hot Pepper Beauty用ブログ文章を作成してください。

条件：
・タイトル作成
・本文100〜180文字
・上品
・大人っぽい
・絵文字なし
・最後に予約誘導
・ハッシュタグ5個
"""
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "このネイル画像のブログ文章を作成してください"
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

    reply = response.choices[0].message.content

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
