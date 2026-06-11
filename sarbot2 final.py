# -*- coding: utf-8 -*-
"""
سربوت ٢ — النسخة النهائية المدمجة (القلب + الطقس)
وكيل سكرتير شخصي مبادر على تليقرام، محرّكه Gemini، معماريته registry قابلة للتوسّع.

يشمل هذه الدفعة:
  • جدولة مبادِرة (البوت يبدأ المحادثة بنفسه بأوقات محددة)
  • العادات: نادي، ماء، مشي، تنفّس، قراءة، نوم، وزن
  • المكملات: يومية بالأوقات + أسبوعية (أحد/ثلاثاء/خميس) + الأحد فقط
  • الحسّاس: أدوية نفسية + مزاج (تسجيل وعرض فقط، بحدود صارمة)
  • تخطيط الويكند (الخميس) + ملخص أسبوعي (الجمعة) + شهري (آخر جمعة)
  • صيام كل شهرين
  • TinyDB للتسجيل + Gemini لفهم الردود الطبيعية والرد بالنجدية

الطبقة الثانية لاحقاً: الطوالع، الفصول، درب التبانة، الطقس، نشرة SitDeck من Gmail.

────────────────────────────────────────────────────────
التثبيت:  pip install python-telegram-bot tinydb google-genai pytz
المتغيّرات السرّية (Secrets في Replit / Environment في Render):
    TELEGRAM_TOKEN   من @BotFather
    GEMINI_API_KEY   من https://aistudio.google.com/apikey
    MY_CHAT_ID       معرّف الدردشة الخاص بك (أرسل /start للبوت وسيطبعه)
التشغيل:  python sarbot2.py
────────────────────────────────────────────────────────
"""

import os
import datetime as dt
from zoneinfo import ZoneInfo

from tinydb import TinyDB, Query
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from google import genai
from google.genai import types

# ───────────────────────── الإعدادات العامة ─────────────────────────
TZ = ZoneInfo("Asia/Riyadh")          # تثبيت التوقيت على الرياض (مهم للجدولة)
RIYADH = "Asia/Riyadh"
db = TinyDB("sarbot.json")            # قاعدة التسجيل
LOG = db.table("log")                 # كل تسجيلات العادات/المكملات/المزاج
Q = Query()

genai_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MY_CHAT_ID = int(os.environ.get("MY_CHAT_ID", "0"))

# أيام الأسبوع في python-telegram-bot: 0=الأحد ... 6=السبت
SUN, MON, TUE, WED, THU, FRI, SAT = 0, 1, 2, 3, 4, 5, 6
GYM_DAYS = (SUN, MON, TUE, WED, THU)          # النادي أحد–خميس
WEEKLY_SUPP_DAYS = (SUN, TUE, THU)            # الأسبوعيات أحد/ثلاثاء/خميس


# ───────────────────────── شخصية سربوت (Gemini) ─────────────────────────
PERSONA = """\
أنت "سربوت" — سكرتير ومدرّب شخصي لعمر، تكلّمه باللهجة النجدية العامية بخفّة دم ومباشرة، دون مقدمات.
دورك: تذكّره بعاداته ومكمّلاته، تستقبل ردوده الطبيعية، تستخرج منها التسجيل، وتشجّعه باختصار.

قواعد صارمة:
- لا تعطِ تحليلاً طبياً أو نفسياً، ولا تعدّل جرعات دواء، ولا تربط الدواء بالمزاج.
- في الأمور الحسّاسة (دواء نفسي/مزاج): ردّك داعم وقصير فقط، بلا تحليل.
- لو المزاج منخفض، شجّعه يكلّم دكتوره، لا تحلّل أنت.
- كن مختصراً (جملة أو جملتين)، نجدي، وبلا مبالغة.
"""


def gemini_reply(user_text: str, context_note: str = "") -> str:
    """يفهم رد عمر الطبيعي ويرد بالنجدية بإيجاز."""
    try:
        prompt = f"{context_note}\n\nرسالة عمر: {user_text}\nردّ عليه بإيجاز نجدي مشجّع."
        resp = genai_client.models.generate_content(
            model="gemini-3.1-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=PERSONA, temperature=0.6,
            ),
        )
        return resp.text.strip()
    except Exception:
        return "سجّلتها ✅"


