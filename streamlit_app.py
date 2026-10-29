# -*- coding: utf-8 -*-
"""LAO LOTTO PRO (Web) — ระบบวิเคราะห์และทำนายผลหวยลาวสมบูรณ์แบบ"""

import glob
import gzip
import json
import math
from pathlib import Path

import pandas as pd
import streamlit as st

import formula_engine as fe

ROOT = Path(__file__).parent
DATA = ROOT / "data" / "lao_lottery_full.csv"
PRED_DIR = ROOT / "data" / "predictions"
TARGETS = {"2 ตัวบน": "top2", "2 ตัวล่าง": "bottom2", "3 ตัวบน": "top3"}
KEY_LABEL = {v: k for k, v in TARGETS.items()}

st.set_page_config(
    page_title="Lao Lotto Pro", page_icon="🎯", layout="wide"
)


# ----------------------------------------------------------------- ระบบล็อครหัสผ่าน (ถ้าตั้งไว้)
def gate():
  try:
    pw = st.secrets["APP_PASSWORD"]
  except Exception:
    return
  if st.session_state.get("ok"):
    return
  x = st.text_input("รหัสผ่านเข้าใช้งาน", type="password")
  if x and x == pw:
    st.session_state["ok"] = True
    st.rerun()
  if x:
    st.error("รหัสผ่านไม่ถูกต้อง")
  st.stop()


gate()


# ----------------------------------------------------------------- โหลดและเตรียมข้อมูล
def to_iso(s):
  d, m, y = s.split("/")
  y = int(y)
  y -= 543 if y > 2400 else 0
  return f"{y:04d}-{int(m):02d}-{int(d):02d}"


@st.cache_data(ttl=600)
def load_raw():
  d = pd.read_csv(DATA, dtype=str, encoding="utf-8-sig")
  if "number6" in d.columns:
    d = d.rename(
        columns={
            "number6": "digit_6",
            "number3_top": "top3",
            "number2_top": "top2",
            "number2_bottom": "bottom2",
        }
    )
  d["draw_date"] = d["draw_date"].map(to_iso)
  return d.sort_values("draw_date").reset_index(drop=True)


@st.cache_data(ttl=600)
def load_clean():
  return fe.clean_draws(load_raw())


@st.cache_resource(
    show_spinner="กำลังคำนวณและวิเคราะห์สูตรทั้งหมด (ใช้เวลา 10-15 วินาที)..."
)
def run_analysis(data_key, n_test, win, K, N2, N3):
  clean, _ = load_clean()
  top = fe.analyze(clean, n_test, win, K, N2, N3)
  top["df"] = clean
  dfb = fe.bottom_frame(clean)
  bot = None
  if len(dfb) >= win + 90:
    bot = fe.analyze(dfb, n_test, win, K, N2, N3, want=2)
    bot["df"] = dfb
  return top, bot


raw = load_raw()
clean, rep = load_clean()
data_key = f"{len(clean)}|{clean.draw_date.iloc[-1]}"

# ----------------------------------------------------------------- แถบเมนูด้านข้าง (Sidebar)
st.sidebar.title("🎯 Lao Lotto Pro")
st.sidebar.caption(
    f"ข้อมูล {len(raw):,} งวด • สะอาด {len(clean):,} งวด • ล่าสุด"
    f" {raw.draw_date.iloc[-1]}"
)
n_test = st.sidebar.slider("ทดสอบย้อนหลัง (งวด)", 100, 600, 300, 50)
win = st.sidebar.slider("ช่วงคัดสูตร (งวด)", 30, 200, 100, 10)
K = st.sidebar.slider("คัดกี่สูตรเด่น (K)", 1, 15, 5)
N2 = st.sidebar.slider("ชุดเด่น 2 ตัว (กี่เลข)", 1, 10, 3)
N3 = st.sidebar.slider("ชุดเด่น 3 ตัว (กี่เลข)", 1, 15, 5)
st.sidebar.warning(
    "เพื่อการศึกษาสถิติเท่านั้น ผลย้อนหลังไม่รับประกันอนาคต"
    " ผลแต่ละงวดเป็นอิสระต่อกัน"
)

