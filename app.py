import streamlit as st
import pandas as pd
import hashlib
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px
from datetime import datetime, date, time, timedelta
import pytz
import os
import urllib.parse

# ==========================================
# 0. ตั้งค่า Timezone (เวลาประเทศไทย)
# ==========================================
TH_TIMEZONE = pytz.timezone('Asia/Bangkok')

def get_current_thai_time():
    now_utc = datetime.now(pytz.utc)
    now_th = now_utc.astimezone(TH_TIMEZONE)
    return now_th.strftime("%Y-%m-%d %H:%M:%S")

os.makedirs("downloads", exist_ok=True)

# ==========================================
# 1. เชื่อมต่อ Google Sheets & Drive ผ่าน Streamlit Secrets
# ==========================================
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

@st.cache_resource
def init_google_services():
    try:
        secret_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(secret_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("DebtDatabase")
        return sheet, creds
    except Exception as e:
        st.error(f"⚠️ ไม่สามารถเชื่อมต่อ Google Sheets ได้: {e}")
        return None, None

sh, creds = init_google_services()

def get_data_from_sheet(worksheet_name):
    if sh is None:
        return pd.DataFrame()
    try:
        worksheet = sh.worksheet(worksheet_name)
        data = worksheet.get_all_records()
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame()

def append_to_sheet(worksheet_name, row_data):
    if sh is not None:
        worksheet = sh.worksheet(worksheet_name)
        worksheet.append_row(row_data)

def delete_row_from_sheet(worksheet_name, row_index):
    if sh is not None:
        worksheet = sh.worksheet(worksheet_name)
        worksheet.delete_rows(row_index)

def update_or_add_setting(username, theme_name, welcome_msg, bg_image=""):
    if sh is not None:
        try:
            ws = sh.worksheet("settings")
            data = ws.get_all_records()
            df = pd.DataFrame(data)
            
            if not df.empty and "username" in df.columns:
                cell = ws.find(username)
                if cell:
                    ws.delete_rows(cell.row)
            
            ws.append_row([username, theme_name, welcome_msg, bg_image])
        except Exception:
            pass

def get_user_setting(username):
    df_set = get_data_from_sheet("settings")
    if not df_set.empty and "username" in df_set.columns:
        user_row = df_set[df_set["username"] == username]
        if not user_row.empty:
            return user_row.iloc[0].to_dict()
    return {
        "theme_name": "🔴 Crimson Red (แดงเพลิงโฉบเฉี่ยว)", 
        "welcome_msg": "ยินดีต้อนรับสู่ระบบจัดการลูกหนี้ระดับ Ultimate Pro",
        "bg_image": ""
    }

def upload_slip_to_drive(uploaded_file, folder_name="DebtSlips"):
    if uploaded_file is None or creds is None:
        return ""
    try:
        import googleapiclient.discovery
        from googleapiclient.http import MediaIoBaseUpload
        import io

        service = googleapiclient.discovery.build('drive', 'v3', credentials=creds)
        folder_id = None
        response = service.files().list(q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false").execute()
        files = response.get('files', [])
        if files:
            folder_id = files[0]['id']
        else:
            folder_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
            folder = service.files().create(body=folder_metadata, fields='id').execute()
            folder_id = folder.get('id')

        file_metadata = {'name': f"slip_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_file.name}", 'parents': [folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(uploaded_file.getvalue()), mimetype=uploaded_file.type, resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink, webContentLink').execute()
        service.permissions().create(fileId=file['id'], body={'role': 'reader', 'type': 'anyone'}).execute()
        return file.get('webViewLink', '')
    except Exception:
        return f"แนบไฟล์แล้ว ({uploaded_file.name})"

# ==========================================
# 2. ชุดธีมสีมาตรฐาน (Theme Palettes)
# ==========================================
THEME_PALETTES = {
    "🔴 Crimson Red (แดงเพลิงโฉบเฉี่ยว)": {
        "primary": "#ff4b4b", "primary_hover": "#ff6b6b", "glow": "rgba(255, 75, 75, 0.5)", "card_bg": "rgba(25, 28, 36, 0.7)", "border": "rgba(255, 75, 75, 0.4)"
    },
    "⚡ Cyber Blue (ฟ้าไซเบอร์ล้ำอนาคต)": {
        "primary": "#00d2ff", "primary_hover": "#3addff", "glow": "rgba(0, 210, 255, 0.5)", "card_bg": "rgba(25, 28, 36, 0.7)", "border": "rgba(0, 210, 255, 0.4)"
    },
    "🟢 Neon Emerald (เขียวมรกตเรืองแสง)": {
        "primary": "#00ff87", "primary_hover": "#33ff9f", "glow": "rgba(0, 255, 135, 0.5)", "card_bg": "rgba(25, 28, 36, 0.7)", "border": "rgba(0, 255, 135, 0.4)"
    },
    "🟣 Royal Purple (ม่วงพรีเมียมหรูหรา)": {
        "primary": "#9d4edd", "primary_hover": "#b565ff", "glow": "rgba(157, 78, 221, 0.5)", "card_bg": "rgba(25, 28, 36, 0.7)", "border": "rgba(157, 78, 221, 0.4)"
    },
    "🟡 Golden Amber (เหลืองทองคำเด่นชัด)": {
        "primary": "#ffb703", "primary_hover": "#ffd166", "glow": "rgba(255, 183, 3, 0.5)", "card_bg": "rgba(25, 28, 36, 0.7)", "border": "rgba(255, 183, 3, 0.4)"
    }
}

# ==========================================
# 3. ระบบ Login & UI Setup พร้อมเอฟเฟกต์คลิก/โฮเวอร์สุดลื่นไหล
# ==========================================
st.set_page_config(page_title="ระบบจัดการลูกหนี้ Ultimate Pro", page_icon="⚡", layout="wide")

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""

current_user = st.session_state["username"]
user_setting = get_user_setting(current_user) if st.session_state["logged_in"] else {"theme_name": "🔴 Crimson Red (แดงเพลิงโฉบเฉี่ยว)", "bg_image": ""}

def apply_custom_css(setting):
    theme_key = setting.get("theme_name", "🔴 Crimson Red (แดงเพลิงโฉบเฉี่ยว)")
    if theme_key not in THEME_PALETTES:
        theme_key = "🔴 Crimson Red (แดงเพลิงโฉบเฉี่ยว)"
    t = THEME_PALETTES[theme_key]
    bg_image = setting.get("bg_image", "")
    
    bg_style = "background-color: #0b0f19;"
    if bg_image.strip() != "":
        bg_style = f"background-image: linear-gradient(rgba(11,15,25,0.88), rgba(11,15,25,0.88)), url('{bg_image}'); background-size: cover; background-position: center; background-attachment: fixed;"

    custom_css = f"""
    <style>
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(8px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        @keyframes pulseGlow {{
            0% {{ box-shadow: 0 0 0 0 {t['glow']}; }}
            70% {{ box-shadow: 0 0 0 10px rgba(0,0,0,0); }}
            100% {{ box-shadow: 0 0 0 0 rgba(0,0,0,0); }}
        }}

        .stApp {{
            {bg_style}
            animation: fadeIn 0.5s ease-out;
        }}

        /* เอฟเฟกต์ปุ่มกด ขยับและเรืองแสง */
        div.stButton > button {{
            background: linear-gradient(135deg, {t['primary']} 0%, {t['primary_hover']} 100%) !important;
            color: #ffffff !important;
            border: none !important;
            border-radius: 12px !important;
            font-weight: 700 !important;
            padding: 0.55rem 1.1rem !important;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3) !important;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
        }}
        div.stButton > button:hover {{
            transform: translateY(-3px) scale(1.02) !important;
            box-shadow: 0 6px 20px {t['glow']} !important;
            animation: pulseGlow 1.2s infinite;
        }}
        div.stButton > button:active {{
            transform: translateY(1px) scale(0.98) !important;
        }}

        /* แต่ง Radio Sidebar ให้ปุ่มเมนูน่ากด มีเอฟเฟกต์เปลี่ยนสีเมื่อเอาเมาส์ชี้ */
        [data-testid="stSidebar"] .stRadio label {{
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 10px;
            padding: 8px 12px;
            margin-bottom: 6px;
            transition: all 0.25s ease;
            cursor: pointer;
            display: block;
        }}
        [data-testid="stSidebar"] .stRadio label:hover {{
            background: {t['card_bg']};
            border-color: {t['primary']};
            transform: translateX(4px);
            box-shadow: 0 4px 12px {t['glow']};
        }}

        /* กล่อง Input ฟอร์ม */
        .stTextInput input, .stNumberInput input, .stSelectbox select, .stDateInput input, .stTimeInput input {{
            background-color: rgba(255, 255, 255, 0.04) !important;
            border: 1px solid rgba(255, 255, 255, 0.12) !important;
            border-radius: 10px !important;
            color: #ffffff !important;
            transition: all 0.3s ease !important;
        }}
        .stTextInput input:focus, .stNumberInput input:focus, .stSelectbox select:focus {{
            border-color: {t['primary']} !important;
            box-shadow: 0 0 10px {t['glow']} !important;
        }}

        /* การ์ดสถิติ (Metric Cards) ขยับลอยได้เมื่อชี้เมาส์ */
        [data-testid="stMetric"] {{
            background: {t['card_bg']};
            backdrop-filter: blur(14px);
            padding: 18px;
            border-radius: 16px;
            border: 1px solid {t['border']};
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.35);
            transition: all 0.3s ease;
        }}
        [data-testid="stMetric"]:hover {{
            transform: translateY(-6px);
            border-color: {t['primary']};
            box-shadow: 0 12px 30px {t['glow']};
        }}

        [data-testid="stSidebar"] {{
            background-color: rgba(11, 15, 25, 0.96);
            backdrop-filter: blur(10px);
            border-right: 1px solid rgba(255, 255, 255, 0.08);
        }}
    </style>
    """
    st.markdown(custom_css, unsafe_allow_html=True)

apply_custom_css(user_setting)

def login_screen():
    st.title("⚡ ระบบจัดการลูกหนี้ Ultimate Pro (All-in-One)")
    st.markdown("กรุณาเข้าสู่ระบบเพื่อจัดการข้อมูลของคุณ")
    with st.container():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("login_form"):
                username = st.text_input("Username (ชื่อผู้ใช้)")
                password = st.text_input("Password (รหัสผ่าน)", type="password")
                submit = st.form_submit_button("🚀 เข้าสู่ระบบ", use_container_width=True)
                if submit:
                    df_users = get_data_from_sheet("users")
                    hashed_pw = hashlib.sha256(password.encode()).hexdigest()
                    if df_users.empty:
                        sh.worksheet("users").append_row(["admin", hashlib.sha256("1234".encode()).hexdigest(), "admin"])
                        df_users = get_data_from_sheet("users")
                    user_row = df_users[(df_users["username"] == username) & (df_users["password"] == hashed_pw)]
                    if not user_row.empty:
                        st.session_state["logged_in"] = True
                        st.session_state["username"] = username
                        st.success("เข้าสู่ระบบสำเร็จ!")
                        st.rerun()
                    else:
                        st.error("❌ ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

if not st.session_state["logged_in"]:
    login_screen()
else:
    current_user = st.session_state["username"]
    user_setting = get_user_setting(current_user)
    custom_welcome = user_setting.get("welcome_msg", "ยินดีต้อนรับ")

    st.sidebar.markdown(f"👤 **ผู้ใช้งาน:** `{current_user}`")
    st.sidebar.markdown(f"✨ *{custom_welcome}*")
    if st.sidebar.button("🚪 ออกจากระบบ", use_container_width=True):
        st.session_state["logged_in"] = False
        st.session_state["username"] = ""
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.markdown("📂 **เมนูการใช้งานหลัก:**")
    
    # Sidebar แสดงปุ่มเลือกเมนูแบบครบทุกรายการ กดจิ้มได้ทันที
    menu = st.sidebar.radio("", [
        "📊 หน้าสรุปภาพรวม & กราฟสัดส่วน", 
        "🔍 เจาะลึกโปรไฟล์ลูกหนี้รายบุคคล",
        "📅 ปฏิทินติดตามการทำธุรกรรม",
        "➕ บันทึกยอดกู้ใหม่ (เลือกเวลาได้)", 
        "✏️ จัดการ/แก้ไข/ลบรายการกู้",
        "💵 บันทึกรับชำระ (ตัดดอกเบี้ยก่อน)",
        "📄 ประวัติรับชำระ & ออกใบเสร็จ",
        "💬 สร้างข้อความแจ้งเตือน LINE",
        "🎨 ตั้งค่าธีมสีและ Background",
        "👥 จัดการผู้ใช้งาน"
    ], label_visibility="collapsed")

    # ฟังก์ชันช่วยเลือกวันเวลาด้วย Checkbox (ปัจจุบัน vs ปฏิทินย้อนหลัง)
    def handle_datetime_input(key_prefix):
        st.markdown("🕒 **กำหนดวันและเวลาบันทึกรายการ:**")
        use_custom_date = st.checkbox("📅 เลือกวันที่และเวลาย้อนหลัง (เปิดปฏิทิน)", value=False, key=f"{key_prefix}_chk")
        if use_custom_date:
            c1, c2 = st.columns(2)
            with c1:
                selected_date = st.date_input("เลือกวันที่", value=date.today(), key=f"{key_prefix}_date")
            with c2:
                selected_time = st.time_input("เลือกเวลา", value=datetime.now().time(), key=f"{key_prefix}_time")
            combined_dt = datetime.combine(selected_date, selected_time)
            return combined_dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            return get_current_thai_time()

    current_buddhist_year = datetime.now(TH_TIMEZONE).year + 543
    buddhist_years_list = [str(y) for y in range(current_buddhist_year - 5, current_buddhist_year + 6)]

    # เมนู 1: หน้าสรุปภาพรวมพร้อม Smart Alert Banner
    if menu == "📊 หน้าสรุปภาพรวม & กราฟสัดส่วน":
        st.header(f"📊 สรุปยอดลูกหนี้ & ระบบประเมินความเสี่ยง - ({current_user})")
        
        df_loans = get_data_from_sheet("loans")
        df_payments = get_data_from_sheet("payments")

        if not df_loans.empty and "date_time" in df_loans.columns:
            today_date = datetime.now(TH_TIMEZONE).date()
            urgent_alerts = []
            
            for idx, row in df_loans.iterrows():
                try:
                    loan_dt = pd.to_datetime(row["date_time"]).tz_localize(TH_TIMEZONE).date() if pd.to_datetime(row["date_time"]).tz is None else pd.to_datetime(row["date_time"]).astimezone(TH_TIMEZONE).date()
                    days_passed = (today_date - loan_dt).days
                    days_left = 30 - (days_passed % 30)
                    
                    if 0 <= days_left <= 3:
                        urgent_alerts.append(f"🚨 **แจ้งเตือนด่วน!** ลูกหนี้ **{row['debtor_name']}** จะครบกำหนดชำระในอีก **{days_left} วัน** (ยอดกู้: {row['total_due']:,.2f} ฿)")
                except Exception:
                    pass
            
            if urgent_alerts:
                st.warning("### ⚠️ ประกาศเตือนกำหนดชำระใกล้ถึงกำหนด (<= 3 วัน)")
                for alert_msg in set(urgent_alerts):
                    st.error(alert_msg)

        if df_loans.empty:
            st.info("💡 ยังไม่มีข้อมูลในระบบ เริ่มบันทึกยอดกู้ได้ที่เมนูด้านข้างครับ")
        else:
            years = sorted(df_loans["buddhist_year"].astype(str).unique().tolist()) if "buddhist_year" in df_loans.columns else ["ทั้งหมด"]
            selected_year = st.selectbox("📅 เลือกปี พ.ศ. ที่ต้องการตรวจสอบ", ["ทั้งหมด"] + years)

            if selected_year != "ทั้งหมด" and "buddhist_year" in df_loans.columns:
                df_loans = df_loans[df_loans["buddhist_year"].astype(str) == selected_year]
                if not df_payments.empty and "buddhist_year" in df_payments.columns:
                    df_payments = df_payments[df_payments["buddhist_year"].astype(str) == selected_year]

            summary_loans = df_loans.groupby("debtor_name")[["principal", "interest", "total_due"]].sum().reset_index()
            
            debtor_balances = []
            for idx, row in summary_loans.iterrows():
                d_name = row["debtor_name"]
                init_p = row["principal"]
                init_i = row["interest"]
                
                total_paid_by_debtor = 0
                payment_count = 0
                if not df_payments.empty and "debtor_name" in df_payments.columns:
                    p_rows = df_payments[df_payments["debtor_name"] == d_name]
                    if not p_rows.empty and "paid_amount" in p_rows.columns:
                        total_paid_by_debtor = p_rows["paid_amount"].sum()
                        payment_count = len(p_rows)

                paid_to_interest = min(init_i, total_paid_by_debtor)
                remainder_after_interest = max(0, total_paid_by_debtor - init_i)
                paid_to_principal = min(init_p, remainder_after_interest)
                
                remaining_interest = init_i - paid_to_interest
                remaining_principal = init_p - paid_to_principal
                remaining_total = remaining_interest + remaining_principal

                if remaining_total <= 0:
                    risk_grade = "🟢 เกรด A (ชำระครบ ไร้ความเสี่ยง)"
                elif payment_count > 0:
                    risk_grade = "🟡 เกรด B (กำลังทยอยผ่อน)"
                else:
                    risk_grade = "🔴 เกรด C (ยังไม่มีประวัติ/เสี่ยงสูง)"

                u_line = "ไม่มีข้อมูล"
                if "line_id" in df_loans.columns:
                    l_rows = df_loans[df_loans["debtor_name"] == d_name]
                    if not l_rows.empty and "line_id" in l_rows.columns:
                        val = l_rows.iloc[0]["line_id"]
                        u_line = val if val else "ไม่ได้ระบุ"

                debtor_balances.append({
                    "debtor_name": d_name,
                    "line_id": u_line,
                    "principal": init_p,
                    "interest": init_i,
                    "total_due": init_p + init_i,
                    "total_paid": total_paid_by_debtor,
                    "remaining": remaining_total,
                    "risk_score": risk_grade,
                    "status": "✅ ชำระครบแล้ว" if remaining_total <= 0 else "⚠️ ยังค้างชำระ"
                })

            df_summary = pd.DataFrame(debtor_balances)
            st.subheader("📋 ตารางสรุปภาพรวมยอดหนี้")
            st.dataframe(df_summary.rename(columns={
                "debtor_name": "ชื่อลูกหนี้", "line_id": "LINE ID", "principal": "เงินต้นตั้งต้น",
                "interest": "ดอกเบี้ยตั้งต้น", "total_due": "ยอดสุทธิทั้งหมด", "total_paid": "จ่ายแล้ว",
                "remaining": "ยอดหนี้คงเหลือสุทธิ", "risk_score": "เกรดความเสี่ยง", "status": "สถานะ"
            }), use_container_width=True)

            st.markdown("---")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("📌 เงินต้นรวมทั้งหมด", f"{df_summary['principal'].sum():,.2f} ฿")
            col2.metric("📈 ดอกเบี้ยรวมทั้งหมด", f"{df_summary['interest'].sum():,.2f} ฿")
            col3.metric("💵 จ่ายคืนรวมทั้งหมด", f"{df_summary['total_paid'].sum():,.2f} ฿")
            col4.metric("🚨 ยอดหนี้คงเหลือสุทธิ", f"{df_summary['remaining'].sum():,.2f} ฿")

    # เมนู 2: เจาะลึกโปรไฟล์ลูกหนี้รายบุคคล พร้อมคำนวณวันครบกำหนดชำระอัตโนมัติ
    elif menu == "🔍 เจาะลึกโปรไฟล์ลูกหนี้รายบุคคล":
        st.header("🔍 ตรวจสอบโปรไฟล์และคำนวณวันครบกำหนดชำระรายบุคคล")
        df_loans = get_data_from_sheet("loans")
        df_payments = get_data_from_sheet("payments")

        if df_loans.empty:
            st.info("ยังไม่มีข้อมูลลูกหนี้ในระบบ")
        else:
            debtors_list = df_loans["debtor_name"].unique().tolist()
            target_debtor = st.selectbox("📌 เลือกลูกหนี้ที่ต้องการเจาะลึก", debtors_list)

            if target_debtor:
                u_loans = df_loans[df_loans["debtor_name"] == target_debtor]
                u_payments = df_payments[df_payments["debtor_name"] == target_debtor] if not df_payments.empty and "debtor_name" in df_payments.columns else pd.DataFrame()

                t_prin = u_loans["principal"].sum()
                t_inte = u_loans["interest"].sum()
                t_paid = u_payments["paid_amount"].sum() if not u_payments.empty else 0

                paid_i = min(t_inte, t_paid)
                rem_i = max(0, t_inte - paid_i)
                rem_p = max(0, t_prin - max(0, t_paid - t_inte))
                rem_tot = rem_i + rem_p

                # คำนวณวันครบกำหนดชำระจากวันที่ทำรายการล่าสุด
                latest_loan_time_str = u_loans.iloc[0].get("date_time", str(datetime.now()))
                try:
                    loan_dt_obj = pd.to_datetime(latest_loan_time_str)
                    next_due_date = loan_dt_obj + timedelta(days=30)
                    today_dt = datetime.now()
                    days_to_due = (next_due_date - today_dt).days
                    due_msg = f"รอบถัดไปวันที่ **{next_due_date.strftime('%d/%m/%Y')}** (เหลืออีกประมาณ **{max(0, days_to_due)} วัน**)"
                except Exception:
                    due_msg = "ไม่สามารถคำนวณได้"

                u_line = "ไม่ได้ระบุ"
                if "line_id" in u_loans.columns and not u_loans.empty:
                    val = u_loans.iloc[0].get("line_id", "")
                    if val:
                        u_line = val

                st.markdown(f"### 👤 ข้อมูลเชิงลึกของ: `{target_debtor}`")
                c1, c2 = st.columns(2)
                c1.markdown(f"💬 **LINE ID / เบอร์ติดต่อ:** `{u_line}`")
                c2.markdown(f"📅 **กำหนดชำระถัดไป:** {due_msg}")

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("📌 เงินต้นรวม", f"{t_prin:,.2f} ฿")
                m2.metric("📈 ดอกเบี้ยรวม", f"{t_inte:,.2f} ฿")
                m3.metric("💵 จ่ายแล้ว", f"{t_paid:,.2f} ฿")
                m4.metric("🚨 คงเหลือสุทธิ", f"{rem_tot:,.2f} ฿")

                st.markdown("---")
                st.subheader("📌 ประวัติการกู้ยืม")
                st.dataframe(u_loans, use_container_width=True)

                st.subheader("💵 ประวัติการชำระเงิน")
                if not u_payments.empty:
                    st.dataframe(u_payments, use_container_width=True)
                else:
                    st.info("ยังไม่มีประวัติการชำระเงิน")

    # เมนู 3: ปฏิทินติดตามการทำธุรกรรม
    elif menu == "📅 ปฏิทินติดตามการทำธุรกรรม":
        st.header("📅 ปฏิทินติดตามความเคลื่อนไหวการกู้และจ่ายหนี้")
        df_loans = get_data_from_sheet("loans")
        df_payments = get_data_from_sheet("payments")

        t1, t2 = st.tabs(["📌 รายการกู้ยืมทั้งหมด", "💵 ประวัติรับชำระทั้งหมด"])
        with t1:
            if df_loans.empty:
                st.info("ไม่มีข้อมูล")
            else:
                st.dataframe(df_loans, use_container_width=True)
        with t2:
            if df_payments.empty:
                st.info("ไม่มีข้อมูล")
            else:
                st.dataframe(df_payments, use_container_width=True)

    # เมนู 4: บันทึกยอดกู้ใหม่ (เลือกเวลาได้ผ่าน Checkbox ปฏิทิน)
    elif menu == "➕ บันทึกยอดกู้ใหม่ (เลือกเวลาได้)":
        st.header("➕ บันทึกรายการยืมเงินใหม่")
        
        with st.form("loan_form_sheet"):
            buddhist_year = st.selectbox("ปี พ.ศ.", buddhist_years_list, index=buddhist_years_list.index(str(current_buddhist_year)) if str(current_buddhist_year) in buddhist_years_list else 0)
            debtor_name = st.text_input("ชื่อลูกหนี้")
            line_id = st.text_input("💬 (ทางเลือก) LINE ID หรือเบอร์ติดต่อลูกหนี้")
            principal = st.number_input("เงินต้นรอบนี้ (บาท)", min_value=0.0, step=100.0)
            rate = st.number_input("ดอกเบี้ย (%)", value=20.0, step=1.0)
            slip_file = st.file_uploader("📎 แนบสลิปหลักฐาน (PNG, JPG)", type=["png", "jpg", "jpeg"])
            
            st.markdown("---")
            final_date_time = handle_datetime_input("loan_dt")

            submitted = st.form_submit_button("💾 บันทึกยอดกู้", use_container_width=True)
            if submitted:
                if debtor_name and principal > 0:
                    slip_url = ""
                    if slip_file is not None:
                        with st.spinner("กำลังอัปโหลดสลิป..."):
                            slip_url = upload_slip_to_drive(slip_file)
                    
                    interest = principal * (rate / 100)
                    total_due = principal + interest
                    append_to_sheet("loans", [current_user, debtor_name, line_id, buddhist_year, final_date_time, principal, interest, total_due, slip_url])
                    st.success(f"✅ บันทึกยอดกู้ของ '{debtor_name}' สำเร็จเรียบร้อย!")
                else:
                    st.error("⚠️ กรุณากรอกข้อมูลให้ครบถ้วน")

    # เมนู 5: แก้ไข/ลบรายการกู้
    elif menu == "✏️ จัดการ/แก้ไข/ลบรายการกู้":
        st.header("✏️ จัดการรายการยืมเงิน")
        df_loans = get_data_from_sheet("loans")
        if df_loans.empty:
            st.info("ยังไม่มีข้อมูล")
        else:
            st.dataframe(df_loans, use_container_width=True)
            st.markdown("---")
            max_idx = max(0, len(df_loans) - 1)
            row_to_delete = st.number_input("ระบุลำดับแถว (Index) ที่ต้องการลบ", min_value=0, max_value=max_idx, step=1)
            if st.button("❌ ลบรายการนี้", type="primary"):
                delete_row_from_sheet("loans", int(row_to_delete) + 2)
                st.success("🗑 ลบรายการเรียบร้อย!")
                st.rerun()

    # เมนู 6: บันทึกรับชำระ + เลือกเวลาปฏิทิน
    elif menu == "💵 บันทึกรับชำระ (ตัดดอกเบี้ยก่อน)":
        st.header("💵 บันทึกรับชำระหนี้ (ระบบตัดดอกเบี้ยก่อน แล้วตัดต้น)")
        df_loans = get_data_from_sheet("loans")
        debtors_list = df_loans["debtor_name"].unique().tolist() if not df_loans.empty and "debtor_name" in df_loans.columns else []

        if not debtors_list:
            st.warning("⚠️ ยังไม่มีรายชื่อลูกหนี้ในระบบ")
        else:
            with st.form("payment_form_sheet"):
                buddhist_year = st.selectbox("ปี พ.ศ.", buddhist_years_list, index=buddhist_years_list.index(str(current_buddhist_year)) if str(current_buddhist_year) in buddhist_years_list else 0)
                debtor_name = st.selectbox("เลือกชื่อลูกหนี้", debtors_list)
                paid_amount = st.number_input("จำนวนเงินที่โอนจ่ายเข้ามา (บาท)", min_value=0.0, step=100.0)
                slip_file = st.file_uploader("📎 แนบสลิปชำระเงิน (PNG, JPG)", type=["png", "jpg", "jpeg"])
                
                st.markdown("---")
                final_date_time = handle_datetime_input("payment_dt")

                submitted = st.form_submit_button("💵 บันทึกรับชำระ", use_container_width=True)
                if submitted:
                    if paid_amount > 0:
                        slip_url = ""
                        if slip_file is not None:
                            with st.spinner("กำลังอัปโหลดสลิป..."):
                                slip_url = upload_slip_to_drive(slip_file, folder_name="PaymentSlips")
                        
                        append_to_sheet("payments", [current_user, debtor_name, buddhist_year, final_date_time, paid_amount, slip_url])
                        st.success(f"💵 บันทึกรับชำระจาก '{debtor_name}' จำนวน {paid_amount:,.2f} บาท สำเร็จ!")
                    else:
                        st.error("⚠️ กรุณากรอกจำนวนเงินให้มากกว่า 0")

    # เมนู 7: ประวัติรับชำระ & ออกใบเสร็จ
    elif menu == "📄 ประวัติรับชำระ & ออกใบเสร็จ":
        st.header("📄 ประวัติการรับชำระเงินและออกใบเสร็จดิจิทัล")
        df_payments = get_data_from_sheet("payments")
        df_loans = get_data_from_sheet("loans")

        if df_payments.empty:
            st.info("ยังไม่มีประวัติการชำระเงิน")
        else:
            st.dataframe(df_payments, use_container_width=True)
            st.markdown("---")
            
            st.subheader("🧾 สร้างใบเสร็จรับเงิน")
            selected_idx = st.number_input("ระบุลำดับแถว (Index) ที่ต้องการออกใบเสร็จ", min_value=0, max_value=max(0, len(df_payments)-1), step=1)
            
            if st.button("🖨️ สร้างใบเสร็จรับเงิน"):
                row_p = df_payments.iloc[int(selected_idx)]
                p_name = row_p["debtor_name"]
                p_amount = row_p["paid_amount"]
                p_time = row_p["date_time"]
                
                user_loans = df_loans[df_loans["debtor_name"] == p_name]
                tot_p = user_loans["principal"].sum() if not user_loans.empty else 0
                tot_i = user_loans["interest"].sum() if not user_loans.empty else 0
                all_p_user = df_payments[df_payments["debtor_name"] == p_name]["paid_amount"].sum()
                
                paid_i = min(tot_i, all_p_user)
                rem_i = max(0, tot_i - paid_i)
                rem_p = max(0, tot_p - max(0, all_p_user - tot_i))
                
                receipt_text = f"""
                ========================================
                      📜 ใบเสร็จรับเงิน / หลักฐานการชำระหนี้
                ========================================
                📅 วันที่ทำรายการ: {p_time}
                👤 ชื่อลูกหนี้: {p_name}
                💰 จำนวนเงินที่ชำระงวดนี้: {p_amount:,.2f} บาท
                ----------------------------------------
                📌 สรุปยอดหนี้คงเหลือหลังหักชำระ:
                • ดอกเบี้ยคงค้าง: {rem_i:,.2f} บาท
                • เงินต้นคงค้าง: {rem_p:,.2f} บาท
                • ยอดหนี้สุทธิรวม: {rem_i + rem_p:,.2f} บาท
                ========================================
                ผู้บันทึก: {current_user}
                """
                st.code(receipt_text, language="text")
                st.download_button("📥 ดาวน์โหลดใบเสร็จ (.txt)", data=receipt_text.encode('utf-8-sig'), file_name=f"receipt_{p_name}.txt", mime="text/plain")

            st.markdown("---")
            p_del = st.number_input("ระบุ Index ประวัติชำระที่ต้องการลบ", min_value=0, max_value=max(0, len(df_payments)-1), step=1, key="del_pay")
            if st.button("❌ ลบประวัติการรับชำระนี้", type="primary"):
                delete_row_from_sheet("payments", int(p_del) + 2)
                st.success("🗑️ ลบประวัติสำเร็จ!")
                st.rerun()

    # เมนู 8: สร้างข้อความแจ้งเตือน LINE
    elif menu == "💬 สร้างข้อความแจ้งเตือน LINE":
        st.header("💬 สร้างข้อความทวงหนี้ / แจ้งเตือนส่งทาง LINE")
        df_loans = get_data_from_sheet("loans")
        df_payments = get_data_from_sheet("payments")

        if df_loans.empty:
            st.info("ยังไม่มีข้อมูลลูกหนี้")
        else:
            debtors_list = df_loans["debtor_name"].unique().tolist()
            selected_debtor = st.selectbox("📌 เลือกลูกหนี้ที่ต้องการสร้างข้อความส่ง LINE", debtors_list)

            if selected_debtor:
                user_loans = df_loans[df_loans["debtor_name"] == selected_debtor]
                tot_p = user_loans["principal"].sum()
                tot_i = user_loans["interest"].sum()
                
                u_line = "ไม่ได้ระบุ"
                if "line_id" in user_loans.columns and not user_loans.empty:
                    val = user_loans.iloc[0].get("line_id", "")
                    if val:
                        u_line = val

                total_paid_by_debtor = 0
                if not df_payments.empty and "debtor_name" in df_payments.columns:
                    p_rows = df_payments[df_payments["debtor_name"] == selected_debtor]
                    if not p_rows.empty and "paid_amount" in p_rows.columns:
                        total_paid_by_debtor = p_rows["paid_amount"].sum()

                paid_to_interest = min(tot_i, total_paid_by_debtor)
                remainder_after_interest = max(0, total_paid_by_debtor - tot_i)
                paid_to_principal = min(tot_p, remainder_after_interest)
                
                rem_i = tot_i - paid_to_interest
                rem_p = tot_p - paid_to_principal
                rem_total = rem_i + rem_p

                line_notice_text = f"""🔔 แจ้งเตือนยอดชำระ / สรุปยอดหนี้
👤 เรียนคุณ: {selected_debtor}
💬 LINE ID: {u_line}
----------------------------------------
📌 เงินต้นคงเหลือ: {rem_p:,.2f} บาท
📈 ดอกเบี้ยคงค้าง: {rem_i:,.2f} บาท
💰 ยอดหนี้สุทธิรวมทั้งหมด: {rem_total:,.2f} บาท
💵 ชำระมาแล้วรวม: {total_paid_by_debtor:,.2f} บาท
----------------------------------------
📅 กรุณาชำระตามกำหนดเวลา ขอบคุณครับ 🙏"""

                st.code(line_notice_text, language="text")
                encoded_msg = urllib.parse.quote(line_notice_text)
                line_url = f"https://line.me/R/msg/text/?{encoded_msg}"
                
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"[📲 คลิกส่งผ่าน LINE (เปิดแอป LINE)]({line_url})", unsafe_allow_html=True)
                with c2:
                    st.download_button("📥 ดาวน์โหลดข้อความ (.txt)", data=line_notice_text.encode('utf-8-sig'), file_name=f"line_{selected_debtor}.txt", mime="text/plain")

    # เมนู 9: ตั้งค่าธีมสีและ Background
    elif menu == "🎨 ตั้งค่าธีมสีและ Background":
        st.header("🎨 ปรับแต่งธีมสีและภาพพื้นหลังส่วนตัว")
        current_setting = get_user_setting(current_user)

        with st.form("theme_bg_form"):
            new_welcome = st.text_input("💬 ข้อความต้อนรับส่วนตัว", value=current_setting.get("welcome_msg", "ยินดีต้อนรับ"))
            theme_keys = list(THEME_PALETTES.keys())
            current_theme_selection = current_setting.get("theme_name", theme_keys[0])
            if current_theme_selection not in theme_keys:
                current_theme_selection = theme_keys[0]
            
            selected_theme = st.selectbox("🎨 เลือกชุด Theme Color", theme_keys, index=theme_keys.index(current_theme_selection))
            bg_image = st.text_input("🖼️ (ทางเลือก) ลิงก์รูปภาพ Background (Image URL)", value=current_setting.get("bg_image", ""))
            
            save_btn = st.form_submit_button("✨ บันทึกการตั้งค่า", use_container_width=True)
            if save_btn:
                update_or_add_setting(current_user, selected_theme, new_welcome, bg_image)
                st.success("🎉 บันทึกสำเร็จ! กำลังโหลดธีมใหม่...")
                st.rerun()

    # เมนู 10: จัดการผู้ใช้งาน
    elif menu == "👥 จัดการผู้ใช้งาน":
        st.header("👥 จัดการบัญชีผู้ใช้งานระบบ")
        df_users = get_data_from_sheet("users")
        if not df_users.empty:
            st.subheader("รายชื่อผู้ใช้งานปัจจุบัน")
            st.dataframe(df_users[["username", "role"]], use_container_width=True)
            st.markdown("---")

        with st.form("new_user_sheet"):
            new_user = st.text_input("Username ใหม่")
            new_pass = st.text_input("Password ใหม่", type="password")
            create_sub = st.form_submit_button("สร้างบัญชีผู้ใช้", use_container_width=True)
            if create_sub:
                if new_user and new_pass:
                    hashed = hashlib.sha256(new_pass.encode()).hexdigest()
                    append_to_sheet("users", [new_user, hashed, "user"])
                    st.success(f"✅ สร้างบัญชี '{new_user}' สำเร็จ!")
                else:
                    st.error("⚠️ กรุณากรอกข้อมูลให้ครบถ้วน")
