import datetime
import time
import threading
import requests
import schedule
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
import telebot

# --- 1. ตั้งค่า Token และข้อมูลพื้นฐาน ---
my_access_token = 'EAAMGODCrJx0BSAorqIytUpbwpaZAIVwBFwzjKs4R6dqCfYmyArxqyhYDCeQIhZCM50PZCpkZAIrVvw44nJOM2XRIVvgJoVpWxRDciTmFL25x7XEpXZAE82ZBB7jKOFz0LOiZATef9DZA7XbwfAs1gcm2CdTi8UtnFnss2Lc2xrsaaYsEN9FAIHNMmOg0GXug'
my_account_id = 'act_903046447494483'

TELEGRAM_BOT_TOKEN = '8445150248:AAE-G9xNuB_Ol3F9nC66Bl_4RqQ3RiOH_VY'
TELEGRAM_CHAT_ID = '8330282208'

FacebookAdsApi.init(access_token=my_access_token)
account = AdAccount(my_account_id)

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

latest_crisis_campaigns = []
alerted_campaigns_today = set()
scale_alerted_today = set()
last_alert_date = datetime.date.today()

# --- 2. ฟังก์ชันวิเคราะห์เชิงลึกระดับมืออาชีพ ---
def analyze_campaign_performance_pro(spend, roas):
    if spend == 0:
        return "⚠️ *สถานะ:* ยังไม่มีการใช้จ่ายงบประมาณ"
    if roas >= 3.5:
        return "🔥 *สถานะ (Scale-up):* ผลลัพธ์ดีเยี่ยม เกินเป้าหมายหลัก"
    elif roas >= 2.5:
        return "⚡ *สถานะ (Stable):* ผลลัพธ์อยู่ในเกณฑ์เลี้ยงตัวได้กำไรดี"
    elif roas > 0:
        return "📉 *สถานะ (Optimization):* ROAS ต่ำกว่าจุดคุ้มทุน แนะนำลดงบหรือเปลี่ยนครีเอทีฟ"
    else:
        return "❌ *สถานะ (Critical):* ผลาญงบแต่ไม่มีคอนเวอร์ชั่น/ยอดขาย"

