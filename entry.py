import json
import random
from datetime import date
from js import fetch, Headers, Request, Response

# =========================
# 配置项与全局常量
# =========================
LPA_CODE = "LPA:1$millicomelsalvador.validereachdpplus.com$GENERICJOWMI-FAHTCU0-SKFMYPW6UIEFGRWC8GE933ITFAUVN63WMUVHFOWTS80"

# 请替换为你的二维码图片直链（Cloudflare 无法像本地服务器一样直接读本地磁盘图片，需走网络 URL）
QR_CODE_URL = "https://telegra.ph/file/6b1cbdd4986f98a03e066078f0c3eee6.png"

DISCLAIMER_TEXT = """
<b>⚠️ 免责声明 (Disclaimer)</b>

1. <b>软件用途</b>：本 Bot 仅供技术研究、软件测试及自动化接口验证使用。严禁用于任何商业用途或非法目的。
2. <b>数据说明</b>：测试中用到的身份信息（DUI 等）均为伪随机算法自动生成，不含任何真实个人隐私。
3. <b>责任界定</b>：使用者因误用或滥用本工具导致的任何后果均由使用者自行承担。
"""

FIRST_NAMES_MALE = ["Carlos", "Luis", "Jose", "Juan", "Diego", "Fernando", "Jorge", "Manuel"]
FIRST_NAMES_FEMALE = ["Maria", "Ana", "Sofia", "Lucia", "Elena", "Valeria", "Camila", "Mariana"]
LAST_NAMES = ["Hernandez", "Martinez", "Lopez", "Gonzalez", "Perez", "Rodriguez", "Sanchez", "Ramirez"]


# =========================
# 算法与数据生成
# =========================

def generate_dui():
    """生成合规的萨尔瓦多 DUI 9位纯数字 (带加权校验码)"""
    digits = [random.randint(0, 9) for _ in range(8)]
    weights = [9, 8, 7, 6, 5, 4, 3, 2]
    total_sum = sum(d * w for d, w in zip(digits, weights))
    
    remainder = total_sum % 10
    check_digit = 0 if remainder == 0 else 10 - remainder
    return "".join(map(str, digits)) + str(check_digit)


def generate_customer():
    gender = random.choice(["M", "F"])
    names = FIRST_NAMES_MALE if gender == "M" else FIRST_NAMES_FEMALE
    first_name = random.choice(names)
    second_name = random.choice(names)
    surname = random.choice(LAST_NAMES)
    
    birth_year = random.randint(1985, 2005)
    birth_month = random.randint(1, 12)
    birth_day = random.randint(1, 28)
    dob = date(birth_year, birth_month, birth_day).isoformat()

    return {
        "first_name": first_name,
        "second_name": second_name,
        "surname": surname,
        "second_surname": "",
        "dob": dob,
        "identification": generate_dui(),
        "identification_type": "DUI",
        "gender": None,
        "identification_issue_date": None,
        "identification_exp_date": None,
        "email": None,
        "contact_phone_number": None,
        "address": {"state": "SANTA ANA", "city": "SANTA ANA"},
        "nationality": None,
        "manual_input": False
    }


async def send_telegram_request(token, method, payload):
    """异步请求 Telegram Bot API"""
    url = f"https://api.telegram.org/bot{token}/{method}"
    headers = Headers.new({"Content-Type": "application/json"})
    req = Request.new(
        url,
        method="POST",
        headers=headers,
        body=json.dumps(payload)
    )
    await fetch(req)


# =========================
# Tigo 接口逻辑
# =========================

