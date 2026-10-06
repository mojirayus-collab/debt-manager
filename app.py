import streamlit as st
import pandas as pd
import hashlib
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px

# ==========================================
# 1. เชื่อมต่อ Google Sheets ผ่าน Streamlit Secrets
# ==========================================
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

@st.cache_resource
def init_google_sheet():
    try:
        # ดึงค่าจากความลับที่ซ่อนไว้ใน Streamlit Cloud
        secret_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(secret_dict, scope)
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
                    "paid_amount": "จ่ายคืนแล้ว (บาท)",
                    "remaining": "ยอดค้างชำระ (บาท)",
                    "status": "สถานะ"
                }),
                use_container_width=True
            )

            st.markdown("---")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("📌 เงินต้นรวม", f"{df_summary['principal'].sum():,.2f} ฿")
            col2.metric("📈 ดอกเบี้ยรวม", f"{df_summary['interest'].sum():,.2f} ฿")
            col3.metric("💵 จ่ายคืนแล้ว", f"{df_summary['paid_amount'].sum():,.2f} ฿")
            col4.metric("🚨 ค้างชำระรวม", f"{df_summary['remaining'].sum():,.2f} ฿")

            # กราฟวงกลม
            st.markdown("---")
            st.subheader("🍩 กราฟแสดงสัดส่วนยอดหนี้ของแต่ละคน")
            
            if not df_summary.empty and df_summary["total_due"].sum() > 0:
                col_chart1, col_chart2 = st.columns(2)

                with col_chart1:
                    st.markdown("##### 📌 สัดส่วนยอดหนี้สุทธิ (ต้น+ดอก) แต่ละคน")
                    fig_due = px.pie(df_summary, names="debtor_name", values="total_due", hole=0.4, color_discrete_sequence=px.colors.sequential.RdBu)
                    st.plotly_chart(fig_due, use_container_width=True)

                with col_chart2:
                    st.markdown("##### 🚨 สัดส่วนยอดค้างชำระ")
                    df_remaining_only = df_summary[df_summary["remaining"] > 0]
                    if not df_remaining_only.empty:
                        fig_rem = px.pie(df_remaining_only, names="debtor_name", values="remaining", hole=0.4, color_discrete_sequence=px.colors.sequential.Sunset)
                        st.plotly_chart(fig_rem, use_container_width=True)
                    else:
                        st.success("🎉 ยอดค้างชำระเป็น 0 ทุกคน เคลียร์หนี้ครบหมดแล้ว!")

    # เมนู 2: บันทึกยอดกู้ใหม่ (ซอยยอด)
    elif menu == "➕ บันทึกยอดกู้ใหม่ (ซอยยอดได้)":
        st.header("➕ บันทึกรายการยืมเงิน (สามารถบันทึกเพิ่มหลายรอบได้)")
        with st.form("loan_form_sheet"):
            buddhist_year = st.selectbox("ปี พ.ศ.", ["2569", "2570", "2571"])
            month = st.selectbox("เดือน", ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"])
            day_note = st.text_input("วันที่กู้ (เช่น วันที่ 1, หรือ 15 ต.ค.)", value="1")
            debtor_name = st.text_input("ชื่อลูกหนี้")
            principal = st.number_input("เงินต้นรอบนี้ (บาท)", min_value=0.0, step=100.0)
            rate = st.number_input("ดอกเบี้ย (%)", value=20.0, step=1.0)
            
            submitted = st.form_submit_button("บันทึกข้อมูลเพิ่ม")
            if submitted:
                if debtor_name and principal > 0:
                    interest = principal * (rate / 100)
                    total_due = principal + interest
                    append_to_sheet("loans", [current_user, debtor_name, buddhist_year, f"{day_note} {month} {buddhist_year}", principal, interest, total_due])
                    st.success(f"✅ บันทึกยอดกู้ของ '{debtor_name}' สำเร็จ!")
                else:
                    st.error("⚠️ กรุณากรอกข้อมูลให้ครบถ้วน")

    # เมนู 3: แก้ไข/ลบรายการกู้
    elif menu == "✏️ จัดการ/แก้ไข/ลบรายการกู้":
        st.header("✏️ จัดการรายการยืมเงิน (ลบรายการที่ผิดพลาด)")
        df_loans = get_data_from_sheet("loans")

        if df_loans.empty:
            st.info("ยังไม่มีข้อมูลรายการกู้ในระบบ")
        else:
            st.dataframe(df_loans, use_container_width=True)
            st.markdown("---")
            row_to_delete = st.number_input("ระบุลำดับแถว (Index) ที่ต้องการลบ", min_value=0, max_value=len(df_loans)-1, step=1)
            
            if st.button("❌ ลบรายการนี้ออกจากระบบ"):
                sheet_row_index = int(row_to_delete) + 2
                delete_row_from_sheet("loans", sheet_row_index)
                st.success(f"ลบรายการเรียบร้อย! กรุณารีเฟรชหน้าจอ")
                st.rerun()

    # เมนู 4: บันทึกรับชำระเงิน
    elif menu == "💵 บันทึกรับชำระเงิน":
        st.header("💵 บันทึกรับชำระเงิน")
        df_loans = get_data_from_sheet("loans")
        debtors_list = df_loans["debtor_name"].unique().tolist() if not df_loans.empty else []

        if not debtors_list:
            st.warning("⚠ ยังไม่มีรายชื่อลูกหนี้ในระบบ")
        else:
            with st.form("payment_form_sheet"):
                buddhist_year = st.selectbox("ปี พ.ศ.", ["2569", "2570", "2571"])
                debtor_name = st.selectbox("เลือกชื่อลูกหนี้", debtors_list)
                month = st.text_input("งวดเดือนที่ชำระ")
                paid_amount = st.number_input("จำนวนเงินที่จ่าย (บาท)", min_value=0.0, step=100.0)
                
                submitted = st.form_submit_button("บันทึกรับชำระ")
                if submitted:
                    if paid_amount > 0:
                        append_to_sheet("payments", [current_user, debtor_name, buddhist_year, month, paid_amount])
                        st.success(f"💵 บันทึกรับชำระจาก '{debtor_name}' เรียบร้อย!")
                    else:
                        st.error("⚠️ กรุณากรอกจำนวนเงินให้ถูกต้อง")

    # เมนู 5: จัดการผู้ใช้งาน
    elif menu == "👥 จัดการผู้ใช้งาน":
        st.header("👥 เพิ่มบัญชีผู้ใช้งานใหม่")
        with st.form("new_user_sheet"):
            new_user = st.text_input("Username ใหม่")
            new_pass = st.text_input("Password ใหม่", type="password")
            create_sub = st.form_submit_button("สร้างบัญชี")
            
            if create_sub:
                if new_user and new_pass:
                    hashed = hashlib.sha256(new_pass.encode()).hexdigest()
                    append_to_sheet("users", [new_user, hashed, "user"])
                    st.success(f"✅ สร้างบัญชี '{new_user}' สำเร็จ!")
                else:
                    st.error("⚠ กรุณากรอกข้อมูลให้ครบถ้วน")