# --- 3. ฟังก์ชันหลัก: ดึงข้อมูลและสร้างรายงานสรุป ---
def generate_report_text(date_str=None):
    today = datetime.date.today()
    
    if date_str:
        try:
            parts = date_str.split('/')
            if len(parts) == 3:
                day = int(parts[0])
                month = int(parts[1])
                year_be = int(parts[2])
                year_ce = 2000 + year_be - 43 if year_be < 100 else (year_be - 543 if year_be > 2400 else year_be)
                target_date = datetime.date(year_ce, month, day)
                since_date = target_date.strftime('%Y-%m-%d')
                until_date = target_date.strftime('%Y-%m-%d')
                title_text = f"📊 *รายงานวิเคราะห์แคมเปญ (ประจำวันที่ {date_str})*"
            elif len(parts) == 2:
                month = int(parts[0])
                year_be = int(parts[1])
                year_ce = 2000 + year_be - 43 if year_be < 100 else (year_be - 543 if year_be > 2400 else year_be)
                since_date = f"{year_ce}-{month:02d}-01"
                if month == 12:
                    until_date = f"{year_ce}-12-31"
                else:
                    next_month = datetime.date(year_ce, month + 1, 1)
                    last_day = next_month - datetime.timedelta(days=1)
                    until_date = last_day.strftime('%Y-%m-%d')
                title_text = f"📊 *รายงานวิเคราะห์ภาพรวมประจำเดือน {date_str}*"
            else:
                raise ValueError
        except Exception:
            since_date = today.strftime('%Y-%m-%d')
            until_date = today.strftime('%Y-%m-%d')
            title_text = f"📊 *รายงานวิเคราะห์แคมเปญ (เรียลไทม์วันนี้)*"
    else:
        since_date = today.strftime('%Y-%m-%d')
        until_date = today.strftime('%Y-%m-%d')
        title_text = f"📊 *รายงานวิเคราะห์แคมเปญ (เรียลไทม์วันนี้)*"

    acc_url = f"https://graph.facebook.com/v18.0/{my_account_id}/insights"
    acc_params = {
        'access_token': my_access_token,
        'time_range': f'{{"since":"{since_date}","until":"{until_date}"}}',
        'fields': 'spend,purchase_roas,action_values'
    }
    acc_res = requests.get(acc_url, params=acc_params).json().get('data', [])
    
    grand_total_spend = 0.0
    grand_total_conv = 0.0
    grand_total_roas = 0.0
    
    if acc_res:
        grand_total_spend = float(acc_res[0].get('spend', 0))
        roas_list = acc_res[0].get('purchase_roas', [])
        if roas_list:
            grand_total_roas = float(roas_list[0].get('value', 0))
            
        action_values_list = acc_res[0].get('action_values', [])
        for item in action_values_list:
            if item.get('action_type') in ['omni_purchase', 'purchase', 'offsite_conversion.fb_pixel_purchase']:
                grand_total_conv += float(item.get('value', 0))

    camp_url = f"https://graph.facebook.com/v18.0/{my_account_id}/campaigns"
    camp_params = {
        'access_token': my_access_token,
        'effective_status': '["ACTIVE"]',
        'fields': 'name,daily_budget'
    }
    active_campaigns = requests.get(camp_url, params=camp_params).json().get('data', [])
    
    msg_lines = [
        title_text,
        f"🗓️ ช่วงเวลา: {since_date} ถึง {until_date}",
        "==================================="
    ]
    
    active_spend_sum = 0.0
    active_conv_sum = 0.0
    
    for camp in active_campaigns:
        camp_id = camp['id']
        camp_name = camp['name']
        daily_budget = float(camp.get('daily_budget', 0)) / 100 if camp.get('daily_budget') else 0.0
        
        insight_url = f"https://graph.facebook.com/v18.0/{camp_id}/insights"
        insight_params = {
            'access_token': my_access_token,
            'time_range': f'{{"since":"{since_date}","until":"{until_date}"}}',
            'fields': 'spend,purchase_roas,action_values'
        }
        
        insight_res = requests.get(insight_url, params=insight_params).json().get('data', [])
        
        spend = 0.0
        roas = 0.0
        conversion_value = 0.0
        
        if insight_res:
            spend = float(insight_res[0].get('spend', 0))
            active_spend_sum += spend
            
            roas_list = insight_res[0].get('purchase_roas', [])
            if roas_list:
                roas = float(roas_list[0].get('value', 0))
                
            action_values_list = insight_res[0].get('action_values', [])
            for item in action_values_list:
                if item.get('action_type') in ['omni_purchase', 'purchase', 'offsite_conversion.fb_pixel_purchase']:
                    conversion_value += float(item.get('value', 0))
            active_conv_sum += conversion_value

        pro_analysis = analyze_campaign_performance_pro(spend, roas)
        
        camp_text = (
            f"🎯 *{camp_name}* (🟢 เปิดอยู่)\n"
            f"   💰 ใช้จ่าย: {spend:,.2f} บ. | 📈 ROAS: {roas:.2f}\n"
            f"   {pro_analysis}\n"
            f"-----------------------------------"
        )
        msg_lines.append(camp_text)
    
    msg_lines.append(
        f"📌 *สรุปภาพรวมบัญชีทั้งหมด:*\n"
        f"   💰 งบใช้จ่ายรวม: {grand_total_spend:,.2f} บาท\n"
        f"   🛒 มูลค่าคอนเวอร์ชั่นรวม: {grand_total_conv:,.2f} บาท\n"
        f"   📈 ROAS รวม: {grand_total_roas:.2f}"
    )
        
    return "\n".join(msg_lines)

