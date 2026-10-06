import streamlit as st
import pandas as pd
import hashlib, io, html, calendar, urllib.parse
import gspread, pytz
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px
from datetime import datetime, date, time, timedelta

# ==========================================
# 0. ค่าพื้นฐาน
# ==========================================
TZ = pytz.timezone("Asia/Bangkok")
FMT = "%Y-%m-%d %H:%M:%S"
CYCLE_DAYS = 30
DEFAULT_THEME = "🔴 Crimson Red (แดงเพลิงโฉบเฉี่ยว)"
MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
          "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
LOAN_COLS = ["username", "debtor_name", "line_id", "buddhist_year", "date_time",
             "principal", "interest", "total_due", "slip_url"]
PAY_COLS = ["username", "debtor_name", "buddhist_year", "date_time", "paid_amount", "slip_url"]

def now_th():
    return datetime.now(TZ).replace(tzinfo=None)

def baht(x):
    return f"{x:,.2f} ฿"

# ==========================================
# 1. Google Sheets & Drive
# ==========================================
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

@st.cache_resource
def init_google():
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), SCOPE)
        book = gspread.authorize(creds).open("DebtDatabase")
        heads = {"users": ["username", "password", "role"], "loans": LOAN_COLS, "payments": PAY_COLS,
                 "settings": ["username", "theme_name", "welcome_msg", "bg_image"]}
        have = [w.title for w in book.worksheets()]
        for name, cols in heads.items():
            if name not in have:
                ws = book.add_worksheet(title=name, rows=1000, cols=len(cols))
                ws.append_row(cols)
        return book, creds
    except Exception as e:
        st.error(f"⚠️ เชื่อมต่อ Google Sheets ไม่ได้: {e}")
        return None, None

sh, creds = init_google()