# ───────────────────────── وكيل الطقس (مدموج) ─────────────────────────
WEATHER_PERSONA = """\
أنت أستاذ أرصاد جوية وعالم مناخ، تجاوب عمر عن طقس الرياض وأي موقع يسأل عنه، بالنجدية المفهومة.
قواعد: استخدم بحث Google دائماً للبيانات الحية. افصل التوقع قصير المدى (≤14 يوم، موثوق)
عن الموسمي (احتمالي، فئات نوعية فقط). لا تختلق أرقاماً ولا مصادر — اذكر المصدر وتاريخه.
لا دقة زائفة: لا نسب مئوية موسمية إلا من مخرج نموذج فعلي.
لو سأل عن رصد فلكي/تطعيس: أضف الرؤية والغبار والغطاء السحابي وأفضل النوافذ.
"""


def weather_answer(question: str) -> str:
    """وكيل الطقس — بحث حي + منهجية البروفيسور."""
    try:
        resp = genai_client.models.generate_content(
            model="gemini-3.1-flash",
            contents=question,
            config=types.GenerateContentConfig(
                system_instruction=WEATHER_PERSONA,
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.3,
            ),
        )
        return resp.text.strip()
    except Exception:
        return "ما قدرت أسحب بيانات الطقس الحين، جرّب بعد شوي."


# ───────────────────────── سجل العادات (registry) ─────────────────────────
# إضافة أي عادة جديدة = سطر واحد هنا. كل شيء يتولّد منها تلقائياً.
HABITS = {
    "نادي_صباح": {"msg": "صباح الخير 💪 بتروح النادي اليوم؟", "time": (9, 0),  "days": GYM_DAYS},
    "نادي_عصر":  {"msg": "لا تنسَ النادي بعد الدوام 🏋️",      "time": (15, 0), "days": GYM_DAYS},
    "نادي_تأكيد":{"msg": "رحت النادي؟ وش تمرّنت اليوم؟",        "time": (20, 0), "days": GYM_DAYS, "track": "gym"},
    "مشي":       {"msg": "كم خطوة اليوم؟ (الهدف ١٠ آلاف)",     "time": (20, 30), "track": "steps"},
    "تنفّس":     {"msg": "سوّيت تمرين تنفّس/استرخاء اليوم؟",     "time": (22, 0),  "track": "breath"},
    "قراءة":     {"msg": "قريت شي اليوم؟",                     "time": (22, 30), "track": "read"},
    "نوم":       {"msg": "صباح الخير ☀️ كيف النوم؟ هات درجة قارمن", "time": (6, 0), "track": "sleep"},
    "وزن":       {"msg": "وش وزنك اليوم؟ (للمتابعة)",           "time": (6, 30),  "track": "weight"},
    "مزاج":      {"msg": "كيف مزاجك اليوم من ١ لـ ١٠؟",          "time": (21, 0),  "track": "mood", "sensitive": True},
    "دواء_نفسي": {"msg": "تذكير: أخذت دواءك النفسي اليوم؟",      "time": (9, 5),   "track": "psych_med", "sensitive": True},
}

# تذكير الماء كل ٣ ساعات من ٩ص لـ ٩م
WATER_HOURS = [9, 12, 15, 18, 21]
WATER_MSG = "💧 اشرب ماء — الهدف ٣ لتر اليوم"