# --- 4. ฟังก์ชันตรวจสอบแคมเปญใหม่แบบอัจฉริยะ (Smart Alert & Auto-Kill) ---
def job_check_budget_alerts():
    global alerted_campaigns_today, last_alert_date, latest_crisis_campaigns, scale_alerted_today
    today = datetime.date.today()
    
    if today != last_alert_date:
        alerted_campaigns_today.clear()
        scale_alerted_today.clear()
        latest_crisis_campaigns.clear()
        last_alert_date = today

    today_str = today.strftime('%Y-%m-%d')
    
    camp_url = f"https://graph.facebook.com/v18.0/{my_account_id}/campaigns"
    camp_params = {
        'access_token': my_access_token,
        'effective_status': '["ACTIVE"]',
        'fields': 'name,created_time'
    }
    active_campaigns = requests.get(camp_url, params=camp_params).json().get('data', [])
    
    for camp in active_campaigns:
        camp_id = camp['id']
        camp_name = camp['name']
        created_time_str = camp.get('created_time', '')[:10]
        
        # เช็คเฉพาะแคมเปญที่สร้างใหม่ในวันนี้เท่านั้น
        if created_time_str != today_str:
            continue
            
        insight_url = f"https://graph.facebook.com/v18.0/{camp_id}/insights"
        insight_params = {
            'access_token': my_access_token,
            'time_range': f'{{"since":"{today_str}","until":"{today_str}"}}',
            'fields': 'spend,purchase_roas'
        }
        
        insight_res = requests.get(insight_url, params=insight_params).json().get('data', [])
        
        if insight_res:
            spend = float(insight_res[0].get('spend', 0))
            roas_list = insight_res[0].get('purchase_roas', [])
            roas = float(roas_list[0].get('value', 0)) if roas_list else 0.0
            
            # A. เช็คแคมเปญปัง (Scale Alert) ใช้งบ 50-100 บาท แต่ ROAS พุ่งสูง $\ge 3.5$
            if 50.0 <= spend <= 120.0 and roas >= 3.5:
                if camp_id not in scale_alerted_today:
                    scale_msg = (
                        f"🟢 *[SCALE ALERT] แคมเปญใหม่ปังมาก! นาทีทองสเกลงาน*\n\n"
                        f"🎯 *แคมเปญ:* {camp_name}\n"
                        f"💰 *ใช้จ่ายไปแค่:* {spend:,.2f} บาท\n"
                        f"🔥 *ROAS พุ่งสูงถึง:* {roas:.2f}\n\n"
                        f"📈 *คำแนะนำ:* พิจารณาเพิ่มงบประมาณเพื่อดันสเกลต่องานนี้ด่วน!"
                    )
                    try:
                        bot.send_message(TELEGRAM_CHAT_ID, scale_msg, parse_mode='Markdown')
                        scale_alerted_today.add(camp_id)
                    except Exception as e:
                        print(f"Error sending scale alert: {e}")

            # B. เช็คแคมเปญพัง (Critical Alert & Auto-Kill แบบขั้นบันได)
            if 120.0 <= spend <= 180.0 and roas == 0.0:
                if camp_id not in alerted_campaigns_today:
                    if camp_id not in [c['id'] for c in latest_crisis_campaigns]:
                        latest_crisis_campaigns.append({'id': camp_id, 'name': camp_name, 'spend': spend})
                        
                    alert_msg = (
                        f"🚨 *[CRITICAL ALERT] แคมเปญใหม่เผางบฟรี!*\n\n"
                        f"🎯 *แคมเปญ:* {camp_name}\n"
                        f"💰 *ใช้จ่ายไปแล้ว:* {spend:,.2f} บาท (ช่วงเตือน 120-150 บาท)\n"
                        f"❌ *สถานะ:* ยังไม่มี ROAS\n\n"
                        f"💬 พิมพ์ตอบกลับว่า `ปิดแคมเปญที่พึ่งขึ้นใหม่` หรือหากปล่อยทิ้งไว้เกิน 200 บาท บอทจะจัดการปิดให้อัตโนมัติครับ"
                    )
                    try:
                        bot.send_message(TELEGRAM_CHAT_ID, alert_msg, parse_mode='Markdown')
                        alerted_campaigns_today.add(camp_id)
                    except Exception as e:
                        print(f"Error sending alert: {e}")
            
            # C. ระบบ Auto-Kill ขั้นเด็ดขาด: หากทะลุ 200 บาทแล้วยัง 0 ROAS ปิดอัตโนมัติทันที
            if spend > 200.0 and roas == 0.0:
                url = f"https://graph.facebook.com/v18.0/{camp_id}"
                payload = {'access_token': my_access_token, 'status': 'PAUSED'}
                res = requests.post(url, data=payload).json()
                
                # เช็คว่าเคยส่งแจ้งเตือนยัง เพื่อไม่ให้ยิงข้อความซ้ำรัวๆ
                kill_key = f"killed_{camp_id}"
                if kill_key not in scale_alerted_today:
                    kill_msg = (
                        f"🛑 *[AUTO-KILL] ตัดไฟต้นลม ปิดแคมเปญให้อัตโนมัติ!*\n\n"
                        f"🎯 *แคมเปญ:* {camp_name}\n"
                        f"💰 *เผางบไปถึง:* {spend:,.2f} บาท (เกินขีดจำกัด 200 บาท)\n"
                        f"❌ *สถานะ:* 0 ROAS บอทสั่ง Pause หยุดการเผาเงินเรียบร้อยแล้วครับ!"
                    )
                    try:
                        bot.send_message(TELEGRAM_CHAT_ID, kill_msg, parse_mode='Markdown')
                        scale_alerted_today.add(kill_key)
                    except Exception as e:
                        print(f"Error sending kill msg: {e}")