top, bot = run_analysis(data_key, n_test, win, K, N2, N3)
RES = {"top2": (top, 2), "top3": (top, 3), "bottom2": (bot, 2)}

# ----------------------------------------------------------------- แท็บแสดงผลหลัก
tabs = st.tabs([
    "🎯 เลขเด็ดงวดนี้",
    "📊 ตารางเทียบงวดต่องวด",
    "🧪 ผลวิเคราะห์สูตร",
    "📈 ติดตามผลจริง",
    "🔎 ความถี่เลข",
    "💰 แผนตามเลข",
    "ℹ️ วิธีอ่านผล",
])

# ----------------------------------------------------------------- 1. แท็บเลขเด็ดงวดนี้
with tabs[0]:
  st.subheader(f"🔮 วิเคราะห์ฟันธงสำหรับงวดวันที่: {top['next_date']}")

  col1, col2 = st.columns([1, 1])

  with col1:
    st.markdown("### 🏆 ชุดเด่นสถิติแม่นยำ (Walk-forward)")
    st.caption("คัดเลือกจากสูตรที่ทำผลงานสถิติดีที่สุดในอดีตย้อนหลัง")
    for key in ("top2", "bottom2", "top3"):
      res, kind = RES[key]
      c = res["champ"].get(kind) if res else None
      if c and c["numbers"]:
        st.info(
            f"**{KEY_LABEL[key]}:** `{' '.join(c['numbers'])}` "
            f" (เด่นสุด: **{c['numbers'][0]}** | ย้อนหลังเข้า"
            f" {c['hits']}/{c['tests']} งวด = {c['hit_pct']:.1f}%)"
        )

  with col2:
    st.markdown("### 🗳️ เลขมหาชน (Consensus Top Picks)")
    st.caption("เลขที่ถูกโหวตซ้ำกันมากที่สุดจากสูตรคำนวณทั้งหมด")
    cons = fe.consensus(top["next_picks"], top=6)
    if cons:
      c_cols = st.columns(3)
      for idx, (num, count) in enumerate(cons):
        c_cols[idx % 3].metric(
            label=f"อันดับ {idx+1}", value=num, delta=f"{count} สูตรตรงกัน"
        )

  st.divider()
  st.subheader("10 งวดล่าสุด")
  st.dataframe(
      raw.tail(10)
      .iloc[::-1]
      .rename(
          columns={
              "draw_date": "วันที่",
              "digit_6": "เลข 6 ตัว",
              "top3": "3 ตัวบน",
              "top2": "2 ตัวบน",
              "bottom2": "2 ตัวล่าง",
          }
      ),
      hide_index=True,
      use_container_width=True,
  )

# ----------------------------------------------------------------- 2. แท็บตารางเทียบงวดต่องวด
with tabs[1]:
  st.subheader("📊 ตารางเปรียบเทียบสูตรแบบงวดต่องวด")
  st.caption("ตรวจสอบว่าสูตรเด่นแต่ละสูตรทาย ถูก (✅) หรือ ผิด (❌) ในแต่ละงวด")

  f1, f2 = st.columns(2)
  target_grid = f1.selectbox(
      "เลือกประเภทรางวัล", ["2 ตัวบน", "2 ตัวล่าง", "3 ตัวบน"], key="grid_t"
  )
  n_draws_grid = f2.slider("จำนวนงวดที่ต้องการดู", 10, 50, 15, key="grid_n")

  res_grid, kind_grid = RES[TARGETS[target_grid]]
  if res_grid is not None:
    tbl_data = res_grid["tbl"]
    df_clean_grid = res_grid["df"].tail(n_draws_grid).reset_index(drop=True)
    act_numbers = (
        df_clean_grid["t2"].tolist()
        if kind_grid == 2
        else df_clean_grid["t3"].tolist()
    )
    dates = df_clean_grid["draw_date"].tolist()

    # คัดเลือก 20 สูตรแรกที่สถิติ p-value ดีที่สุด
    bt_top = res_grid["bt"][res_grid["bt"].kind == kind_grid].head(20)
    top_formulas = bt_top["name"].tolist()

    grid_rows = []
    for name in top_formulas:
      row = {"ชื่อสูตร / ลอจิก": name, "เข้ารวม (งวด)": 0}
      hits_count = 0

      for idx, date in enumerate(dates):
        global_idx = len(res_grid["df"]) - len(dates) + idx
        picks = tbl_data.get(name, {}).get(global_idx, [])
        actual = act_numbers[idx]

        if actual in picks:
          row[date] = "✅"
          hits_count += 1
        else:
          row[date] = "❌"

      row["เข้ารวม (งวด)"] = hits_count
      row["อัตราเข้า (%)"] = round((hits_count / len(dates)) * 100, 1)
      grid_rows.append(row)

    df_grid = pd.DataFrame(grid_rows).sort_values(
        "เข้ารวม (งวด)", ascending=False
    )
    col_order = (
        ["ชื่อสูตร / ลอจิก", "เข้ารวม (งวด)", "อัตราเข้า (%)"]
        + list(reversed(dates))
    )
    df_grid = df_grid[col_order]

    st.dataframe(
        df_grid, hide_index=True, use_container_width=True, height=450
    )

    if not df_grid.empty:
      best_f = df_grid.iloc[0]
      st.success(
          f"🏆 **สูตรที่แม่นที่สุดในช่วง {n_draws_grid} งวดนี้:**"
          f" `{best_f['ชื่อสูตร / ลอจิก']}` เข้าทั้งหมด **{best_f['เข้ารวม (งวด)']} /"
          f" {n_draws_grid} งวด** ({best_f['อัตราเข้า (%)']}%)"
      )

