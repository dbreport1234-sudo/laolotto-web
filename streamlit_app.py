# -*- coding: utf-8 -*-
"""LAO LOTTO PRO (Web) — รันบนมือถือ/เว็บด้วย Streamlit  |  ข้อมูล: data/lao_lottery_full.csv (อัปเดตโดย GitHub Actions)"""
import glob, gzip, json, math
from pathlib import Path

import pandas as pd
import streamlit as st

import formula_engine as fe

ROOT = Path(__file__).parent
DATA = ROOT / "data" / "lao_lottery_full.csv"
PRED_DIR = ROOT / "data" / "predictions"
TARGETS = {"2 ตัวบน": "top2", "2 ตัวล่าง": "bottom2", "3 ตัวบน": "top3"}
KEY_LABEL = {v: k for k, v in TARGETS.items()}

st.set_page_config(page_title="Lao Lotto Pro", page_icon="🎯", layout="wide")


# ----------------------------------------------------------------- รหัสผ่าน (ถ้าตั้ง APP_PASSWORD ใน Secrets)
def gate():
    try: pw = st.secrets["APP_PASSWORD"]
    except Exception: return
    if st.session_state.get("ok"): return
    x = st.text_input("รหัสผ่าน", type="password")
    if x and x == pw: st.session_state["ok"] = True; st.rerun()
    if x: st.error("รหัสผ่านไม่ถูกต้อง")
    st.stop()
gate()


# ----------------------------------------------------------------- ข้อมูล
def to_iso(s):
    d, m, y = s.split("/"); y = int(y); y -= 543 if y > 2400 else 0
    return f"{y:04d}-{int(m):02d}-{int(d):02d}"

@st.cache_data(ttl=600)
def load_raw():
    d = pd.read_csv(DATA, dtype=str, encoding="utf-8-sig")
    return pd.DataFrame({"draw_date": d.draw_date.map(to_iso), "digit_6": d.number6, "top3": d.number3_top,
                         "top2": d.number2_top, "bottom2": d.number2_bottom}).sort_values("draw_date").reset_index(drop=True)

@st.cache_data(ttl=600)
def load_clean():
    return fe.clean_draws(load_raw())

@st.cache_resource(show_spinner="กำลังรันทุกสูตร (ครั้งแรกใช้เวลาราว 10-20 วินาที) ...")
def run_analysis(data_key, n_test, win, K, N2, N3):
    clean, _ = load_clean()
    top = fe.analyze(clean, n_test, win, K, N2, N3); top["df"] = clean
    dfb = fe.bottom_frame(clean); bot = None
    if len(dfb) >= win + 90:
        bot = fe.analyze(dfb, n_test, win, K, N2, N3, want=2); bot["df"] = dfb
    return top, bot

def chi2_p(counts):
    n = sum(counts); k = len(counts) - 1; e = n / len(counts)
    x = sum((c - e) ** 2 / e for c in counts)
    z = ((x / k) ** (1 / 3) - (1 - 2 / (9 * k))) / math.sqrt(2 / (9 * k))
    return x, 0.5 * math.erfc(z / math.sqrt(2))


raw = load_raw()
clean, rep = load_clean()
data_key = f"{len(clean)}|{clean.draw_date.iloc[-1]}"

# ----------------------------------------------------------------- sidebar
st.sidebar.title("🎯 Lao Lotto Pro")
st.sidebar.caption(f"ข้อมูล {len(raw):,} งวด • สะอาด {len(clean):,} งวด • ล่าสุด {raw.draw_date.iloc[-1]}")
n_test = st.sidebar.slider("ทดสอบย้อนหลัง (งวด)", 100, 600, 400, 50)
win = st.sidebar.slider("ช่วงคัดสูตร (งวด)", 30, 200, 100, 10)
K = st.sidebar.slider("คัดกี่สูตร (K)", 1, 15, 5)
N2 = st.sidebar.slider("ชุดเด่น 2 ตัว: กี่เลข", 1, 10, 3)
N3 = st.sidebar.slider("ชุดเด่น 3 ตัว: กี่เลข", 1, 15, 5)
st.sidebar.warning("เพื่อการศึกษาสถิติเท่านั้น ผลย้อนหลังไม่รับประกันงวดหน้า ผลแต่ละงวดเป็นอิสระต่อกัน")