# --- 5. ระบบรายงานสรุปย่อยระหว่างวันทุก 4 ชั่วโมง ---
def job_mini_summary():
    print("⏰ กำลังส่งรายงานสรุปย่อยระหว่างวัน...")
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    
    acc_url = f"https://graph.facebook.com/v18.0/{my_account_id}/insights"
    acc_params = {
        'access_token': my_access_token,
        'time_range': f'{{"since":"{today_str}","until":"{today_str}"}}',
        'fields': 'spend,purchase_roas,action_values'
    }
    acc_res = requests.get(acc_url, params=acc_params).json().get('data', [])
    
    spend = 0.0
    conv = 0.0
    roas = 0.0
    if acc_res:
        spend = float(acc_res[0].get('spend', 0))
        roas_list = acc_res[0].get('purchase_roas', [])
        if roas_list:
            roas = float(roas_list[0].get('value', 0))
        for item in acc_res[0].get('action_values', []):
            if item.get('action_type') in ['omni_purchase', 'purchase', 'offsite_conversion.fb_pixel_purchase']:
                conv += float(item.get('value', 0))
                
    summary_msg = (
        f"⏱️ *[Smart Mini-Summary] สรุปผลภาพรวมระหว่างวัน*\n"
        f"🗓️ วันที่: {today_str}\n"
        f"-----------------------------------\n"
        f"💰 ยอดใช้จ่ายรวมวันนี้: {spend:,.2f} บาท\n"
        f"🛒 ยอดขาย/คอนเวอร์ชั่น: {conv:,.2f} บาท\n"
        f"📈 ROAS เฉลี่ยรวม: {roas:.2f}\n"
        f"-----------------------------------\n"
        f"💡 บอทยังคงสแกนแคมเปญใหม่ทุก 2 ชั่วโมงเพื่อความปลอดภัยครับ"
    )
    try:
        bot.send_message(TELEGRAM_CHAT_ID, summary_msg, parse_mode='Markdown')
    except Exception as e:
        print(f"Error sending mini-summary: {e}")

# --- 6. จัดการคำสั่งและข้อความใน Telegram ---
@bot.message_handler(commands=['report'])
def handle_report_command(message):
    args = message.text.split()
    date_arg = args[1] if len(args) > 1 else None
    bot.reply_to(message, "⏳ กำลังประมวลผลรายงานวิเคราะห์ กรุณารอสักครู่...")
    report_msg = generate_report_text(date_arg)
    bot.send_message(message.chat.id, report_msg, parse_mode='Markdown')

@bot.message_handler(commands=['active'])
def handle_active_command(message):
    bot.reply_to(message, "⏳ กำลังดึงรายชื่อแคมเปญที่กำลังรันอยู่ทั้งหมด...")
    camp_url = f"https://graph.facebook.com/v18.0/{my_account_id}/campaigns"
    camp_params = {
        'access_token': my_access_token,
        'effective_status': '["ACTIVE"]',
        'fields': 'name,daily_budget'
    }
    active_campaigns = requests.get(camp_url, params=camp_params).json().get('data', [])
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    
    lines = [f"🟢 *แคมเปญที่กำลัง Active อยู่ขณะนี้ ({len(active_campaigns)} แคมเปญ):*", "-----------------------------------"]
    for camp in active_campaigns:
        c_id = camp['id']
        c_name = camp['name']
        d_budget = float(camp.get('daily_budget', 0)) / 100 if camp.get('daily_budget') else 0.0
        
        # ดึงยอดใช้วันนี้สั้นๆ
        ins = requests.get(f"https://graph.facebook.com/v18.0/{c_id}/insights", params={'access_token': my_access_token, 'time_range': f'{{"since":"{today_str}","until":"{today_str}"}}', 'fields': 'spend,purchase_roas'}).json().get('data', [])
        sp = float(ins[0].get('spend', 0)) if ins else 0.0
        rs = float(ins[0].get('purchase_roas', [{}])[0].get('value', 0)) if ins and ins[0].get('purchase_roas') else 0.0
        
        b_text = f"{d_budget:,.0f}บ./วัน" if d_budget > 0 else "CBO/ไม่อั้น"
        lines.append(f"• *{c_name}*\n  ⚙️ งบ: {b_text} | 💰 ใช้ไป: {sp:,.2f}บ. | 📈 ROAS: {rs:.2f}")
        
    bot.send_message(message.chat.id, "\n".join(lines), parse_mode='Markdown')