async def api_request(url_path, opts=None):
    opts = opts or {}
    base_url = "https://activate-sv-xapis-prod.tigocloud.net/sv"
    full_url = base_url + url_path
    
    headers = {
        "referer": "https://activate.tigo.com.sv/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    if "headers" in opts:
        headers.update(opts["headers"])

    js_headers = Headers.new(headers)
    req_options = {
        "method": opts.get("method", "GET"),
        "headers": js_headers
    }
    
    if "body" in opts:
        req_options["body"] = opts["body"]

    req = Request.new(full_url, **req_options)
    response = await fetch(req)
    
    res_text = await response.text()
    try:
        result_json = json.loads(res_text)
    except Exception:
        raise Exception(f"服务器返回非 JSON 响应 (HTTP Status: {response.status})")

    response_data = result_json.get("response", {})
    result = response_data.get("result", {})

    if result.get("code") != 200:
        error_msg = result.get("result_message", {}).get("value", "未知 API 错误")
        raise Exception(f"接口错误 [{result.get('code')}]: {error_msg}")

    return response_data.get("data")


async def process_activation(iccid: str) -> dict:
    # Worker 中无 native uuid 库，生成 128 bit 随机 HEX 作为 UUID
    request_id = "%032x" % random.getrandbits(128)
    formatted_uuid = f"{request_id[:8]}-{request_id[8:12]}-{request_id[12:16]}-{request_id[16:20]}-{request_id[20:]}"

    # 1. 查询 SIM 卡信息
    auth_data = await api_request(
        f"/get-simcard?serialNumber={iccid}&requestId={formatted_uuid}&type=chip"
    )
    query_msisdn = auth_data["msisdn"]["value"]

    # 2. 构建 Payload
    customer = generate_customer()
    order_info = {
        "customer": customer,
        "activation": [
            {
                "offer": {},
                "offer_device": {},
                "resources": [
                    {
                        "parameters": [
                            {"name": "model"},
                            {"name": "imei"},
                            {"name": "icc", "value": iccid},
                            {"name": "msisdn", "value": query_msisdn},
                            {"name": "request_id", "value": formatted_uuid}
                        ]
                    }
                ]
            }
        ],
        "order": {
            "reference_number": "",
            "date": "",
            "action": "PREPAID_ACTIVATION",
            "journey": "activation"
        }
    }

    # 3. 提交激活申请
    order = await api_request(
        "/activation/order",
        {
            "method": "POST",
            "headers": {
                "content-type": "application/json",
                "authorization": f"Bearer {auth_data['accessToken']['value']}"
            },
            "body": json.dumps(order_info, ensure_ascii=False)
        }
    )

    activated_msisdn = order["activation"]["attributes"]["resources"]["attributes"]["parameters"]["attributes"]["msisdn"]["value"]
    trans_id = order.get("transaction_id", {}).get("value", "N/A")

    return {
        "activated_msisdn": activated_msisdn,
        "trans_id": trans_id,
        "customer_name": f"{customer['first_name']} {customer['second_name']} {customer['surname']}",
        "dui": customer['identification']
    }


# =========================
# Cloudflare Worker 主入口
# =========================

async def on_fetch(request, env):
    # 只处理 Telegram 推送过来的 POST 请求
    if request.method != "POST":
        return Response.new("Tigo Telegram Bot API is Running!")

    bot_token = env.BOT_TOKEN
    
    try:
        req_body = await request.text()
        update = json.loads(req_body)
    except Exception:
        return Response.new("Invalid JSON", status=400)

    message = update.get("message", {})
    text = message.get("text", "").strip()
    chat_id = message.get("chat", {}).get("id")

    if not chat_id or not text:
        return Response.new("OK")

    # 指令解析
    if text.startswith("/start"):
        welcome_message = (
            "🤖 <b>欢迎使用 Tigo SIM 自动化激活测试 Bot (Cloudflare 无服务器版)</b>\n\n"
            "<b>📌 支持指令：</b>\n"
            "• <code>/iccid [卡号]</code> - 自动激活指定 ICCID\n"
            "• <code>/esim</code> - 获取默认 eSIM 激活码与二维码\n\n"
            "-----------------------------------\n"
            f"{DISCLAIMER_TEXT}"
        )
        await send_telegram_request(bot_token, "sendMessage", {
            "chat_id": chat_id,
            "text": welcome_message,
            "parse_mode": "HTML"
        })

    elif text.startswith("/esim"):
        caption_text = (
            "📲 <b>eSIM 激活信息</b>\n\n"
            f"<b>LPA 激活码:</b>\n<code>{LPA_CODE}</code>\n\n"
            "💡 <i>可直接点击上述代码进行复制，或扫码添加。</i>"
        )
        await send_telegram_request(bot_token, "sendPhoto", {
            "chat_id": chat_id,
            "photo": QR_CODE_URL,
            "caption": caption_text,
            "parse_mode": "HTML"
        })

    elif text.startswith("/iccid"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await send_telegram_request(bot_token, "sendMessage", {
                "chat_id": chat_id,
                "text": "❌ <b>参数缺失！</b>\n正确格式：<code>/iccid 你的ICCID号码</code>",
                "parse_mode": "HTML"
            })
            return Response.new("OK")

        iccid = parts[1].strip()

        # 发送提示
        await send_telegram_request(bot_token, "sendMessage", {
            "chat_id": chat_id,
            "text": f"⏳ 正在提交激活申请...\n<b>ICCID:</b> <code>{iccid}</code>",
            "parse_mode": "HTML"
        })

        try:
            res = await process_activation(iccid)
            success_text = (
                "🎉 <b>SIM 卡激活成功！</b>\n\n"
                f"📱 <b>激活手机号 (MSISDN):</b> <code>{res['activated_msisdn']}</code>\n"
                f"💳 <b>绑定 ICCID:</b> <code>{iccid}</code>\n"
                f"🆔 <b>使用生成 DUI:</b> <code>{res['dui']}</code>\n"
                f"👤 <b>分配姓名:</b> {res['customer_name']}\n"
                f"🔖 <b>交易 ID:</b> <code>{res['trans_id']}</code>"
            )
            await send_telegram_request(bot_token, "sendMessage", {
                "chat_id": chat_id,
                "text": success_text,
                "parse_mode": "HTML"
            })
        except Exception as e:
            await send_telegram_request(bot_token, "sendMessage", {
                "chat_id": chat_id,
                "text": f"💥 <b>激活失败！</b>\n\n<b>ICCID:</b> <code>{iccid}</code>\n<b>原因:</b> <code>{str(e)}</code>",
                "parse_mode": "HTML"
            })

    return Response.new("OK")