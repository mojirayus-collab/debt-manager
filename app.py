import streamlit as st
import pandas as pd
import hashlib
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px

# ==========================================
# 1. เชื่อมต่อ Google Sheets ผ่าน Streamlit Secrets (แบบใหม่)
# ==========================================
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

@st.cache_resource
def init_google_sheet():
    try:
        # ดึงค่าจากความลับที่ซ่อนไว้ใน Streamlit Cloud
        secret_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(secret_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open("DebtDatabase")
        return sheet
    except Exception as e:
        st.error(f"⚠️ ไม่สามารถเชื่อมต่อ Google Sheets ได้: {e}")
        return None

sh = init_google_sheet()

def get_data_from_sheet(worksheet_name):
    if sh is None:
        return pd.DataFrame()
    worksheet = sh.worksheet(worksheet_name)
    data = worksheet.get_all_records()
    return pd.DataFrame(data)

def append_to_sheet(worksheet_name, row_data):
    if sh is not None:
        worksheet = sh.worksheet(worksheet_name)
        worksheet.append_row(row_data)

def delete_row_from_sheet(worksheet_name, row_index):
    if sh is not None:
        worksheet = sh.worksheet(worksheet_name)
        worksheet.delete_rows(row_index)

# ==========================================
# 2. ระบบ Login หน้าบ้าน
# ==========================================
st.set_page_config(page_title="ระบบจัดการลูกหนี้ (Cloud & Analytics)", page_icon="📊", layout="wide")

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""

def login_screen():
    st.title("📊 ระบบจัดการลูกหนี้และวิเคราะห์สัดส่วน")
    st.markdown("กรุณาเข้าสู่ระบบเพื่อใช้งาน")
    
    with st.form("login_form"):
        username = st.text_input("Username (ชื่อผู้ใช้)")
        password = st.text_input("Password (รหัสผ่าน)", type="password")
        submit = st.form_submit_button("เข้าสู่ระบบ")
        
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
    st.sidebar.markdown(f"👤 **ผู้ใช้งาน:** {st.session_state['username']}")
    if st.sidebar.button("🚪 ออกจากระบบ"):
        st.session_state["logged_in"] = False
        st.session_state["username"] = ""
        st.rerun()

    menu = st.sidebar.selectbox("เมนูการใช้งาน", [
        "📊 หน้าสรุปภาพรวมและกราฟสัดส่วน", 
        "➕ บันทึกยอดกู้ใหม่ (ซอยยอดได้)", 
        "✏️ จัดการ/แก้ไข/ลบรายการกู้",
        "💵 บันทึกรับชำระเงิน", 
        "👥 จัดการผู้ใช้งาน"
    ])

    current_user = st.session_state["username"]

    # เมนู 1: หน้าสรุปภาพรวม + กราฟวงกลม
    if menu == "📊 หน้าสรุปภาพรวมและกราฟสัดส่วน":
        st.header("📊 สรุปภาพรวมและสัดส่วนยอดลูกหนี้รายบุคคล")
        
        df_loans = get_data_from_sheet("loans")
        df_payments = get_data_from_sheet("payments")

        if df_loans.empty:
            st.info("ยังไม่มีข้อมูลในระบบ เริ่มบันทึกยอดกู้ได้ที่เมนูด้านข้างครับ")
        else:
            years = sorted(df_loans["buddhist_year"].astype(str).unique().tolist())
            selected_year = st.selectbox("📅 เลือกปี พ.ศ. ที่ต้องการตรวจสอบ", ["ทั้งหมด"] + years)

            if selected_year != "ทั้งหมด":
                df_loans = df_loans[df_loans["buddhist_year"].astype(str) == selected_year]
                if not df_payments.empty and "buddhist_year" in df_payments.columns:
                    df_payments = df_payments[df_payments["buddhist_year"].astype(str) == selected_year]

            summary_loans = df_loans.groupby("debtor_name")[["principal", "interest", "total_due"]].sum().reset_index()
            
            if not df_payments.empty and "paid_amount" in df_payments.columns:
                summary_payments = df_payments.groupby("debtor_name")["paid_amount"].sum().reset_index()
            else:
                summary_payments = pd.DataFrame(columns=["debtor_name", "paid_amount"])
                summary_payments["paid_amount"] = 0

            df_summary = pd.merge(summary_loans, summary_payments, on="debtor_name", how="left").fillna(0)
            df_summary["remaining"] = df_summary["total_due"] - df_summary["paid_amount"]
            df_summary["status"] = df_summary["remaining"].apply(lambda x: "✅ ชำระครบแล้ว" if x <= 0 else "⚠️ ยังค้างชำระ")
            df_summary["remaining"] = df_summary["remaining"].apply(lambda x: max(0, x))

            st.subheader("📋 ตารางสรุปรายละเอียดรายบุคคล")
            st.dataframe(
                df_summary.rename(columns={
                    "debtor_name": "ชื่อลูกหนี้",
                    "principal": "เงินต้นรวม (บาท)",
                    "interest": "ดอกเบี้ยรวม (บาท)",
                    "total_due": "ยอดสุทธิ (ต้น+ดอก)",
                    "paid_amount": "จ่าย