@bot.message_handler(commands=['check'])
def handle_check_command(message):
    bot.reply_to(message, "🔍 กำลังสั่งรันระบบตรวจสอบแคมเปญวิกฤตทันที...")
    job_check_budget_alerts()
    bot.send_message(message.chat.id, "✅ ตรวจสอบสถานะแคมเปญใหม่เสร็จสิ้นเรียบร้อยแล้วครับ ไม่มีแคมเปญวิกฤตเพิ่มเติม หรือระบบได้แจ้งเตือนไปแล้ว")

@bot.message_handler(func=lambda message: True)
def handle_text_messages(message):
    global latest_crisis_campaigns
    text = message.text.strip()
    
    if "ปิดแคมเปญที่พึ่งขึ้นใหม่" in text:
        if not latest_crisis_campaigns:
            bot.reply_to(message, "⚠️ ไม่พบแคมเปญใหม่ที่เข้าข่ายวิกฤต หรือถูกปิดไปหมดแล้วครับ")
            return
            
        closed_names = []
        for camp in latest_crisis_campaigns:
            c_id = camp['id']
            c_name = camp['name']
            url = f"https://graph.facebook.com/v18.0/{c_id}"
            payload = {'access_token': my_access_token, 'status': 'PAUSED'}
            requests.post(url, data=payload)
            closed_names.append(c_name)
            
        bot.reply_to(message, f"🛑 ปิดแคมเปญใหม่ที่เผางบเรียบร้อยแล้ว:\n" + "\n".join([f"• {n}" for n in closed_names]), parse_mode='Markdown')
        latest_crisis_campaigns.clear()
    else:
        bot.reply_to(message, "🤖 คำสั่งไม่ถูกต้อง\n• พิมพ์ `/report` ดูรายงาน\n• พิมพ์ `/active` ดูแคมเปญที่รันอยู่\n• พิมพ์ `/check` สั่งเช็ควิกฤตด่วน\n• หรือพิมพ์ `ปิดแคมเปญที่พึ่งขึ้นใหม่` เพื่อสั่งปิดแคมเปญวิกฤต")

# --- 7. ตั้งเวลาทำงานเบื้องหลัง (Schedule Tasks) ---
def job_send_daily_report():
    print("⏰ กำลังส่งรายงานอัตโนมัติประจำวัน...")
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    yesterday_str = yesterday.strftime('%d/%m/') + str(yesterday.year + 543)[-2:]
    
    report_msg = generate_report_text(yesterday_str)
    bot.send_message(TELEGRAM_CHAT_ID, report_msg, parse_mode='Markdown')

def run_schedule():
    schedule.every().day.at("08:00").do(job_send_daily_report)
    schedule.every(2).hours.do(job_check_budget_alerts)  # ตรวจสอบวิกฤต/ปัง ทุก 2 ชั่วโมง
    schedule.every(4).hours.do(job_mini_summary)         # สรุปผลย่อยระหว่างวันทุก 4 ชั่วโมง
    
    while True:
        schedule.run_pending()
        time.sleep(1)

schedule_thread = threading.Thread(target=run_schedule)
schedule_thread.daemon = True
schedule_thread.start()

# --- 8. เปิดสแตนด์บายบอท ---
print("🤖 Bot is running with Advanced Pro Features (Auto-Kill, Scale Alert, Commands)...")
bot.infinity_polling()
