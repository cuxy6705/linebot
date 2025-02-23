import os
import datetime
import pytz
from datetime import timedelta
from flask import Flask, request, abort
from apscheduler.schedulers.background import BackgroundScheduler

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    PostbackEvent, TemplateSendMessage, ButtonsTemplate, PostbackAction
)

# Supabase
from supabase import create_client, Client

# Flask 應用初始化
app = Flask(__name__)

# 從環境變數讀取 LINE 與 Supabase 設定
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN')
CHANNEL_SECRET = os.getenv('CHANNEL_SECRET')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY')
tz_taipei = pytz.timezone("Asia/Taipei")

# 建立 LINE Bot 與 WebhookHandler
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
line_handler = WebhookHandler(CHANNEL_SECRET)

# 建立 Supabase 連線
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# APScheduler（在 Serverless 環境中不會真正常駐）
scheduler = BackgroundScheduler()
scheduler.start()


def parse_date_time(date_str, time_str):
    """
    將日期與時間字串解析為 datetime 物件。支援:
    - date_str: 2/19 or 2月19 or YYYY-MM-DD
    - time_str: HH:MM (24小時制)
    """
    current_year = datetime.datetime.now().year
    
    # 嘗試不帶年份的格式
    date_formats = ['%m/%d', '%m月%d']
    date_obj = None
    for fmt in date_formats:
        try:
            temp = datetime.datetime.strptime(date_str, fmt)
            date_obj = temp.replace(year=current_year)
            break
        except ValueError:
            pass
    
    if not date_obj:
        # 試試完整格式: YYYY-MM-DD
        try:
            date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            raise ValueError("日期格式錯誤")
    
    # 解析時間
    try:
        time_obj = datetime.datetime.strptime(time_str, '%H:%M')
    except ValueError:
        raise ValueError("時間格式錯誤")

    return date_obj.replace(hour=time_obj.hour, minute=time_obj.minute, second=0)


@line_handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """處理用戶傳入的文字訊息，解析日期/時間，並存入資料庫。"""
    user_id = event.source.user_id
    text = event.message.text.strip()
    parts = text.split(' ', 2)  # 期望: [日期, 時間, 事件描述]

    if len(parts) < 3:
        # 格式不符，回覆提示
        reply_text = ("請依照格式輸入：\n日期 時間 事件描述\n"
                      "例如：2/19 23:00 開會")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    date_str, time_str, desc = parts
    try:
        dt = parse_date_time(date_str, time_str)
        local_dt = tz_taipei.localize(dt)
        local_dt = local_dt - timedelta(hours=1)
        if local_dt <= datetime.datetime.now(tz_taipei):
            reply_text = "指定的提醒時間已過(提早後)，請輸入未來時間。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        utc_dt = local_dt.astimezone(pytz.utc)
    except ValueError:
        reply_text = ("日期或時間格式錯誤！\n"
                      "日期可用: MM/DD、MM月DD 或 YYYY-MM-DD\n"
                      "時間請用 24 小時 HH:MM")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 檢查是否是過去時間
    now = datetime.datetime.now()
    if dt <= now:
        reply_text = "指定的提醒時間已過，請輸入未來時間。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 將提醒事件寫入資料庫
    data = {
        "user_id": user_id,
        "notify_time": utc_dt.isoformat(),  # 以 ISO8601 字串儲存
        "text": desc,
        "is_sent": False
    }
    supabase.table("reminders").insert(data).execute()

    # reply_text = f"已設定提醒：{dt.strftime('%Y-%m-%d %H:%M')} {desc}"
    # line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))


@app.route("/callback", methods=['POST'])
def callback():
    """LINE Webhook 的入口，用於接收事件 (Event)"""
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info(f"Request body: {body}")

    try:
        line_handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. 請檢查你的 channel access token / channel secret。")
        abort(400)

    return 'OK'