# ----------------------------------------------------------------- 3. แท็บผลวิเคราะห์สูตร
with tabs[2]:
  lab = st.radio("เลือกเป้าหมาย", list(TARGETS), horizontal=True, key="t2_rad")
  res, kind = RES[TARGETS[lab]]
  if res is not None:
    bt = res["bt"]
    bt = bt[bt.kind == kind].copy()
    m = len(bt)
    sig_raw = int((bt.p < 0.05).sum())
    sig_adj = int((bt.p_adj < 0.05).sum())

    c = st.columns(3)
    c[0].metric("จำนวนสูตรทั้งหมด", m)
    c[1].metric(
        "สูตรแม่นผิดปกติ (p<0.05)",
        sig_raw,
        help=f"คาดว่าเกิดจากดวงล้วน ≈ {0.05 * m:.1f}",
    )
    c[2].metric("ผ่านเกณฑ์แก้ไข Bonferroni", sig_adj)

    st.subheader("สรุปรายชุดลอจิก")
    gs = fe.group_summary(bt)
    st.dataframe(gs.round(2), hide_index=True, use_container_width=True)

    st.subheader("ตารางสถิติทุกสูตร")
    st.dataframe(
        bt[[
            "name",
            "picks",
            "hits",
            "tests",
            "hit_pct",
            "exp_pct",
            "max_miss",
            "p",
            "p_adj",
        ]].rename(
            columns={
                "name": "ชื่อสูตร",
                "picks": "จำนวนเลขที่ทาย",
                "hits": "ถูก (งวด)",
                "tests": "ทดสอบ (งวด)",
                "hit_pct": "ถูก %",
                "exp_pct": "คาดสุ่ม %",
                "max_miss": "พลาดติดสูงสุด",
            }
        ),
        hide_index=True,
        use_container_width=True,
        height=400,
    )