top, bot = run_analysis(data_key, n_test, win, K, N2, N3)
RES = {"top2": (top, 2), "top3": (top, 3), "bottom2": (bot, 2)}

tabs = st.tabs(["🏠 ภาพรวม", "🧪 สูตร & ชุดลอจิก", "🏆 ชุดเด่น", "📈 ติดตามผลจริง", "🔎 ความถี่เลข", "💰 แผนตามเลข", "ℹ️ วิธีอ่านผล"])


# ----------------------------------------------------------------- ภาพรวม
with tabs[0]:
    c = st.columns(4)
    c[0].metric("งวดทั้งหมด", f"{len(raw):,}"); c[1].metric("ใช้วิเคราะห์ได้ (สะอาด)", f"{len(clean):,}")
    c[2].metric("ล่าสุด", raw.draw_date.iloc[-1]); c[3].metric("งวดถัดไป (ประมาณ)", top["next_date"])
    st.subheader("10 งวดล่าสุด")
    st.dataframe(raw.tail(10).iloc[::-1].rename(columns={"draw_date": "วันที่", "digit_6": "เลข 6 ตัว", "top3": "3 ตัวบน", "top2": "2 ตัวบน", "bottom2": "2 ตัวล่าง"}),
                 hide_index=True, width="stretch")
    st.subheader("คุณภาพข้อมูล")
    ok = raw[raw.digit_6.str.fullmatch(r"\d{6}")]
    q = st.columns(4)
    q[0].metric("3 ตัวบน = ท้ายเลข 6 ตัว", f"{(ok.top3 == ok.digit_6.str[-3:]).mean():.1%}")
    q[1].metric("2 ตัวบน = ท้ายเลข 6 ตัว", f"{(ok.top2 == ok.digit_6.str[-2:]).mean():.1%}")
    q[2].metric("2 ตัวล่าง = หลัก 3-4", f"{(ok.bottom2 == ok.digit_6.str[2:4]).mean():.1%}")
    q[3].metric("แถวที่ตัดออก (เลขซ้ำ/เสีย)", rep["dup6"] + rep["year_like"] + rep["invalid"])
    st.subheader("ทดสอบความเป็นสุ่ม (chi-square)")
    rows = []
    for lab, ser in (("2 ตัวบน (100 ค่า)", clean.t2), ("2 ตัวล่าง (100 ค่า)", clean.b2[clean.b2 != ""]),
                     ("หลักสิบของ 2 ตัวบน", clean.t2.str[0]), ("หลักหน่วยของ 2 ตัวบน", clean.t2.str[1])):
        vc = ser.value_counts(); cells = 100 if "100" in lab else 10
        counts = [int(vc.get(f"{i:02d}" if cells == 100 else str(i), 0)) for i in range(cells)]
        x, p = chi2_p(counts); rows.append({"ตัวชี้วัด": lab, "chi-square": round(x, 1), "p-value": round(p, 3),
                                           "ผล": "ไม่พบความผิดปกติ" if p >= 0.05 else "⚠ เบี่ยงจากสุ่มเรียบ"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("p-value สูง = การกระจายตัวของเลขสอดคล้องกับการสุ่มเรียบ (ทุกเลขโอกาสเท่ากัน) — ถ้าเป็นแบบนั้น ไม่มีสูตรใดทายล่วงหน้าได้")
    freq = clean.t2.value_counts().head(15)
    st.bar_chart(freq, height=220)


# ----------------------------------------------------------------- สูตร & ชุดลอจิก
with tabs[1]:
    lab = st.radio("เป้าหมาย", list(TARGETS), horizontal=True, key="t1")
    res, kind = RES[TARGETS[lab]]
    if res is None:
        st.info("ข้อมูล 2 ตัวล่างยังไม่พอ")
    else:
        bt = res["bt"]; bt = bt[bt.kind == kind].copy()
        m = len(bt); sig_raw = int((bt.p < .05).sum()); sig_adj = int((bt.p_adj < .05).sum())
        c = st.columns(4)
        c[0].metric("จำนวนสูตร", m); c[1].metric("ดูเหมือนแม่น (p<0.05)", sig_raw, help=f"คาดว่าเกิดจากดวงล้วน ≈ {0.05 * m:.1f}")
        c[2].metric("ผ่านเกณฑ์หลังแก้ Bonferroni", sig_adj)
        a_n, a_h = int(bt.after3_n.sum()), int(bt.after3_hit.sum())
        c[3].metric("หลังพลาด 3 งวดติด → ถูกต่อ", f"{100 * a_h / a_n:.2f}%" if a_n else "-",
                    help=f"ถ้า 'ใกล้ถึงรอบ' จริง ต้องสูงกว่าอัตราปกติ ({(bt.exp_pct * bt.after3_n).sum() / max(a_n, 1):.2f}%)")
        st.subheader("สรุปรายชุดลอจิก")
        gs = fe.group_summary(bt).rename(columns={"group": "ชุดลอจิก", "formulas": "สูตร", "avg_diff": "ส่วนต่างเฉลี่ย %", "best": "ดีที่สุดในชุด",
                                                  "best_hit": "ถูก", "sig_raw": "p<0.05", "sig_adj": "ผ่าน Bonf.", "cover5": "ถูกใน5งวด %", "exp_cover5": "คาดสุ่ม %"})
        st.dataframe(gs.round(2), hide_index=True, width="stretch")
        st.subheader("ทุกสูตร")
        f1, f2 = st.columns(2)
        g = f1.selectbox("กรองชุดลอจิก", ["ทุกชุด"] + sorted(bt.group.unique()))
        s = f2.text_input("ค้นหาชื่อสูตร")
        v = bt if g == "ทุกชุด" else bt[bt.group == g]
        if s: v = v[v["name"].str.contains(s, case=False, regex=False)]
        v = v.assign(ผล=lambda d: d.apply(lambda r: "✅ ผ่านเกณฑ์" if r.p_adj < .05 else ("⚠ อาจบังเอิญ" if r.p < .05 else "—"), axis=1),
                     after3=lambda d: d.after3_hit.astype(int).astype(str) + "/" + d.after3_n.astype(int).astype(str))
        st.dataframe(v[["name", "picks", "hits", "tests", "hit_pct", "exp_pct", "cover5", "exp_cover5", "max_miss", "cur_miss", "after3", "p", "p_adj", "ผล"]]
                     .rename(columns={"name": "สูตร", "picks": "เลข", "hits": "ถูก", "tests": "ทดสอบ", "hit_pct": "ถูก %", "exp_pct": "สุ่ม %", "cover5": "ถูกใน5งวด %",
                                      "exp_cover5": "สุ่ม5 %", "max_miss": "พลาดสูงสุด", "cur_miss": "พลาดติดตอนนี้", "after3": "หลังพลาด3→ถูก", "p": "p", "p_adj": "p แก้"})
                     .round(3), hide_index=True, width="stretch", height=420)
        pick_name = st.selectbox("ดูเลขที่สูตรนี้ทายสำหรับงวดหน้า", list(v["name"]) or ["-"])
        if pick_name in res["next_picks"]:
            st.success(f"{pick_name} → งวด {res['next_date']}: " + (" ".join(res["next_picks"][pick_name]) or "(ไม่มีเลข)"))


# ----------------------------------------------------------------- ชุดเด่น
with tabs[2]:
    st.write(f"**งวดถัดไป (ประมาณ): {top['next_date']}**")
    st.caption("ชุดเด่น = ทุกงวดคัด K สูตรที่เกินค่าสุ่มมากสุดในช่วงคัดสูตรก่อนหน้า แล้วโหวตเป็นชุดเดียว — ผลย้อนหลังด้านล่างวัดกับงวดที่ระบบยังไม่เคยเห็น")
    rows = []
    for key in ("top2", "bottom2", "top3"):
        res, kind = RES[key]
        c = res["champ"].get(kind) if res else None
        if c: rows.append({"เป้าหมาย": KEY_LABEL[key], "ชุดเด่นงวดหน้า": " ".join(c["numbers"]), "เด่นสุด": c["numbers"][0] if c["numbers"] else "-",
                           "ย้อนหลัง ถูก/ทดสอบ": f"{c['hits']}/{c['tests']}", "ถูก %": round(c["hit_pct"], 2), "คาดสุ่ม %": round(c["exp_pct"], 2), "p": round(c["p"], 3),
                           "สูตรที่ถูกคัด": " | ".join(n.split("-")[0] + f" ({z:+.1f})" for n, z in c["formulas"])})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    cons = fe.consensus(top["next_picks"])
    st.write("เลข 2 ตัวบนที่หลายสูตรเลือกตรงกัน: " + ", ".join(f"**{n}** (×{c})" for n, c in cons))
    st.info("ถ้า 'ถูก %' ใกล้เคียง 'คาดสุ่ม %' แปลว่าการเลือกสูตรที่ถูกสูงสุดย้อนหลังไม่ได้ช่วยทายงวดหน้า และเลขที่หลายสูตรเลือกตรงกันก็ไม่ได้มีโอกาสออกมากกว่าเลขอื่น")


# ----------------------------------------------------------------- ติดตามผลจริง
with tabs[3]:
    st.caption("คำทายถูกสร้างอัตโนมัติ 'ก่อนผลออก' และ commit ลง GitHub (ไม่เขียนทับ) — นี่คือหลักฐานเดียวที่เชื่อได้ ต้องสะสมหลายสิบงวด")
    files = sorted(glob.glob(str(PRED_DIR / "*.json.gz")))
    if not files:
        st.info("ยังไม่มีไฟล์คำทาย — จะถูกสร้างอัตโนมัติโดย GitHub Actions")
    else:
        d = raw.sort_values("draw_date"); recs = []; pending = []
        for fpath in files:
            with gzip.open(fpath, "rt", encoding="utf-8") as f: P = json.load(f)
            td = P["target_date"]; lim = (pd.Timestamp(td) + pd.Timedelta(days=3)).strftime("%Y-%m-%d")
            m = d[(d.draw_date >= td) & (d.draw_date <= lim)]
            if m.empty: pending.append(td); continue
            x = m.iloc[0]; d6 = x.digit_6 if len(x.digit_6) == 6 else ""
            actual = {"top2": d6[-2:] or x.top2, "top3": d6[-3:] or x.top3, "bottom2": x.bottom2}
            for tkey, T in P["targets"].items():
                kind = 3 if tkey == "top3" else 2
                items = dict(T["picks"])
                if T.get("champion") and T["champion"].get("numbers"): items[f"🏆 ชุดเด่น {KEY_LABEL[tkey]}"] = " ".join(T["champion"]["numbers"])
                for name, pk in items.items():
                    pl = pk.split()
                    recs.append(dict(target=tkey, formula=name, hit=int(actual[tkey] in pl), exp=len(pl) / 10 ** kind, champ=name.startswith("🏆")))
        st.write(f"ไฟล์คำทาย {len(files)} งวด | ตรวจผลแล้ว {len(files) - len(pending)} งวด | รอผล: {', '.join(pending) or '-'}")
        if recs:
            R = pd.DataFrame(recs)
            g = R.groupby(["target", "formula", "champ"]).agg(ตรวจแล้ว=("hit", "count"), ถูก=("hit", "sum"), exp=("exp", "mean")).reset_index()
            g["ถูก %"] = (100 * g.ถูก / g.ตรวจแล้ว).round(2); g["คาดสุ่ม %"] = (100 * g.exp).round(2)
            g["เป้าหมาย"] = g.target.map(KEY_LABEL)
            g = g.sort_values(["champ", "ถูก"], ascending=[False, False])
            st.dataframe(g[["เป้าหมาย", "formula", "ตรวจแล้ว", "ถูก", "ถูก %", "คาดสุ่ม %"]].rename(columns={"formula": "สูตร / ชุดเด่น"}),
                         hide_index=True, width="stretch", height=480)


# ----------------------------------------------------------------- ความถี่เลข + สถิติรายช่วง
with tabs[4]:
    st.subheader("ความถี่ผลจริงย้อนหลัง")
    st.caption("ส่วนนี้เป็นสถิติย้อนหลัง ไม่ใช่การรับประกันว่าเลขที่ออกบ่อยจะออกซ้ำในงวดหน้า")
    target_lab = st.radio("วิเคราะห์ผลจริง", ["2 ตัวบน", "2 ตัวล่าง", "3 ตัวบน"], horizontal=True, key="freq_target")
    target_col = {"2 ตัวบน": "t2", "2 ตัวล่าง": "b2", "3 ตัวบน": "t3"}[target_lab]
    freq_series = clean[target_col].astype(str)
    freq_series = freq_series[freq_series.str.fullmatch(r"\d{2}" if target_col != "t3" else r"\d{3}")]
    max_window = max(1, min(500, len(freq_series)))
    default_window = min(100, max_window)
    window = st.slider("จำนวนงวดที่ใช้คำนวณ", 10, max(10, max_window), max(10, default_window), 10, key="freq_window")
    recent = freq_series.tail(window)
    total_space = 100 if target_col != "t3" else 1000
    all_nums = [f"{i:02d}" if total_space == 100 else f"{i:03d}" for i in range(total_space)]
    counts = recent.value_counts()
    freq_table = pd.DataFrame({"เลข": all_nums})
    freq_table["ออก"] = freq_table["เลข"].map(counts).fillna(0).astype(int)
    freq_table["ความถี่ %"] = (100 * freq_table["ออก"] / max(1, len(recent))).round(2)
    freq_table["ไม่ออกติด (นับจากงวดล่าสุด)"] = freq_table["เลข"].map(
        {n: (len(recent) - 1 - max([i for i, x in enumerate(recent.tolist()) if x == n], default=-1))
         for n in all_nums}
    ).fillna(len(recent)).astype(int)
    hot, cold = st.columns(2)
    with hot:
        st.markdown("**เลขออกบ่อยสุดในช่วงที่เลือก**")
        st.dataframe(freq_table.sort_values(["ออก", "เลข"], ascending=[False, True]).head(20),
                     hide_index=True, width="stretch")
    with cold:
        st.markdown("**เลขออกน้อยสุดในช่วงที่เลือก**")
        st.dataframe(freq_table.sort_values(["ออก", "เลข"], ascending=[True, True]).head(20),
                     hide_index=True, width="stretch")
    st.markdown("**ความถี่รายหลัก**")
    digit_rows = []
    for pos in range(len(recent.iloc[0]) if len(recent) else (3 if target_col == "t3" else 2)):
        dc = recent.str[pos].value_counts()
        for digit in map(str, range(10)):
            digit_rows.append({"ตำแหน่ง": ["หลักร้อย", "หลักสิบ", "หลักหน่วย"][pos] if target_col == "t3" else ["หลักสิบ", "หลักหน่วย"][pos],
                               "เลข": digit, "ออก": int(dc.get(digit, 0)),
                               "ความถี่ %": round(100 * dc.get(digit, 0) / max(1, len(recent)), 2)})
    digit_df = pd.DataFrame(digit_rows)
    st.dataframe(digit_df, hide_index=True, width="stretch")
    st.markdown("**ผลรวมความถี่ทั้งชุด**")
    st.bar_chart(freq_table.sort_values("เลข").set_index("เลข")["ออก"], height=220)
    st.info(
        f"ช่วงนี้มีผลจริง {len(recent):,} งวด จากพื้นที่เลข {total_space:,} ค่า "
        f"ค่าเฉลี่ยเชิงสุ่มประมาณ {len(recent)/total_space:.2f} ครั้งต่อเลข "
        "ความต่างระหว่างเลขมักเกิดขึ้นได้เองจากความผันผวนของตัวอย่าง และเลขที่ค้างนานไม่ได้แปลว่าจะถึงคิว"
    )


# ----------------------------------------------------------------- แผนตามเลข
with tabs[5]:
    st.caption("คำนวณว่า 'ตามเลขเดิมไม่เกิน R งวด' เสี่ยง/คุ้มแค่ไหน — ผลแต่ละงวดเป็นอิสระ การพลาดมาแล้วไม่ทำให้งวดหน้าถูกง่ายขึ้น")
    c = st.columns(6)
    kind_lab = c[0].selectbox("ชนิด", ["2 ตัว", "3 ตัว"]); kind = 2 if kind_lab == "2 ตัว" else 3
    pay = c[1].number_input("เท่าที่จ่าย", 1.0, 5000.0, 60.0 if kind == 2 else 500.0, help="ปรับตามอัตราจริงของเจ้ามือ")
    npk = c[2].number_input("เลขต่องวด", 1, 100, 3); R = c[3].number_input("จำนวนรอบ R", 1, 12, 5)
    stake = c[4].number_input("เงินต่อเลข", 1.0, 100000.0, 10.0); mode = c[5].selectbox("เพิ่มเงิน", ["flat", "double", "x1.5", "fib"])
    rows, sm = fe.plan_table(10 ** kind, int(npk), pay, int(R), stake, mode)
    st.dataframe(pd.DataFrame(rows).rename(columns={"round": "รอบ", "stake": "เงินต่อเลข", "cost": "ลงรอบนี้", "cum_cost": "ลงสะสม", "p_first": "โอกาสถูกครั้งแรกรอบนี้",
                                                    "p_cum": "โอกาสถูกสะสม", "profit": "กำไรสุทธิถ้าถูกรอบนี้"}).round(3), hide_index=True, width="stretch")
    m = st.columns(4)
    m[0].metric(f"ถูกอย่างน้อย 1 ครั้งใน {int(R)} งวด", f"{100 * sm['p_hit']:.1f}%"); m[1].metric("พลาดหมด", f"{100 * sm['p_all_miss']:.1f}%")
    m[2].metric("ขาดทุนสูงสุด", f"{sm['worst_loss']:,.0f}"); m[3].metric("ค่าคาดหวังสุทธิ", f"{sm['ev']:+,.1f}", f"{100 * sm['ev_per_cost']:+.1f}% ของเงินที่ลง")
    st.divider(); st.subheader("จำลองกับประวัติจริง")
    s1, s2 = st.columns([1, 3])
    t_lab = s1.selectbox("เป้าหมาย", ["2 ตัวบน", "2 ตัวล่าง", "3 ตัวบน"], key="simt")
    res, k2 = RES[TARGETS[t_lab]]
    if res is not None and k2 == kind:
        names = list(res["bt"][res["bt"].kind == k2]["name"])
        nm = s2.selectbox("สูตร", names, key="simf")
        if st.button("จำลอง"):
            r = fe.simulate_plan(res["df"], res["tbl"], nm, k2, res["start"], int(R), pay, stake, mode)
            th = fe.plan_table(10 ** k2, len(next(iter(res["tbl"][nm].values()))), pay, int(R), stake, mode)[1]
            a = st.columns(4)
            a[0].metric("จำนวนรอบแผน", r["cycles"]); a[1].metric(f"ถูกภายใน {int(R)} งวด", f"{r['hit_rate']:.1f}%", f"ทฤษฎีสุ่ม {100 * th['p_hit']:.1f}%")
            a[2].metric("กำไร/ขาดทุนสุทธิ", f"{r['net']:+,.0f}"); a[3].metric("ขาดทุนสะสมต่ำสุด", f"{r['worst']:+,.0f}")
            st.write("ถูกที่งวดที่:", r["where"] or "-")
            st.caption("สูตรเดียวจากไม่กี่สิบรอบแปรปรวนมาก อย่าสรุปจากตัวเลขนี้ — ดู p-value และผลจริงที่ติดตามต่อเนื่อง")
    else:
        st.info("เลือกชนิดให้ตรงกับเป้าหมาย (2 ตัว ↔ 2 ตัวบน/ล่าง, 3 ตัว ↔ 3 ตัวบน)")


# ----------------------------------------------------------------- วิธีอ่านผล
with tabs[6]:
    st.markdown("""
**ระบบทำอะไร** — ทดสอบสูตรกว่า 270 สูตรกับผลจริงทีละงวดโดย *ไม่แอบดูอนาคต* (แต่ละงวดใช้เฉพาะข้อมูลก่อนหน้า) แล้วเทียบกับค่าที่การสุ่มล้วนจะได้

**อ่านค่าอย่างไร**
- *ถูก % vs สุ่ม %* — ถ้าใกล้กัน สูตรนั้นไม่ได้ดีกว่าการสุ่ม
- *p-value* — โอกาสที่ดวงล้วน ๆ จะได้ผลดีขนาดนี้ ทดสอบหลายร้อยสูตรจึงต้องดู *p แก้ (Bonferroni)* ด้วย: ถ้ามากกว่า 0.05 แปลว่ายังอธิบายด้วยดวงได้
- *ถูกใน 5 งวด* — สัดส่วนช่วง 5 งวดที่มีถูกอย่างน้อย 1 ครั้ง (เทียบกับค่าสุ่ม)
- *หลังพลาด 3 งวดติด → ถูกต่อ* — ถ้าเลขใกล้ 'ถึงรอบ' ต้องสูงกว่าอัตราปกติ ผลที่วัดได้ไม่ต่างจากปกติ

**ข้อจำกัด** — ผลหวยแต่ละงวดเป็นอิสระต่อกัน ไม่มีสูตรใดรับประกันว่าจะถูกในรอบที่ 4-5 การเพิ่มเงินตามเลขเพิ่มแต่ยอดขาดทุนเมื่อพลาด ค่าคาดหวังของการแทงเป็นลบเสมอ
""")