@line_handler.add(MessageEvent, message=TextMessage)
def handle_postback(event):
    """
    只要使用者在 Template/Buttons 上按下 PostbackAction，就會進到這裡。
    透過解析 event.postback.data 來處理「延長時間」功能。
    """
    data = event.postback.data
    if data.startswith("extend_time="):
        # 拆出提醒ID 與 延長分鐘數
        raw = data.replace("extend_time=", "")  # 例如 "123|30"
        reminder_id_str, minutes_str = raw.split("|")
        reminder_id = int(reminder_id_str)
        extension = int(minutes_str)

        # 從資料庫撈出原本的提醒資訊
        resp = supabase.table("reminders").select("*").eq("id", reminder_id).single().execute()
        if not resp.data:
            # 找不到資料，可能已被刪除或其他原因
            line_bot_api.reply_message(
                event.reply_token, 
                TextSendMessage(text="無法延長，提醒不存在。")
            )
            return

        row = resp.data
        
        # 若要避免他人延長，可以比對 user_id
        # if row['user_id'] != event.source.user_id:
        #     line_bot_api.reply_message(event.reply_token, TextSendMessage(text="您無權限延長此提醒。"))
        #     return

        old_notify_time_utc = datetime.datetime.fromisoformat(row['notify_time'])  # UTC datetime
        new_notify_time_utc = old_notify_time_utc + datetime.timedelta(minutes=extension)

        # 更新資料庫 (notify_time + extension)，並把 is_sent 重設為 False
        supabase.table("reminders").update({
            "notify_time": new_notify_time_utc.isoformat(),
            "is_sent": False
        }).eq("id", reminder_id).execute()

        # 回覆使用者
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"已為您延長提醒 {extension} 分鐘。")
        )


@app.route("/cron", methods=['GET', 'POST'])
def cron():
    """
    提供給外部排程 (例如 Vercel Schedule、cron-job.org、GitHub Actions 等)
    每 X 分鐘/小時呼叫此路徑，檢查資料庫中是否有到期但未發送(is_sent=false)的提醒，推播給用戶。
    """
    now = datetime.datetime.utcnow()  # 假設你的資料庫 notify_time 存的是 UTC
    resp = supabase.table("reminders") \
        .select("*") \
        .lte("notify_time", now.isoformat()) \
        .eq("is_sent", False) \
        .execute()

    rows = resp.data
    if not rows:
        return "No reminders to process", 200

    success_count = 0
    for row in rows:
        user_id = row['user_id']
        desc = row['text']
        notify_time = row['notify_time']  # ISO8601 字串
        id = row['id']
        try:
            # 發送提醒
            notify_time_utc = datetime.datetime.fromisoformat(notify_time)
            local_time = notify_time_utc.astimezone(tz_taipei)
            formatted_time = f"{local_time.month}/{local_time.day} {local_time:%H:%M}"
            line_bot_api.push_message(
                user_id, 
                TemplateSendMessage(
                    alt_text=f"{formatted_time} {desc}",
                    template=ButtonsTemplate(
                        title="偷偷跟你說",
                        text=f"{desc}",
                        actions=[
                            PostbackAction(label="延長 30 分鐘", data=f"extend_time={id}|30"),
                            PostbackAction(label="延長 20 分鐘", data=f"extend_time={id}|20"),
                            PostbackAction(label="延長 15 分鐘", data=f"extend_time={id}|15"),
                            PostbackAction(label="延長 10 分鐘", data=f"extend_time={id}|10"),
                        ]
                    )
                )
                # TextSendMessage(text=f"{formatted_time} {desc}")
            )

            # 更新 is_sent 為 True
            supabase.table("reminders") \
                .update({"is_sent": True}) \
                .eq("id", row['id']) \
                .execute()

            success_count += 1
        except Exception as e:
            print("推播失敗:", e)

    return f"Processed {success_count} reminders", 200


if __name__ == "__main__":
    # 本地測試用，若在 Vercel 上則不需要這段或可保留
    app.run(debug=True)