# ----------------------------------------------------------------- 4. แท็บติดตามผลจริง
with tabs[3]:
  st.caption("คำทายถูกบันทึกอัตโนมัติก่อนผลออก เพื่อติดตามความแม่นยำจริง")
  files = sorted(glob.glob(str(PRED_DIR / "*.json.gz")))
  if not files:
    st.info("ยังไม่มีไฟล์คำทายที่บันทึกไว้")
  else:
    d = raw.sort_values("draw_date")
    recs = []
    for fpath in files:
      with gzip.open(fpath, "rt", encoding="utf-8") as f:
        P = json.load(f)
      td = P["target_date"]
      lim = (pd.Timestamp(td) + pd.Timedelta(days=3)).strftime("%Y-%m-%d")
      m = d[(d.draw_date >= td) & (d.draw_date <= lim)]
      if m.empty:
        continue
      x = m.iloc[0]
      d6 = x.digit_6 if len(x.digit_6) == 6 else ""
      actual = {
          "top2": d6[-2:] or x.top2,
          "top3": d6[-3:] or x.top3,
          "bottom2": x.bottom2,
      }
      for tkey, T in P["targets"].items():
        kind = 3 if tkey == "top3" else 2
        items = dict(T.get("picks", {}))
        if T.get("champion") and T["champion"].get("numbers"):
          items[f"🏆 ชุดเด่น {KEY_LABEL[tkey]}"] = " ".join(
              T["champion"]["numbers"]
          )
        for name, pk in items.items():
          pl = pk.split()
          recs.append(dict(
              target=tkey,
              formula=name,
              hit=int(actual[tkey] in pl),
              exp=len(pl) / 10**kind,
          ))
    if recs:
      R = pd.DataFrame(recs)
      g = (
          R.groupby(["target", "formula"])
          .agg(ตรวจแล้ว=("hit", "count"), ถูก=("hit", "sum"), exp=("exp", "mean"))
          .reset_index()
      )
      g["ถูก %"] = (100 * g.ถูก / g.ตรวจแล้ว).round(2)
      g["คาดสุ่ม %"] = (100 * g.exp).round(2)
      g["เป้าหมาย"] = g.target.map(KEY_LABEL)
      st.dataframe(
          g[["เป้าหมาย", "formula", "ตรวจแล้ว", "ถูก", "ถูก %", "คาดสุ่ม %"]],
          hide_index=True,
          use_container_width=True,
      )

# ----------------------------------------------------------------- 5. แท็บความถี่เลข
with tabs[4]:
  st.subheader("สถิติความถี่ผลจริงย้อนหลัง")
  target_lab = st.radio(
      "วิเคราะห์ผลจริง",
      ["2 ตัวบน", "2 ตัวล่าง", "3 ตัวบน"],
      horizontal=True,
      key="freq_t",
  )
  target_col = {"2 ตัวบน": "t2", "2 ตัวล่าง": "b2", "3 ตัวบน": "t3"}[target_lab]
  freq_s = clean[target_col].astype(str)
  freq_s = freq_s[
      freq_s.str.fullmatch(r"\d{2}" if target_col != "t3" else r"\d{3}")
  ]
  window = st.slider("จำนวนงวดที่ใช้คำนวณ", 10, 300, 100, 10, key="freq_w")
  recent = freq_s.tail(window)
  counts = recent.value_counts()
  st.bar_chart(counts.head(20))

# ----------------------------------------------------------------- 6. แท็บแผนตามเลข
with tabs[5]:
  st.subheader("เครื่องมือคำนวณแผนตามเลข")
  st.caption(
      "คำนวณต้นทุน/กำไรในกรณีที่แทงทบหรือตามเลขเดิมต่อเนื่องหลายงวด"
  )
  c = st.columns(4)
  pay = c[0].number_input("อัตราจ่ายต่อ 1 บาท", 1.0, 1000.0, 90.0)
  npk = c[1].number_input("จำนวนเลขที่เล่นต่องวด", 1, 50, 3)
  R = c[2].number_input("จำนวนงวดที่ตาม (R)", 1, 10, 5)
  stake = c[3].number_input("เงินเริ่มต้นต่อเลข (บาท)", 1.0, 10000.0, 10.0)

  rows, sm = fe.plan_table(100, int(npk), pay, int(R), stake, mode="flat")
  st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

# ----------------------------------------------------------------- 7. แท็บวิธีอ่านผล
with tabs[6]:
  st.markdown("""
**หลักการทำงานของระบบ**
1. **Dynamic Walk-forward:** ระบบทำการทดสอบย้อนหลังทีละงวดโดยไม่แอบดูอนาคต แล้วคัดเอาสูตรที่เข้าดีที่สุด ณ ช่วงเวลานั้นๆ มาคำนวณเป็นเลขงวดหน้า
2. **Consensus Voting:** รวมผลการทายจากทุกสูตร แล้วจัดอันดับเลขที่ถูกโหวตซ้ำกันมากที่สุด
3. **P-Value Verification:** ใช้หลักสถิติคณิตศาสตร์เพื่อวัดว่าผลงานของสูตรดีกว่าการสุ่มล้วนๆ อย่างมีนัยสำคัญหรือไม่
""")