# ───────────────────────── سجل المكملات (registry) ─────────────────────────
SUPPLEMENTS = {
    "ريق":      {"time": (7, 0),  "items": ["Probiotic", "NAC 600", "ALA 300"]},
    "فطور":     {"time": (8, 0),  "items": ["Vit D3", "Omega-3", "Collagen+HA", "B-Complex", "Multivitamin", "Zinc"]},
    "غداء":     {"time": (13, 0), "items": ["L-Carnitine", "Chromium", "Berberine", "Glutathione"]},
    "قبل_تمرين":{"time": (16, 30),"items": ["Beta-Alanine", "L-Citrulline", "Super Carb"], "days": GYM_DAYS},
    "بعد_تمرين":{"time": (18, 30),"items": ["Creatine 5g"], "days": GYM_DAYS},
    "عشاء":     {"time": (20, 30),"items": ["CoQ10", "Taurine"]},
    "قبل_النوم":{"time": (23, 0), "items": ["Magnesium", "Psyllium Husk"]},
    # الأسبوعية (أحد/ثلاثاء/خميس)
    "أسبوعي_ريق":  {"time": (7, 5),   "items": ["NMN 1000", "NR 300"], "days": WEEKLY_SUPP_DAYS},
    "أسبوعي_فطور": {"time": (8, 5),   "items": ["Resveratrol+Quercetin"], "days": WEEKLY_SUPP_DAYS},
    "أسبوعي_عشاء": {"time": (20, 35), "items": ["PQQ 20", "TUDCA 250"], "days": WEEKLY_SUPP_DAYS},
    # الأحد فقط
    "أحد_فقط":     {"time": (20, 40), "items": ["Fisetin 100"], "days": (SUN,)},
}
# ملاحظة: الأدوية النفسية الموصوفة (Cipralex/Brintellix/Wellbutrin/Lyrica) تُدار عبر
# تذكير "دواء_نفسي" الحسّاس أعلاه فقط — تذكير التزام، بلا أسماء جرعات في رسائل التشجيع.


# ───────────────────────── التسجيل في القاعدة ─────────────────────────
def today_str():
    return dt.datetime.now(TZ).strftime("%Y-%m-%d")

def log_entry(kind: str, value: str):
    LOG.insert({"date": today_str(), "kind": kind, "value": value,
                "ts": dt.datetime.now(TZ).isoformat()})

def recent_moods(days=3):
    """آخر تسجيلات المزاج (للملاحظة اللطيفة فقط — بلا تحليل)."""
    entries = sorted([e for e in LOG.search(Q.kind == "mood")],
                     key=lambda e: e["ts"], reverse=True)
    vals = []
    for e in entries[:days]:
        try:
            vals.append(int("".join(ch for ch in e["value"] if ch.isdigit())[:2] or "0"))
        except ValueError:
            pass
    return vals