@st.cache_data(ttl=20, show_spinner=False)
def load(name):
    if sh is None:
        return pd.DataFrame()
    try:
        df = pd.DataFrame(sh.worksheet(name).get_all_records())
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df["_row"] = df.index + 2  # เลขแถวจริงใน Sheet
    for c in ("principal", "interest", "total_due", "paid_amount"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    if "date_time" in df.columns:
        df["dt"] = pd.to_datetime(df["date_time"], errors="coerce")
    return df

def add_row(name, row):
    sh.worksheet(name).append_row(row, value_input_option="RAW")
    load.clear()

def delete_row(name, row):
    sh.worksheet(name).delete_rows(int(row))
    load.clear()

def update_cells(name, row, changes):
    ws = sh.worksheet(name)
    for col, val in changes.items():
        ws.update_cell(int(row), col, val)
    load.clear()

def get_setting(user):
    df = load("settings")
    if not df.empty and "username" in df.columns:
        r = df[df["username"] == user]
        if not r.empty:
            return r.iloc[0].to_dict()
    return {"theme_name": DEFAULT_THEME, "welcome_msg": "ยินดีต้อนรับสู่ระบบจัดการลูกหนี้", "bg_image": ""}

def save_setting(user, theme, welcome, bg):
    ws = sh.worksheet("settings")
    names = ws.col_values(1)
    if user in names:
        r = names.index(user) + 1
        for c, v in ((2, theme), (3, welcome), (4, bg)):
            ws.update_cell(r, c, v)
    else:
        ws.append_row([user, theme, welcome, bg], value_input_option="RAW")
    load.clear()

def upload_slip(f, folder="DebtSlips"):
    if f is None or creds is None:
        return ""
    try:
        import googleapiclient.discovery
        from googleapiclient.http import MediaIoBaseUpload
        svc = googleapiclient.discovery.build("drive", "v3", credentials=creds)
        q = f"name='{folder}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        found = svc.files().list(q=q).execute().get("files", [])
        if found:
            fid = found[0]["id"]
        else:
            fid = svc.files().create(body={"name": folder, "mimeType": "application/vnd.google-apps.folder"},
                                     fields="id").execute()["id"]
        meta = {"name": f"slip_{now_th().strftime('%Y%m%d_%H%M%S')}_{f.name}", "parents": [fid]}
        media = MediaIoBaseUpload(io.BytesIO(f.getvalue()), mimetype=f.type, resumable=True)
        up = svc.files().create(body=meta, media_body=media, fields="id, webViewLink").execute()
        svc.permissions().create(fileId=up["id"], body={"role": "reader", "type": "anyone"}).execute()
        return up.get("webViewLink", "")
    except Exception as e:
        st.warning(f"อัปโหลดสลิปไม่สำเร็จ ระบบจะบันทึกรายการโดยไม่มีสลิป ({e})")
        return ""

# ==========================================
# 2. ธีม & CSS
# ==========================================
def _t(p, h, rgb):
    return {"primary": p, "hover": h, "glow": f"rgba({rgb},0.45)", "border": f"rgba({rgb},0.35)"}

THEMES = {
    DEFAULT_THEME: _t("#ff4b4b", "#ff7a6b", "255,75,75"),
    "⚡ Cyber Blue (ฟ้าไซเบอร์ล้ำอนาคต)": _t("#00d2ff", "#5ae3ff", "0,210,255"),
    "🟢 Neon Emerald (เขียวมรกตเรืองแสง)": _t("#00ff87", "#5affb0", "0,255,135"),
    "🟣 Royal Purple (ม่วงพรีเมียมหรูหรา)": _t("#9d4edd", "#b565ff", "157,78,221"),
    "🟡 Golden Amber (เหลืองทองคำเด่นชัด)": _t("#ffb703", "#ffd166", "255,183,3"),
}

def apply_css(setting):
    t = THEMES.get(setting.get("theme_name"), THEMES[DEFAULT_THEME])
    bg = str(setting.get("bg_image", "") or "").strip()
    bg_css = "background:#0b0f19;"
    if bg:
        bg_css = (f"background-image:linear-gradient(rgba(11,15,25,.9),rgba(11,15,25,.9)),url('{bg}');"
                  "background-size:cover;background-position:center;background-attachment:fixed;")
    st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Prompt:wght@400;500;600;700&display=swap');
:root{{--p:{t['primary']};--ph:{t['hover']};--glow:{t['glow']};--bd:{t['border']};}}
.stApp{{{bg_css}}}
.stApp,.stMarkdown,button,input,label,p,h1,h2,h3,h4,textarea{{font-family:'Prompt',sans-serif;}}
.block-container{{padding-top:2rem;max-width:1250px;}}
div.stButton>button,div.stDownloadButton>button,div.stFormSubmitButton>button{{
  background:linear-gradient(135deg,var(--p),var(--ph))!important;color:#fff!important;border:none!important;
  border-radius:12px!important;font-weight:600!important;padding:.55rem 1.1rem!important;transition:.2s;}}
div.stButton>button:hover,div.stFormSubmitButton>button:hover{{box-shadow:0 6px 20px var(--glow)!important;transform:translateY(-2px);}}
.stTextInput input,.stNumberInput input,.stDateInput input,.stTimeInput input{{
  background:rgba(255,255,255,.05)!important;border:1px solid rgba(255,255,255,.14)!important;border-radius:10px!important;}}
.stTextInput input:focus,.stNumberInput input:focus{{border-color:var(--p)!important;box-shadow:0 0 10px var(--glow)!important;}}
[data-testid="stMetric"]{{background:rgba(25,28,36,.7);backdrop-filter:blur(14px);padding:18px 20px;
  border-radius:16px;border:1px solid var(--bd);border-left:5px solid var(--p);}}
[data-testid="stMetricLabel"]{{opacity:.8;}}
[data-testid="stDataFrame"]{{border-radius:12px;overflow:hidden;border:1px solid rgba(255,255,255,.1);}}
[data-testid="stSidebar"]{{background:rgba(11,15,25,.96);border-right:1px solid rgba(255,255,255,.08);}}
.hero{{padding:22px 26px;border-radius:18px;margin-bottom:18px;border:1px solid var(--bd);
  background:linear-gradient(120deg,var(--glow),rgba(25,28,36,.7) 55%);}}
.hero h2{{margin:0;font-weight:700;}} .hero p{{margin:.3rem 0 0;opacity:.8;}}
.chip{{display:inline-block;padding:3px 12px;border-radius:999px;font-size:.82rem;font-weight:600;margin-right:6px;}}
.chip.ok{{background:rgba(0,200,120,.18);color:#4ade80;}} .chip.warn{{background:rgba(255,183,3,.18);color:#fbbf24;}}
.chip.bad{{background:rgba(255,75,75,.18);color:#ff8080;}}
.alert{{padding:12px 16px;border-radius:12px;margin-bottom:8px;border-left:5px solid #ff4b4b;background:rgba(255,75,75,.12);}}
.alert.soon{{border-color:#ffb703;background:rgba(255,183,3,.12);}}
table.cal{{width:100%;border-collapse:separate;border-spacing:5px;table-layout:fixed;}}
table.cal th{{padding:6px;text-align:center;opacity:.7;font-weight:500;}}
table.cal td{{height:92px;vertical-align:top;padding:6px;border-radius:10px;background:rgba(255,255,255,.04);
  border:1px solid rgba(255,255,255,.07);font-size:.78rem;overflow:hidden;}}
table.cal td.e{{background:transparent;border:none;}}
table.cal td.today{{border:2px solid var(--p);box-shadow:0 0 12px var(--glow);}}
.ev{{margin-top:3px;padding:1px 6px;border-radius:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.ev.loan{{background:rgba(80,140,255,.25);}} .ev.pay{{background:rgba(0,200,120,.25);}} .ev.due{{background:rgba(255,75,75,.28);}}
</style>""", unsafe_allow_html=True)

# ==========================================
# 3. ตัวช่วยคำนวณ
# ==========================================
def waterfall(principal, interest, paid):
    """ตัดดอกเบี้ยก่อน แล้วค่อยตัดเงินต้น คืน (ดอกค้าง, ต้นค้าง, เงินจ่ายเกิน)"""
    pay_i = min(interest, paid)
    pay_p = min(principal, max(0.0, paid - interest))
    return interest - pay_i, principal - pay_p, max(0.0, paid - interest - principal)

def next_due(loan_date, today):
    n = (today - loan_date).days
    k = max(1, -(-n // CYCLE_DAYS))
    return loan_date + timedelta(days=CYCLE_DAYS * k)

def summarize(loans, pays):
    if loans.empty:
        return pd.DataFrame()
    today = now_th().date()
    rows = []
    for name, g in loans.groupby("debtor_name"):
        p, i = g["principal"].sum(), g["interest"].sum()
        pp = pays[pays["debtor_name"] == name] if not pays.empty else pays
        paid = float(pp["paid_amount"].sum()) if not pp.empty else 0.0
        ri, rp, extra = waterfall(p, i, paid)
        rem = ri + rp
        if rem <= 0:
            grade, status = "🟢 A ชำระครบ", "✅ ชำระครบแล้ว"
        elif paid > 0:
            grade, status = "🟡 B กำลังผ่อน", "⚠️ ค้างชำระ"
        else:
            grade, status = "🔴 C ยังไม่เคยชำระ", "⚠️ ค้างชำระ"
        lines = [x for x in g.get("line_id", pd.Series(dtype=str)).astype(str) if x.strip()]
        last = g["dt"].max()
        due = next_due(last.date(), today) if rem > 0 and pd.notna(last) else None
        rows.append({"ลูกหนี้": name, "LINE/โทร": lines[0] if lines else "-", "เงินต้น": p, "ดอกเบี้ย": i,
                     "ยอดรวม": p + i, "จ่ายแล้ว": paid, "ดอกค้าง": ri, "ต้นค้าง": rp, "คงเหลือ": rem,
                     "จ่ายเกิน": extra, "เกรด": grade, "สถานะ": status, "ครบกำหนดถัดไป": due,
                     "เหลือ(วัน)": (due - today).days if due else None})
    return pd.DataFrame(rows)

def datetime_picker(key, default=None, label="🕒 วันและเวลาที่ทำรายการ"):
    """เลือก 'ตอนนี้' หรือ 'ย้อนหลังจากปฏิทิน' คืนค่า datetime"""
    now = now_th()
    if default is None:
        mode = st.radio(label, ["⚡ ใช้เวลาปัจจุบัน", "📅 เลือกวันที่เอง (ย้อนหลังได้)"], horizontal=True, key=f"{key}_m")
        if mode.startswith("⚡"):
            st.caption(f"จะบันทึกเป็น {now.strftime('%d/%m/')}{now.year + 543} {now.strftime('%H:%M')} น.")
            return now.replace(microsecond=0)
        default = now
    c1, c2 = st.columns(2)
    d = c1.date_input("วันที่", value=default.date(), max_value=now.date() + timedelta(days=365), key=f"{key}_d")
    t = c2.time_input("เวลา", value=default.time().replace(second=0, microsecond=0), key=f"{key}_t")
    out = datetime.combine(d, t)
    st.caption(f"จะบันทึกเป็น {out.strftime('%d/%m/')}{out.year + 543} {out.strftime('%H:%M')} น.")
    return out

def hero(title, sub=""):
    st.markdown(f"<div class='hero'><h2>{title}</h2><p>{sub}</p></div>", unsafe_allow_html=True)

def chart_style(fig):
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#e5e7eb",
                      margin=dict(l=10, r=10, t=40, b=10))
    return fig

# ==========================================
# 4. Login
# ==========================================
st.set_page_config(page_title="ระบบจัดการลูกหนี้", page_icon="⚡", layout="wide")
ss = st.session_state
ss.setdefault("logged_in", False)
ss.setdefault("username", "")
ss.setdefault("role", "user")

user = ss["username"]
setting = get_setting(user) if ss["logged_in"] else {"theme_name": DEFAULT_THEME}
apply_css(setting)

def login_screen():
    _, mid, _ = st.columns([1, 1.6, 1])
    with mid:
        hero("⚡ ระบบจัดการลูกหนี้", "เข้าสู่ระบบเพื่อดูยอดค้าง บันทึกการรับชำระ และส่งแจ้งเตือนทาง LINE")
        with st.form("login"):
            u = st.text_input("ชื่อผู้ใช้")
            pw = st.text_input("รหัสผ่าน", type="password")
            if st.form_submit_button("เข้าสู่ระบบ", use_container_width=True):
                if sh is None:
                    st.error("ยังเชื่อมต่อฐานข้อมูลไม่ได้")
                    return
                users = load("users")
                if users.empty:
                    add_row("users", ["admin", hashlib.sha256(b"1234").hexdigest(), "admin"])
                    users = load("users")
                    st.warning("สร้างบัญชีเริ่มต้น admin / 1234 แล้ว กรุณาเปลี่ยนรหัสผ่านทันทีหลังเข้าสู่ระบบ")
                h = hashlib.sha256(pw.encode()).hexdigest()
                m = users[(users["username"].astype(str) == u) & (users["password"].astype(str) == h)]
                if m.empty:
                    st.error("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง ลองตรวจตัวพิมพ์เล็ก-ใหญ่อีกครั้ง")
                else:
                    ss.update(logged_in=True, username=u, role=str(m.iloc[0].get("role", "user")))
                    st.rerun()

if not ss["logged_in"]:
    login_screen()
    st.stop()

# ==========================================
# 5. ข้อมูลหลัก (admin เห็นทั้งหมด / user เห็นเฉพาะของตัวเอง)
# ==========================================
is_admin = ss["role"] == "admin"

def scoped(df):
    if df.empty or is_admin or "username" not in df.columns:
        return df
    return df[df["username"].astype(str) == user]

loans_all, pays_all = scoped(load("loans")), scoped(load("payments"))

PAGES = ["🏠 แดชบอร์ด", "📅 ปฏิทิน", "➕ ปล่อยกู้ใหม่", "💵 รับชำระ & ใบเสร็จ", "👤 ข้อมูลลูกหนี้รายคน",
         "✏️ แก้ไข/ลบรายการ", "💬 แจ้งเตือน LINE", "⚙️ ตั้งค่า"]
if is_admin:
    PAGES.append("👥 จัดการผู้ใช้")

with st.sidebar:
    st.markdown(f"### 👤 {user}")
    st.caption(f"{'ผู้ดูแลระบบ' if is_admin else 'ผู้ใช้งาน'} · {setting.get('welcome_msg', '')}")
    page = st.radio("เมนู", PAGES, label_visibility="collapsed")
    st.divider()
    if st.button("🚪 ออกจากระบบ", use_container_width=True):
        ss.update(logged_in=False, username="", role="user")
        st.rerun()
    if st.button("🔄 รีเฟรชข้อมูล", use_container_width=True):
        load.clear()
        st.rerun()

summary = summarize(loans_all, pays_all)

def need_data():
    if loans_all.empty:
        st.info("ยังไม่มีข้อมูล เริ่มจากเมนู ➕ ปล่อยกู้ใหม่ ได้เลย")
        st.stop()

# ---------- แดชบอร์ด ----------
if page == PAGES[0]:
    hero("🏠 ภาพรวมลูกหนี้", f"ข้อมูล ณ {now_th().strftime('%d/%m/')}{now_th().year + 543}")
    need_data()
    loans, pays, summ = loans_all, pays_all, summary
    years = sorted((loans["dt"].dt.year + 543).dropna().astype(int).astype(str).unique())
    y = st.selectbox("ปี พ.ศ.", ["ทั้งหมด"] + years)
    if y != "ทั้งหมด":
        yy = int(y) - 543
        loans = loans[loans["dt"].dt.year == yy]
        pays = pays[pays["dt"].dt.year == yy] if not pays.empty else pays
        summ = summarize(loans, pays)
    if summ.empty:
        st.info("ไม่มีรายการในปีที่เลือก")
        st.stop()

    c = st.columns(4)
    c[0].metric("เงินต้นรวม", baht(summ["เงินต้น"].sum()))
    c[1].metric("ดอกเบี้ยรวม", baht(summ["ดอกเบี้ย"].sum()))
    c[2].metric("รับชำระแล้ว", baht(summ["จ่ายแล้ว"].sum()))
    c[3].metric("ยอดค้างสุทธิ", baht(summ["คงเหลือ"].sum()))

    soon = summ[(summ["คงเหลือ"] > 0) & (summ["เหลือ(วัน)"].notna()) & (summ["เหลือ(วัน)"] <= 3)]
    for _, r in soon.sort_values("เหลือ(วัน)").iterrows():
        d = int(r["เหลือ(วัน)"])
        when = "ครบกำหนดวันนี้" if d == 0 else f"อีก {d} วัน"
        st.markdown(f"<div class='alert soon'>⏰ <b>{html.escape(str(r['ลูกหนี้']))}</b> {when} · ค้าง {baht(r['คงเหลือ'])}</div>",
                    unsafe_allow_html=True)

    g1, g2 = st.columns(2)
    donut = pd.DataFrame({"ส่วน": ["เงินต้นค้าง", "ดอกเบี้ยค้าง", "รับชำระแล้ว"],
                          "บาท": [summ["ต้นค้าง"].sum(), summ["ดอกค้าง"].sum(), summ["จ่ายแล้ว"].sum()]})
    g1.plotly_chart(chart_style(px.pie(donut, names="ส่วน", values="บาท", hole=.55, title="สัดส่วนยอดหนี้")),
                    use_container_width=True)
    top = summ[summ["คงเหลือ"] > 0].sort_values("คงเหลือ", ascending=False).head(10)
    if not top.empty:
        g2.plotly_chart(chart_style(px.bar(top, x="คงเหลือ", y="ลูกหนี้", orientation="h", title="ลูกหนี้ค้างสูงสุด")),
                        use_container_width=True)
    m1 = loans.assign(เดือน=loans["dt"].dt.to_period("M").astype(str)).groupby("เดือน")["principal"].sum().rename("ปล่อยกู้")
    if not pays.empty:
        m2 = pays.assign(เดือน=pays["dt"].dt.to_period("M").astype(str)).groupby("เดือน")["paid_amount"].sum().rename("รับชำระ")
        m = pd.concat([m1, m2], axis=1).fillna(0).reset_index().melt("เดือน", var_name="ประเภท", value_name="บาท")
    else:
        m = m1.reset_index().melt("เดือน", var_name="ประเภท", value_name="บาท")
    st.plotly_chart(chart_style(px.bar(m, x="เดือน", y="บาท", color="ประเภท", barmode="group", title="ปล่อยกู้ vs รับชำระรายเดือน")),
                    use_container_width=True)

    st.subheader("ตารางลูกหนี้")
    f1, f2 = st.columns([2, 3])
    q = f1.text_input("🔍 ค้นหาชื่อ")
    stt = f2.radio("สถานะ", ["ทั้งหมด", "⚠️ ค้างชำระ", "✅ ชำระครบแล้ว"], horizontal=True)
    show = summ
    if q:
        show = show[show["ลูกหนี้"].astype(str).str.contains(q, case=False)]
    if stt != "ทั้งหมด":
        show = show[show["สถานะ"] == stt]
    st.dataframe(show.drop(columns=["จ่ายเกิน"]), use_container_width=True, hide_index=True,
                 column_config={k: st.column_config.NumberColumn(format="%.2f") for k in
                                ["เงินต้น", "ดอกเบี้ย", "ยอดรวม", "จ่ายแล้ว", "ดอกค้าง", "ต้นค้าง", "คงเหลือ"]})
    st.download_button("📥 ดาวน์โหลดรายงาน (CSV)", summ.to_csv(index=False).encode("utf-8-sig"), "debt_report.csv", "text/csv")

# ---------- ปฏิทิน ----------
elif page == PAGES[1]:
    hero("📅 ปฏิทินธุรกรรม", "🔵 ปล่อยกู้ · 🟢 รับชำระ · 🔴 ครบกำหนดชำระ")
    now = now_th()
    c1, c2 = st.columns(2)
    mon = c1.selectbox("เดือน", range(1, 13), index=now.month - 1, format_func=lambda i: MONTHS[i - 1])
    yr = c2.number_input("ปี พ.ศ.", min_value=2500, max_value=2700, value=now.year + 543, step=1) - 543
    start, end = date(yr, mon, 1), date(yr, mon, calendar.monthrange(yr, mon)[1])
    ev = {}
    def put(d, cls, text):
        ev.setdefault(d.day, []).append((cls, text))
    rows = []
    if not loans_all.empty:
        for _, r in loans_all.dropna(subset=["dt"]).iterrows():
            if start <= r["dt"].date() <= end:
                put(r["dt"].date(), "loan", f"💸 {r['debtor_name']}")
                rows.append((r["dt"].date(), "ปล่อยกู้", r["debtor_name"], r["principal"]))
    if not pays_all.empty:
        for _, r in pays_all.dropna(subset=["dt"]).iterrows():
            if start <= r["dt"].date() <= end:
                put(r["dt"].date(), "pay", f"💵 {r['debtor_name']}")
                rows.append((r["dt"].date(), "รับชำระ", r["debtor_name"], r["paid_amount"]))
    if not summary.empty:
        for _, s in summary[summary["คงเหลือ"] > 0].iterrows():
            last = loans_all[loans_all["debtor_name"] == s["ลูกหนี้"]]["dt"].max()
            for k in range(1, 200):
                d = last.date() + timedelta(days=CYCLE_DAYS * k)
                if d > end:
                    break
                if d >= start:
                    put(d, "due", f"⏰ {s['ลูกหนี้']}")
                    rows.append((d, "ครบกำหนด", s["ลูกหนี้"], s["คงเหลือ"]))
    h = "<table class='cal'><tr>" + "".join(f"<th>{d}</th>" for d in ["อา", "จ", "อ", "พ", "พฤ", "ศ", "ส"]) + "</tr>"
    for week in calendar.Calendar(6).monthdayscalendar(yr, mon):
        h += "<tr>"
        for d in week:
            if d == 0:
                h += "<td class='e'></td>"
                continue
            items = ev.get(d, [])
            body = "".join(f"<div class='ev {c}'>{html.escape(t)}</div>" for c, t in items[:3])
            if len(items) > 3:
                body += f"<div class='ev'>+{len(items) - 3} รายการ</div>"
            h += f"<td class='{'today' if date(yr, mon, d) == now.date() else ''}'><b>{d}</b>{body}</td>"
        h += "</tr>"
    st.markdown(h + "</table>", unsafe_allow_html=True)
    st.subheader(f"รายการเดือน{MONTHS[mon - 1]} {yr + 543}")
    if rows:
        st.dataframe(pd.DataFrame(sorted(rows), columns=["วันที่", "ประเภท", "ลูกหนี้", "จำนวนเงิน"]),
                     use_container_width=True, hide_index=True)
    else:
        st.info("เดือนนี้ยังไม่มีรายการ")

# ---------- ปล่อยกู้ใหม่ ----------
elif page == PAGES[2]:
    hero("➕ ปล่อยกู้ใหม่", "กรอกข้อมูลลูกหนี้ ระบบคำนวณดอกเบี้ยและปี พ.ศ. ให้อัตโนมัติ")
    names = sorted(loans_all["debtor_name"].unique()) if not loans_all.empty else []
    c1, c2 = st.columns(2)
    pick = c1.selectbox("ลูกหนี้", ["➕ ลูกหนี้ใหม่"] + names)
    name = c2.text_input("ชื่อลูกหนี้ใหม่") if pick.startswith("➕") else pick
    old_line = ""
    if not pick.startswith("➕"):
        ls = [x for x in loans_all[loans_all["debtor_name"] == pick]["line_id"].astype(str) if x.strip()]
        old_line = ls[0] if ls else ""
    line_id = st.text_input("LINE ID / เบอร์โทร (ไม่บังคับ)", value=old_line, placeholder="@line_debtor หรือ 0812345678")
    c3, c4 = st.columns(2)
    principal = c3.number_input("เงินต้น (บาท)", min_value=0.0, step=100.0)
    rate = c4.number_input("ดอกเบี้ยต่อรอบ (%)", value=20.0, step=1.0)
    interest = principal * rate / 100
    st.info(f"ดอกเบี้ย {baht(interest)} · ยอดที่ต้องคืน **{baht(principal + interest)}**")
    when = datetime_picker("loan")
    slip = st.file_uploader("📎 แนบสลิปการโอนเงินให้ยืม", type=["png", "jpg", "jpeg"])
    if st.button("💾 บันทึกรายการกู้", use_container_width=True):
        if not name.strip() or principal <= 0:
            st.error("กรุณากรอกชื่อลูกหนี้และเงินต้นให้มากกว่า 0")
        else:
            with st.spinner("กำลังบันทึก..."):
                url = upload_slip(slip) if slip else ""
                add_row("loans", [user, name.strip(), line_id.strip(), str(when.year + 543), when.strftime(FMT),
                                  principal, interest, principal + interest, url])
            st.success(f"บันทึกยอดกู้ของ '{name}' แล้ว")

# ---------- รับชำระ ----------
elif page == PAGES[3]:
    hero("💵 รับชำระ & ใบเสร็จ", "ระบบตัดดอกเบี้ยก่อน แล้วจึงตัดเงินต้น")
    need_data()
    t1, t2 = st.tabs(["บันทึกรับชำระ", "ประวัติ · สลิป · ใบเสร็จ"])
    with t1:
        debtor = st.selectbox("ลูกหนี้", sorted(summary["ลูกหนี้"]))
        s = summary[summary["ลูกหนี้"] == debtor].iloc[0]
        c = st.columns(3)
        c[0].metric("ดอกเบี้ยค้าง", baht(s["ดอกค้าง"]))
        c[1].metric("เงินต้นค้าง", baht(s["ต้นค้าง"]))
        c[2].metric("คงเหลือ", baht(s["คงเหลือ"]))
        ss.setdefault("pay_amt", 0.0)
        def fill_all():
            ss["pay_amt"] = float(s["คงเหลือ"])
        a1, a2 = st.columns([3, 1])
        amt = a1.number_input("จำนวนที่รับ (บาท)", min_value=0.0, step=100.0, key="pay_amt")
        a2.markdown("<div style='height:1.9rem'></div>", unsafe_allow_html=True)
        a2.button("ใส่ยอดค้างทั้งหมด", on_click=fill_all, use_container_width=True)
        if amt > 0:
            ri, rp, extra = waterfall(s["เงินต้น"], s["ดอกเบี้ย"], s["จ่ายแล้ว"] + amt)
            st.info(f"หลังรับชำระ: ดอกค้าง {baht(ri)} · ต้นค้าง {baht(rp)} · คงเหลือ **{baht(ri + rp)}**")
            if amt > s["คงเหลือ"]:
                st.warning(f"ยอดนี้เกินยอดค้างอยู่ {baht(amt - s['คงเหลือ'])} ตรวจสอบก่อนบันทึก")
        when = datetime_picker("pay")
        slip = st.file_uploader("📎 แนบสลิปการโอน", type=["png", "jpg", "jpeg"], key="pay_slip")
        if st.button("💾 บันทึกรับชำระ", use_container_width=True):
            if amt <= 0:
                st.error("กรุณากรอกจำนวนเงินมากกว่า 0")
            else:
                url = upload_slip(slip, "PaymentSlips") if slip else ""
                add_row("payments", [user, debtor, str(when.year + 543), when.strftime(FMT), amt, url])
                st.success(f"รับชำระจาก '{debtor}' {baht(amt)} เรียบร้อย")
    with t2:
        if pays_all.empty:
            st.info("ยังไม่มีประวัติรับชำระ")
        else:
            who = st.selectbox("กรองตามลูกหนี้", ["ทั้งหมด"] + sorted(pays_all["debtor_name"].unique()), key="hist_who")
            ph = pays_all if who == "ทั้งหมด" else pays_all[pays_all["debtor_name"] == who]
            ph = ph.sort_values("dt", ascending=False)
            st.dataframe(ph.drop(columns=["_row", "dt"], errors="ignore"), use_container_width=True, hide_index=True)
            st.subheader("🧾 ออกใบเสร็จ")
            rid = st.selectbox("เลือกรายการ", ph.index.tolist(),
                               format_func=lambda i: f"{ph.loc[i, 'date_time']} · {ph.loc[i, 'debtor_name']} · {ph.loc[i, 'paid_amount']:,.2f}")
            r = ph.loc[rid]
            sm = summary[summary["ลูกหนี้"] == r["debtor_name"]]
            rem_i = sm.iloc[0]["ดอกค้าง"] if not sm.empty else 0
            rem_p = sm.iloc[0]["ต้นค้าง"] if not sm.empty else 0
            receipt = f"""========================================
        ใบเสร็จรับเงิน
========================================
วันที่ทำรายการ : {r['date_time']}
ลูกหนี้        : {r['debtor_name']}
จำนวนที่ชำระ   : {r['paid_amount']:,.2f} บาท
----------------------------------------
ยอดคงเหลือปัจจุบัน
  ดอกเบี้ยค้าง : {rem_i:,.2f} บาท
  เงินต้นค้าง  : {rem_p:,.2f} บาท
  รวมคงเหลือ   : {rem_i + rem_p:,.2f} บาท
========================================
ผู้บันทึก: {user}"""
            st.code(receipt, language="text")
            st.download_button("📥 ดาวน์โหลดใบเสร็จ (.txt)", receipt.encode("utf-8-sig"),
                               f"receipt_{r['debtor_name']}_{now_th():%Y%m%d}.txt", "text/plain")
            links = [(x["debtor_name"], x["date_time"], x["paid_amount"], x["slip_url"]) for _, x in ph.iterrows()
                     if str(x.get("slip_url", "")).startswith("http")]
            if links:
                with st.expander(f"🔗 สลิปหลักฐาน ({len(links)})"):
                    for n, d, a, u in links:
                        st.markdown(f"• **{n}** · {d} · {a:,.2f} ฿ → [เปิดสลิป]({u})")

# ---------- รายคน ----------
elif page == PAGES[4]:
    hero("👤 ข้อมูลลูกหนี้รายคน", "ดูยอด ความคืบหน้า และประวัติทั้งหมดของลูกหนี้หนึ่งราย")
    need_data()
    d = st.selectbox("เลือกลูกหนี้", sorted(summary["ลูกหนี้"]))
    s = summary[summary["ลูกหนี้"] == d].iloc[0]
    cls = "ok" if s["คงเหลือ"] <= 0 else ("warn" if s["จ่ายแล้ว"] > 0 else "bad")
    st.markdown(f"<span class='chip {cls}'>{s['เกรด']}</span><span class='chip {cls}'>{s['สถานะ']}</span>"
                f"<span class='chip warn'>LINE/โทร: {html.escape(str(s['LINE/โทร']))}</span>", unsafe_allow_html=True)
    c = st.columns(4)
    c[0].metric("ยอดรวม", baht(s["ยอดรวม"]))
    c[1].metric("จ่ายแล้ว", baht(s["จ่ายแล้ว"]))
    c[2].metric("คงเหลือ", baht(s["คงเหลือ"]))
    c[3].metric("ครบกำหนดถัดไป", s["ครบกำหนดถัดไป"].strftime("%d/%m/") + str(s["ครบกำหนดถัดไป"].year + 543)
                if s["ครบกำหนดถัดไป"] else "-")
    st.progress(min(1.0, s["จ่ายแล้ว"] / s["ยอดรวม"]) if s["ยอดรวม"] else 0.0, text="ความคืบหน้าการชำระ")
    st.subheader("รายการกู้")
    st.dataframe(loans_all[loans_all["debtor_name"] == d].drop(columns=["_row", "dt"], errors="ignore"),
                 use_container_width=True, hide_index=True)
    st.subheader("ประวัติรับชำระ")
    pp = pays_all[pays_all["debtor_name"] == d] if not pays_all.empty else pays_all
    if pp.empty:
        st.info("ยังไม่มีการรับชำระ")
    else:
        st.dataframe(pp.drop(columns=["_row", "dt"], errors="ignore"), use_container_width=True, hide_index=True)

# ---------- แก้ไข/ลบ ----------
elif page == PAGES[5]:
    hero("✏️ แก้ไข/ลบรายการ", "เลือกรายการจากรายชื่อ ไม่ต้องจำเลขแถว")
    need_data()
    t1, t2 = st.tabs(["รายการกู้", "รายการรับชำระ"])
    with t1:
        ids = loans_all.sort_values("dt", ascending=False).index.tolist()
        i = st.selectbox("เลือกรายการกู้", ids, format_func=lambda k: f"{loans_all.loc[k, 'date_time']} · {loans_all.loc[k, 'debtor_name']} · {loans_all.loc[k, 'principal']:,.2f}")
        r = loans_all.loc[i]
        c1, c2 = st.columns(2)
        nn = c1.text_input("ชื่อลูกหนี้", r["debtor_name"], key="e_n")
        nl = c2.text_input("LINE/โทร", str(r.get("line_id", "")), key="e_l")
        c3, c4 = st.columns(2)
        np_ = c3.number_input("เงินต้น", min_value=0.0, value=float(r["principal"]), step=100.0, key="e_p")
        old_rate = float(r["interest"] / r["principal"] * 100) if r["principal"] else 20.0
        nr = c4.number_input("ดอกเบี้ย (%)", value=old_rate, step=1.0, key="e_r")
        nd = datetime_picker("eloan", default=r["dt"] if pd.notna(r["dt"]) else now_th())
        b1, b2 = st.columns(2)
        if b1.button("💾 บันทึกการแก้ไข", use_container_width=True, key="sv1"):
            ni = np_ * nr / 100
            update_cells("loans", r["_row"], {2: nn.strip(), 3: nl.strip(), 4: str(nd.year + 543), 5: nd.strftime(FMT),
                                              6: np_, 7: ni, 8: np_ + ni})
            st.success("แก้ไขเรียบร้อย")
            st.rerun()
        ok = b2.checkbox("ยืนยันว่าต้องการลบรายการนี้", key="cf1")
        if b2.button("🗑️ ลบรายการกู้", disabled=not ok, use_container_width=True, key="dl1"):
            delete_row("loans", r["_row"])
            st.success("ลบแล้ว")
            st.rerun()
    with t2:
        if pays_all.empty:
            st.info("ยังไม่มีรายการรับชำระ")
        else:
            ids = pays_all.sort_values("dt", ascending=False).index.tolist()
            j = st.selectbox("เลือกรายการรับชำระ", ids, format_func=lambda k: f"{pays_all.loc[k, 'date_time']} · {pays_all.loc[k, 'debtor_name']} · {pays_all.loc[k, 'paid_amount']:,.2f}")
            r = pays_all.loc[j]
            na = st.number_input("จำนวนเงิน", min_value=0.0, value=float(r["paid_amount"]), step=100.0, key="e_a")
            nd = datetime_picker("epay", default=r["dt"] if pd.notna(r["dt"]) else now_th())
            b1, b2 = st.columns(2)
            if b1.button("💾 บันทึกการแก้ไข", use_container_width=True, key="sv2"):
                update_cells("payments", r["_row"], {3: str(nd.year + 543), 4: nd.strftime(FMT), 5: na})
                st.success("แก้ไขเรียบร้อย")
                st.rerun()
            ok = b2.checkbox("ยืนยันว่าต้องการลบรายการนี้", key="cf2")
            if b2.button("🗑️ ลบรายการรับชำระ", disabled=not ok, use_container_width=True, key="dl2"):
                delete_row("payments", r["_row"])
                st.success("ลบแล้ว")
                st.rerun()

# ---------- LINE ----------
elif page == PAGES[6]:
    hero("💬 แจ้งเตือนทาง LINE", "สร้างข้อความสรุปยอดและเปิดส่งใน LINE ได้ทันที")
    need_data()
    sel = st.selectbox("ลูกหนี้", sorted(summary["ลูกหนี้"]))
    s = summary[summary["ลูกหนี้"] == sel].iloc[0]
    tone = st.radio("น้ำเสียง", ["สุภาพ", "เตือนใกล้ครบกำหนด", "ทวงถามเร่งด่วน"], horizontal=True)
    closing = {"สุภาพ": "รบกวนชำระตามสะดวก ขอบคุณครับ 🙏",
               "เตือนใกล้ครบกำหนด": "ใกล้ถึงกำหนดชำระแล้ว กรุณาชำระภายในกำหนดด้วยนะครับ 🙏",
               "ทวงถามเร่งด่วน": "ยอดนี้เกินกำหนดแล้ว กรุณาติดต่อกลับและชำระโดยเร็วที่สุดครับ"}[tone]
    due = s["ครบกำหนดถัดไป"].strftime("%d/%m/") + str(s["ครบกำหนดถัดไป"].year + 543) if s["ครบกำหนดถัดไป"] else "-"
    msg = f"""🔔 สรุปยอดหนี้
👤 คุณ {sel}
----------------------------------------
📌 เงินต้นคงเหลือ: {s['ต้นค้าง']:,.2f} บาท
📈 ดอกเบี้ยคงค้าง: {s['ดอกค้าง']:,.2f} บาท
💰 ยอดรวมคงเหลือ: {s['คงเหลือ']:,.2f} บาท
💵 ชำระมาแล้ว: {s['จ่ายแล้ว']:,.2f} บาท
📅 กำหนดชำระถัดไป: {due}
----------------------------------------
{closing}"""
    msg = st.text_area("ข้อความ (แก้ไขได้)", msg, height=260)
    c1, c2 = st.columns(2)
    c1.link_button("📲 เปิดส่งใน LINE", "https://line.me/R/msg/text/?" + urllib.parse.quote(msg), use_container_width=True)
    c2.download_button("📥 ดาวน์โหลด (.txt)", msg.encode("utf-8-sig"), f"line_{sel}.txt", "text/plain", use_container_width=True)

# ---------- ตั้งค่า ----------
elif page == PAGES[7]:
    hero("⚙️ ตั้งค่า", "ปรับธีม ข้อความต้อนรับ พื้นหลัง รหัสผ่าน และสำรองข้อมูล")
    cur = get_setting(user)
    t1, t2, t3 = st.tabs(["🎨 หน้าตา", "🔑 รหัสผ่าน", "💾 สำรองข้อมูล"])
    with t1:
        keys = list(THEMES)
        theme = st.selectbox("ธีมสี", keys, index=keys.index(cur["theme_name"]) if cur.get("theme_name") in keys else 0)
        welcome = st.text_input("ข้อความต้อนรับ", cur.get("welcome_msg", ""))
        bg = st.text_input("ลิงก์รูปพื้นหลัง (เว้นว่างถ้าไม่ใช้)", cur.get("bg_image", ""))
        p = THEMES[theme]["primary"]
        st.markdown(f"<div class='hero' style='border-color:{p}'><h2 style='color:{p}'>ตัวอย่างสีธีม</h2><p>{html.escape(welcome)}</p></div>",
                    unsafe_allow_html=True)
        if st.button("💾 บันทึกการตั้งค่า"):
            save_setting(user, theme, welcome, bg.strip())
            st.success("บันทึกแล้ว")
            st.rerun()
    with t2:
        old, new, new2 = (st.text_input("รหัสผ่านเดิม", type="password"), st.text_input("รหัสผ่านใหม่ (อย่างน้อย 6 ตัว)", type="password"),
                          st.text_input("ยืนยันรหัสผ่านใหม่", type="password"))
        if st.button("เปลี่ยนรหัสผ่าน"):
            us = load("users")
            row = us[us["username"].astype(str) == user].iloc[0]
            if hashlib.sha256(old.encode()).hexdigest() != str(row["password"]):
                st.error("รหัสผ่านเดิมไม่ถูกต้อง")
            elif len(new) < 6 or new != new2:
                st.error("รหัสผ่านใหม่ต้องยาวอย่างน้อย 6 ตัวและกรอกให้ตรงกันทั้งสองช่อง")
            else:
                update_cells("users", row["_row"], {2: hashlib.sha256(new.encode()).hexdigest()})
                st.success("เปลี่ยนรหัสผ่านแล้ว")
    with t3:
        st.caption("ดาวน์โหลดข้อมูลทั้งหมดเก็บไว้เป็นไฟล์สำรอง")
        for label, df in (("รายการกู้", loans_all), ("รับชำระ", pays_all)):
            if not df.empty:
                st.download_button(f"📥 {label} (CSV)", df.drop(columns=["_row", "dt"], errors="ignore").to_csv(index=False).encode("utf-8-sig"),
                                   f"{label}.csv", "text/csv")

# ---------- ผู้ใช้ ----------
elif page == "👥 จัดการผู้ใช้":
    hero("👥 จัดการผู้ใช้", "เฉพาะผู้ดูแลระบบ")
    us = load("users")
    if not us.empty:
        st.dataframe(us[["username", "role"]], use_container_width=True, hide_index=True)
    with st.form("add_user"):
        c1, c2, c3 = st.columns(3)
        nu, npw = c1.text_input("ชื่อผู้ใช้ใหม่"), c2.text_input("รหัสผ่าน", type="password")
        nr = c3.selectbox("สิทธิ์", ["user", "admin"])
        if st.form_submit_button("➕ เพิ่มผู้ใช้"):
            if not nu.strip() or len(npw) < 6:
                st.error("กรอกชื่อผู้ใช้ และรหัสผ่านอย่างน้อย 6 ตัว")
            elif not us.empty and nu in us["username"].astype(str).values:
                st.error("ชื่อผู้ใช้นี้มีอยู่แล้ว")
            else:
                add_row("users", [nu.strip(), hashlib.sha256(npw.encode()).hexdigest(), nr])
                st.success("เพิ่มผู้ใช้แล้ว")
                st.rerun()
    others = us[us["username"].astype(str) != user] if not us.empty else us
    if not others.empty:
        d = st.selectbox("ลบผู้ใช้", others["username"].tolist())
        ok = st.checkbox("ยืนยันการลบผู้ใช้นี้", key="udel")
        if st.button("🗑️ ลบผู้ใช้ที่เลือก", disabled=not ok):
            delete_row("users", others[others["username"] == d].iloc[0]["_row"])
            st.rerun()