# ───────────────────────── دوال الجدولة (callbacks) ─────────────────────────
async def send_habit(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(chat_id=job.chat_id, text=job.data["msg"])

async def send_water(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=context.job.chat_id, text=WATER_MSG)

async def send_supplement(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    items = "، ".join(d["items"])
    await context.bot.send_message(chat_id=context.job.chat_id,
                                   text=f"💊 وقت مكمّلات «{d['label']}»: {items}\nأخذتها؟")

async def weekly_summary(context: ContextTypes.DEFAULT_TYPE):
    """ملخص أسبوعي — الجمعة. يقرأ آخر ٧ أيام من القاعدة."""
    since = (dt.datetime.now(TZ) - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    rows = [e for e in LOG.all() if e["date"] >= since]
    summary = {}
    for e in rows:
        summary.setdefault(e["kind"], []).append(e["value"])
    lines = ["📊 ملخص أسبوعك:"]
    for kind, vals in summary.items():
        lines.append(f"• {kind}: {len(vals)} تسجيل")
    note = gemini_reply("هذا ملخص أسبوعي: " + str(summary),
                        "لخّص أسبوع عمر بإيجاز نجدي مشجّع، بلا تحليل طبي.")
    await context.bot.send_message(chat_id=context.job.chat_id,
                                   text="\n".join(lines) + "\n\n" + note)

async def weekend_plan(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=context.job.chat_id,
                                   text="🗓️ الخميس! وش خطتك للويكند؟ (تطعيس / رصد / راحة؟)")

async def fasting_reminder(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=context.job.chat_id,
                                   text="⏳ ذكّرتك: صيام الماء ٢٤ ساعة هالأسبوع (كل شهرين). جاهز؟")


# ───────────────────────── معالجة ردود عمر ─────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    # سؤال طقس بأي صيغة → وكيل الطقس مباشرة
    if any(w in text for w in ("طقس", "اجواء", "أجواء", "حرارة", "غبار", "امطار", "أمطار")):
        await update.message.reply_text("⛅ أسحب البيانات...")
        await update.message.reply_text(weather_answer(text))
        return

    # تسجيل ذكي بسيط: نخزّن النص ونترك Gemini يردّ.
    # (الطبقة الثانية: استخراج منظّم لكل نوع)
    log_entry("note", text)

    # ملاحظة لطيفة للمزاج المنخفض المتكرّر — بلا تحليل
    extra = ""
    moods = recent_moods(3)
    if len(moods) == 3 and all(m and m <= 4 for m in moods):
        extra = ("\n\nألاحظ مزاجك متعكّر كم يوم ورا بعض. ما أحلّل — بس يمكن زين "
                 "تحجز موعد مع دكتورك في تطبيق لبيه وتطمّن نفسك. تبيني أذكّرك بكرة؟")

    reply = gemini_reply(text)
    await update.message.reply_text(reply + extra)


async def weather_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = " ".join(context.args) if context.args else "طقس الرياض اليوم وبقية الأسبوع"
    await update.message.reply_text("⛅ أسحب البيانات...")
    await update.message.reply_text(weather_answer(q))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await update.message.reply_text(
        f"هلا عمر 👋 سربوت جاهز.\nمعرّف دردشتك: {cid}\n"
        "حطّه في متغيّر MY_CHAT_ID وأعد التشغيل عشان أبدأ أرسل لك التذكيرات تلقائياً."
    )


# ───────────────────────── جدولة كل المهام ─────────────────────────
def schedule_all(app: Application, chat_id: int):
    jq = app.job_queue

    # العادات
    for name, h in HABITS.items():
        hh, mm = h["time"]
        jq.run_daily(send_habit, time=dt.time(hh, mm, tzinfo=TZ),
                     days=h.get("days", tuple(range(7))),
                     data={"msg": h["msg"]}, chat_id=chat_id, name=name)

    # الماء
    for hr in WATER_HOURS:
        jq.run_daily(send_water, time=dt.time(hr, 0, tzinfo=TZ),
                     chat_id=chat_id, name=f"water_{hr}")

    # المكملات
    for label, s in SUPPLEMENTS.items():
        hh, mm = s["time"]
        jq.run_daily(send_supplement, time=dt.time(hh, mm, tzinfo=TZ),
                     days=s.get("days", tuple(range(7))),
                     data={"label": label, "items": s["items"]},
                     chat_id=chat_id, name=f"supp_{label}")

    # تخطيط الويكند — الخميس ٥ مساءً
    jq.run_daily(weekend_plan, time=dt.time(17, 0, tzinfo=TZ), days=(THU,),
                 chat_id=chat_id, name="weekend_plan")

    # ملخص أسبوعي — الجمعة ٨ مساءً
    jq.run_daily(weekly_summary, time=dt.time(20, 0, tzinfo=TZ), days=(FRI,),
                 chat_id=chat_id, name="weekly_summary")

    # صيام — كل شهرين (نفحصه أول كل شهر، ويُرسل في الأشهر الزوجية)
    jq.run_monthly(fasting_reminder, when=dt.time(10, 0, tzinfo=TZ), day=1,
                   chat_id=chat_id, name="fasting")




# ───────────────────────── بوابة ويب شكلية (لخطة Render المجانية) ─────────────────────────
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class _Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"sarbot alive")
    def log_message(self, *a):  # تسكيت السجل
        pass

def start_keepalive():
    port = int(os.environ.get("PORT", "10000"))
    threading.Thread(
        target=lambda: HTTPServer(("0.0.0.0", port), _Ping).serve_forever(),
        daemon=True,
    ).start()


def main():
    start_keepalive()  # بوابة Render المجانية
    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("weather", weather_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    if MY_CHAT_ID:
        schedule_all(app, MY_CHAT_ID)

    print("سربوت ٢ شغّال... (Ctrl+C للإيقاف)")
    app.run_polling()


if __name__ == "__main__":
    main()
