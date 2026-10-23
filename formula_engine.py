# -*- coding: utf-8 -*-
"""
formula_engine.py  -  เอนจิน 94 สูตร + Walk-forward Backtest + ทดสอบนัยสำคัญทางสถิติ
(ไม่ต้องใช้ scipy / ไม่ผูกกับ GUI เรียกจากที่ไหนก็ได้)

ใช้ร่วมกับ Loa_lottery_v02.py  หรือรันเดี่ยว:  python formula_engine.py lottery.csv
"""
import sys, math, random, re
from collections import Counter
import pandas as pd

# ---------------------------------------------------------------- ทำความสะอาดข้อมูล
YEAR_LIKE = r"00(?:20|25|26)\d\d"      # เลข 6 ตัวที่จริงๆ คือ "00"+ปี (บั๊กดึงปี พ.ศ. มาเป็นผลรางวัล)

def clean_draws(df):
    """รับ DataFrame (draw_date, digit_6, top3, top2) -> (df สะอาด, รายงาน dict)"""
    d = df.copy()
    for c in ("digit_6", "top3", "top2", "bottom2"):
        if c not in d: d[c] = ""
        d[c] = d[c].fillna("").astype(str).str.strip()
    d = d.drop_duplicates("draw_date", keep="last")
    rep = {"input": len(d)}
    ok6 = d.digit_6.str.fullmatch(r"\d{6}")
    vc = d.loc[ok6, "digit_6"].value_counts()
    bad6 = set(vc[vc >= 2].index)                      # เลข 6 ตัวเดียวกันออกหลายงวด = ข้อมูลเสีย
    m_dup = d.digit_6.isin(bad6)
    yr = pd.to_datetime(d.draw_date, errors="coerce").dt.year.fillna(0).astype(int)
    # "00"+ปีของงวดนั้นเอง (ค.ศ./พ.ศ.) = บั๊กดึงปีมาเป็นผลรางวัล (เลข 00xxxx ที่ไม่ตรงปีถือว่าเป็นผลจริง)
    m_year = pd.Series([bool(re.fullmatch(r"00(?:%d|%d)" % (y, y + 543), x)) for x, y in zip(d.digit_6, yr)], index=d.index)
    rep["dup6"] = int(m_dup.sum()); rep["year_like"] = int((m_year & ~m_dup).sum())
    d = d[~(m_dup | m_year)].copy()
    ok6 = d.digit_6.str.fullmatch(r"\d{6}")
    ok_top = d.top3.str.fullmatch(r"\d{3}") & d.top2.str.fullmatch(r"\d{2}") & (d.top3.str[-2:] == d.top2)
    keep = ok6 | ok_top
    rep["invalid"] = int((~keep).sum())
    d = d[keep].copy()
    d["t3"] = [x[-3:] if len(x) == 6 and x.isdigit() else t for x, t in zip(d.digit_6, d.top3)]
    d["t2"] = [x[-2:] if len(x) == 6 and x.isdigit() else t for x, t in zip(d.digit_6, d.top2)]
    d["b2"] = [x if (len(x) == 2 and x.isdigit()) else "" for x in d.bottom2]
    d = d.sort_values("draw_date").reset_index(drop=True)
    d["dow"] = pd.to_datetime(d.draw_date).dt.dayofweek
    rep["clean"] = len(d)
    return d, rep

def legacy_csv_to_df(path):
    """อ่าน CSV รูปแบบเก่าที่ส่งออกจากแอพ (prize6/top3/top2) -> DataFrame มาตรฐาน"""
    x = pd.read_csv(path, dtype=str)
    if "country" in x: x = x[x.country == "LA"]
    if "prize6" in x: x = x.rename(columns={"prize6": "digit_6"})
    return x[[c for c in ("draw_date", "digit_6", "top3", "top2", "bottom2") if c in x]]

GROUP_NAMES = {
    "A": "A ความถี่ร้อน/เย็น/ค้างนาน", "B": "B ซ้ำย้อนหลัง (Lag)", "C": "C บวก-ลบ-คูณ-เฉลี่ย",
    "D": "D แตกเลข 3 ตัวเป็น 2 ตัว", "E": "E ระดับหลัก (สิบ/หน่วย)", "F": "F Markov/ตามลำดับ",
    "G": "G ตามวันออกรางวัล", "H": "H ตระกูลเลข (หัว/หาง/คู่คี่/สูงต่ำ)", "I": "I โหวตรวมทุกสูตร",
    "J": "J สูตรจากภาพ (บวกเลข/เด่น/ดับ/ฟีโบ)", "K": "K 3 ตัวบน", "L": "L เลขวิ่ง",
    "M": "M เลขถึงรอบ", "N": "N เบิ้ล/เรียง/กลับ", "O": "O 3 ตัวบนขั้นสูง", "P": "P ผลรวมตำแหน่ง 6 ตัว",
    "Z": "Z ตัวควบคุม (สุ่มล้วน)"}
def group_of(name): return GROUP_NAMES.get(name[:1], "อื่นๆ")

two = lambda x: f"{x % 100:02d}"
rev = lambda s: s[::-1]

# ---------------------------------------------------------------- สูตร
# แต่ละสูตร: f(H2, H3, dows, next_dow) -> list ของเลข 2 ตัวที่ทาย (H2/H3 = ประวัติ 2 ตัว/3 ตัว เก่า->ใหม่)
F = []
def reg(name, fn): F.append((name, fn))

def topk_counter(c, k, rev_=True):
    items = sorted(c.items(), key=lambda kv: (kv[1], kv[0]), reverse=rev_)
    return [n for n, _ in items[:k]]

# --- กลุ่ม A: ความถี่ (Hot) / เลขค้างนาน (Cold) --------------------------------
for w in (30, 60, 100, 200, 400, 0):
    for k in (1, 5, 10):
        lab = "ทั้งหมด" if w == 0 else f"{w}งวด"
        reg(f"A-Hot{k} [{lab}]",
            lambda H2, H3, D, nd, w=w, k=k: topk_counter(Counter(H2[-w:] if w else H2), k))
for k in (1, 5, 10):
    def cold(H2, H3, D, nd, k=k):
        last = {n: i for i, n in enumerate(H2)}
        allc = [f"{i:02d}" for i in range(100)]
        return sorted(allc, key=lambda n: last.get(n, -1))[:k]
    reg(f"A-Overdue{k} (ค้างนานสุด)", cold)
for k in (5, 10):
    reg(f"A-Cold{k} [100งวด]",
        lambda H2, H3, D, nd, k=k: [n for n, _ in sorted(Counter({f'{i:02d}': 0 for i in range(100)} | Counter(H2[-100:])).items(), key=lambda kv: kv[1])[:k]])

# --- กลุ่ม B: ซ้ำย้อนหลัง (Lag) ------------------------------------------------
for L in range(1, 8):
    reg(f"B-Lag{L} (เลขเดิมเมื่อ {L} งวดก่อน)", lambda H2, H3, D, nd, L=L: [H2[-L]] if len(H2) >= L else [])
for L in (1, 2, 3):
    reg(f"B-กลับเลข Lag{L}", lambda H2, H3, D, nd, L=L: [rev(H2[-L])])
for L in (1, 2):
    reg(f"B-99-เลข Lag{L} (เลขคู่เสริม)", lambda H2, H3, D, nd, L=L: [two(99 - int(H2[-L]))])

# --- กลุ่ม C: บวก/ลบ/คูณ งวดก่อน ------------------------------------------------
reg("C-บวก 2 งวดก่อน", lambda H2, H3, D, nd: [two(int(H2[-1]) + int(H2[-2]))])
reg("C-ลบ 2 งวดก่อน", lambda H2, H3, D, nd: [two(int(H2[-1]) - int(H2[-2]))])
reg("C-ลบสลับ", lambda H2, H3, D, nd: [two(int(H2[-2]) - int(H2[-1]))])
reg("C-คูณ 2 งวดก่อน", lambda H2, H3, D, nd: [two(int(H2[-1]) * int(H2[-2]))])
reg("C-บวก 3 งวดก่อน", lambda H2, H3, D, nd: [two(sum(int(x) for x in H2[-3:]))])
reg("C-เฉลี่ย 3 งวด", lambda H2, H3, D, nd: [two(round(sum(int(x) for x in H2[-3:]) / 3))])
reg("C-เฉลี่ย 7 งวด", lambda H2, H3, D, nd: [two(round(sum(int(x) for x in H2[-7:]) / 7))])
reg("C-เฉลี่ย 30 งวด", lambda H2, H3, D, nd: [two(round(sum(int(x) for x in H2[-30:]) / 30))])
reg("C-บวกคงที่ +1", lambda H2, H3, D, nd: [two(int(H2[-1]) + 1)])
reg("C-ลบคงที่ -1", lambda H2, H3, D, nd: [two(int(H2[-1]) - 1)])
reg("C-+7", lambda H2, H3, D, nd: [two(int(H2[-1]) + 7)])
reg("C-+50", lambda H2, H3, D, nd: [two(int(H2[-1]) + 50)])
reg("C-ผลต่างเฉลี่ยเดินต่อ", lambda H2, H3, D, nd: [two(int(H2[-1]) + (int(H2[-1]) - int(H2[-2])))])
reg("C-เลขเดิม ±1 (3 ตัว)", lambda H2, H3, D, nd: [two(int(H2[-1]) + d) for d in (-1, 0, 1)])
reg("C-เลขเดิม ±2 (5 ตัว)", lambda H2, H3, D, nd: [two(int(H2[-1]) + d) for d in (-2, -1, 0, 1, 2)])

# --- กลุ่ม D: เลข 3 ตัว -> 2 ตัว -------------------------------------------------
reg("D-2 ตัวหน้าของ 3 ตัวงวดก่อน", lambda H2, H3, D, nd: [H3[-1][:2]])
reg("D-หลักร้อย+หน่วย", lambda H2, H3, D, nd: [H3[-1][0] + H3[-1][2]])
reg("D-หลักสิบ+ร้อย (กลับ)", lambda H2, H3, D, nd: [H3[-1][1] + H3[-1][0]])
reg("D-ผลบวกหลัก 3 ตัว (หน่วยสองหลัก)", lambda H2, H3, D, nd: [two(sum(map(int, H3[-1])))])
reg("D-ผลบวกหลัก+หน่วย", lambda H2, H3, D, nd: [f"{sum(map(int, H3[-1])) % 10}{H3[-1][2]}"])
reg("D-3ตัวงวดก่อน mod 100", lambda H2, H3, D, nd: [two(int(H3[-1]))])
reg("D-3ตัว 2 งวดก่อน -> หน้า2", lambda H2, H3, D, nd: [H3[-2][:2]])
reg("D-ร้อยงวดก่อน+ร้อย 2 งวดก่อน", lambda H2, H3, D, nd: [H3[-1][0] + H3[-2][0]])
reg("D-ผลคูณหลัก 3 ตัว", lambda H2, H3, D, nd: [two(math.prod(map(int, H3[-1])))])

# --- กลุ่ม E: ระดับหลัก (Digit) ------------------------------------------------
def digit_hot(H2, w, pos):
    return Counter(x[pos] for x in H2[-w:]).most_common(1)[0][0]
for w in (30, 100, 300):
    reg(f"E-หลักสิบ×หลักหน่วย ที่ออกบ่อย [{w}งวด]",
        lambda H2, H3, D, nd, w=w: [digit_hot(H2, w, 0) + digit_hot(H2, w, 1)])
    reg(f"E-หลักสิบ-หน่วยเย็นสุด [{w}งวด]",
        lambda H2, H3, D, nd, w=w: [Counter({str(i): 0 for i in range(10)} | Counter(x[0] for x in H2[-w:])).most_common()[-1][0] +
                                    Counter({str(i): 0 for i in range(10)} | Counter(x[1] for x in H2[-w:])).most_common()[-1][0]])
reg("E-สลับหลักงวดก่อน", lambda H2, H3, D, nd: [H2[-1][1] + H2[-1][0]])
reg("E-หลักสิบงวดก่อน+หน่วย 2 งวดก่อน", lambda H2, H3, D, nd: [H2[-1][0] + H2[-2][1]])
reg("E-หน่วยงวดก่อน+สิบ 2 งวดก่อน", lambda H2, H3, D, nd: [H2[-1][1] + H2[-2][0]])
reg("E-สิบ(+1) หน่วย(+1)", lambda H2, H3, D, nd: [str((int(H2[-1][0]) + 1) % 10) + str((int(H2[-1][1]) + 1) % 10)])
reg("E-สิบ(-1) หน่วย(-1)", lambda H2, H3, D, nd: [str((int(H2[-1][0]) - 1) % 10) + str((int(H2[-1][1]) - 1) % 10)])
reg("E-ผลบวกหลักงวดก่อน (หน่วย) คู่กับหน่วยเดิม", lambda H2, H3, D, nd: [str((int(H2[-1][0]) + int(H2[-1][1])) % 10) + H2[-1][1]])
reg("E-เลขคู่ซ้ำ (00,11,..,99) ที่ค้างนาน", lambda H2, H3, D, nd: [min([f"{i}{i}" for i in range(10)], key=lambda n: max([j for j, x in enumerate(H2) if x == n] or [-1]))])

# --- กลุ่ม F: Markov / ความสัมพันธ์ตามลำดับ --------------------------------------
def markov_next(H2, order=1, k=1):
    key = tuple(H2[-order:])
    nxt = Counter()
    for i in range(order, len(H2)):
        if tuple(H2[i - order:i]) == key:
            nxt[H2[i]] += 1
    return topk_counter(nxt, k) if nxt else []
for k in (1, 5):
    reg(f"F-Markov เลขต่อเลข order1 top{k}", lambda H2, H3, D, nd, k=k: markov_next(H2, 1, k))
reg("F-Markov order2 top1", lambda H2, H3, D, nd: markov_next(H2, 2, 1))
def digit_markov(H2):
    t0 = Counter(); t1 = Counter()
    for i in range(1, len(H2)):
        if H2[i - 1][0] == H2[-1][0]: t0[H2[i][0]] += 1
        if H2[i - 1][1] == H2[-1][1]: t1[H2[i][1]] += 1
    return [(t0.most_common(1)[0][0] if t0 else "0") + (t1.most_common(1)[0][0] if t1 else "0")]
reg("F-Markov รายหลัก", lambda H2, H3, D, nd: digit_markov(H2))
def follow_of_last(H2, k):
    last = H2[-1]; c = Counter()
    for i in range(len(H2) - 1):
        if H2[i] == last: c[H2[i + 1]] += 1
    return topk_counter(c, k) if c else []
reg("F-เลขที่เคยตามหลังเลขล่าสุด", lambda H2, H3, D, nd: follow_of_last(H2, 3))
def after_same_digit_sum(H2):
    s = (int(H2[-1][0]) + int(H2[-1][1])) % 10; c = Counter()
    for i in range(len(H2) - 1):
        if (int(H2[i][0]) + int(H2[i][1])) % 10 == s: c[H2[i + 1]] += 1
    return topk_counter(c, 3)
reg("F-ตามผลบวกหลักเดียวกัน", lambda H2, H3, D, nd: after_same_digit_sum(H2))

# --- กลุ่ม G: วันออกรางวัล (Day-of-week) ------------------------------------------
def dow_hot(H2, D, nd, k, w=0):
    pairs = [(h, d) for h, d in zip(H2[-w:] if w else H2, D[-w:] if w else D) if d == nd]
    return topk_counter(Counter(h for h, _ in pairs), k) if pairs else []
for k in (1, 5):
    reg(f"G-Hot ตามวันออก top{k}", lambda H2, H3, D, nd, k=k: dow_hot(H2, D, nd, k))
    reg(f"G-Hot ตามวันออก 200งวด top{k}", lambda H2, H3, D, nd, k=k: dow_hot(H2, D, nd, k, 200))

# --- กลุ่ม H: ตระกูลเลข (คู่/คี่, สูง/ต่ำ, ผลรวม) ---------------------------------
def parity_pick(H2, w):
    c = Counter((int(x[0]) % 2, int(x[1]) % 2) for x in H2[-w:])
    p = c.most_common(1)[0][0]
    cands = [f"{i:02d}" for i in range(100) if (int(f"{i:02d}"[0]) % 2, int(f"{i:02d}"[1]) % 2) == p]
    return cands
reg("H-กลุ่ม คู่/คี่ ที่ออกบ่อย (25 ตัว)", lambda H2, H3, D, nd: parity_pick(H2, 50))
def sum_family(H2, w):
    c = Counter((int(x[0]) + int(x[1])) % 10 for x in H2[-w:]); s = c.most_common(1)[0][0]
    return [f"{i:02d}" for i in range(100) if (int(f"{i:02d}"[0]) + int(f"{i:02d}"[1])) % 10 == s]
reg("H-ตระกูลผลบวกหลักที่ออกบ่อย (10 ตัว)", lambda H2, H3, D, nd: sum_family(H2, 100))
reg("H-หัว (หลักสิบ) ที่ออกบ่อย 20งวด (10 ตัว)", lambda H2, H3, D, nd: [f"{Counter(x[0] for x in H2[-20:]).most_common(1)[0][0]}{j}" for j in range(10)])
reg("H-หาง (หน่วย) ที่ออกบ่อย 20งวด (10 ตัว)", lambda H2, H3, D, nd: [f"{j}{Counter(x[1] for x in H2[-20:]).most_common(1)[0][0]}" for j in range(10)])
reg("H-หัวเดียวกับงวดก่อน (10 ตัว)", lambda H2, H3, D, nd: [f"{H2[-1][0]}{j}" for j in range(10)])
reg("H-หางเดียวกับงวดก่อน (10 ตัว)", lambda H2, H3, D, nd: [f"{j}{H2[-1][1]}" for j in range(10)])


# --- ตัวช่วยสำหรับสูตรที่ใช้เลขรางวัล 6 ตัว --------------------------------------
from itertools import permutations
_H6 = []
def set_history(df):
    """ต้องเรียกก่อนคำนวณสูตร: เก็บเลข 6 ตัวของทุกงวดให้ตรงลำดับกับ H2/H3"""
    global _H6
    _H6 = [x if (len(x) == 6 and x.isdigit()) else "" for x in df.digit_6.astype(str)]
def _last6(H2, back=1):
    h = _H6[:len(H2)]
    return h[-back] if len(h) >= back else ""
uniq = lambda seq: list(dict.fromkeys(seq))
def _pairs(digs, doubles=True):
    return uniq([a + b for a in digs for b in digs if doubles or a != b])
def _perms(s, k=3):
    return uniq(["".join(p) for p in permutations(s, k)])
def _freq_digits(s):
    c = Counter(s); first = {d: i for i, d in enumerate(s)}
    return sorted(c, key=lambda d: (-c[d], first[d]))
def J(name):
    def deco(fn):
        reg(name, fn); return fn
    return deco

# --- กลุ่ม J: สูตรจากภาพ (บวกเลข / เลขเด่น / เลขดับ / ฟีโบนักชี / คู่-คี่ / บน-ล่าง) ----
@J("J01-บวกเลข 6 ตัว -> เลขวิ่ง (19 ตัว)")
def _(H2, H3, D, nd):
    s = _last6(H2)
    if not s: return []
    d = str(sum(map(int, s)) % 10)
    return uniq([d + str(j) for j in range(10)] + [str(j) + d for j in range(10)])

@J("J02-บวกเลข จับคู่กับหลักท้ายผล (4 ตัว)")
def _(H2, H3, D, nd):
    s = _last6(H2)
    if not s: return []
    d = str(sum(map(int, s)) % 10)
    return uniq([d + s[-1], s[-1] + d, d + s[-2], s[-2] + d])

@J("J03-เลขเด่นตามภาพ: คู่ติดกัน (ไม่ซ้ำ+ผลบวก)")
def _(H2, H3, D, nd):
    s = _last6(H2)
    if not s: return []
    seq = uniq(s) + [str(sum(map(int, s)) % 10)]
    return uniq([seq[i] + seq[i + 1] for i in range(len(seq) - 1)])

@J("J04-เลขเด่นตามภาพ: สามติดกัน (3 ตัว)")
def _(H2, H3, D, nd):
    s = _last6(H2)
    if not s: return []
    seq = uniq(s) + [str(sum(map(int, s)) % 10)]
    return uniq([seq[i] + seq[i + 1] + seq[i + 2] for i in range(1, len(seq) - 2)])

@J("J05-เลขซ้ำมากสุด 3 ตัว: คู่ไม่เบิ้ล (6)")
def _(H2, H3, D, nd):
    s = _last6(H2)
    return _pairs(_freq_digits(s)[:3], False) if s else []

@J("J06-เลขซ้ำมากสุด 3 ตัว: คู่รวมเบิ้ล (9)")
def _(H2, H3, D, nd):
    s = _last6(H2)
    return _pairs(_freq_digits(s)[:3], True) if s else []

@J("J07-เลขซ้ำมากสุด 3 ตัว: สลับชุด 3 ตัว")
def _(H2, H3, D, nd):
    s = _last6(H2)
    f = _freq_digits(s)[:3] if s else []
    return _perms("".join(f), 3) if len(f) == 3 else []

@J("J08-เลขดับ (ไม่ออก) 3 ตัวแรก: คู่รวมเบิ้ล (9)")
def _(H2, H3, D, nd):
    s = _last6(H2)
    if not s: return []
    absent = [str(i) for i in range(10) if str(i) not in s][:3]
    return _pairs(absent, True) if len(absent) >= 2 else []

@J("J09-ฟีโบนักชี {1,2,3,5,8} คงที่ (25 ตัว)")
def _(H2, H3, D, nd):
    return _pairs(list("12358"), True)

@J("J10-ฟีโบนักชีต่อเนื่องจาก 2 ตัวบนงวดก่อน (1 ตัว)")
def _(H2, H3, D, nd):
    a, b = int(H2[-1][0]), int(H2[-1][1])
    x = (a + b) % 10; y = (b + x) % 10
    return [f"{x}{y}"]

@J("J11-ฟีโบนักชีต่อเนื่องจาก 2 งวด (2 ตัว)")
def _(H2, H3, D, nd):
    q = [int(c) for c in H2[-2] + H2[-1]]
    x1 = (q[-2] + q[-1]) % 10; x2 = (q[-1] + x1) % 10; x3 = (x1 + x2) % 10; x4 = (x2 + x3) % 10
    return [f"{x1}{x2}", f"{x3}{x4}"]

def _parity_pick(n2, flip):
    p = [(int(n2[0]) % 2) ^ flip, (int(n2[1]) % 2) ^ flip]
    return [f"{i:02d}" for i in range(100) if (int(f"{i:02d}"[0]) % 2, int(f"{i:02d}"[1]) % 2) == tuple(p)]
@J("J12-คู่-คี่: รูปแบบเดียวกับงวดก่อน (25 ตัว)")
def _(H2, H3, D, nd): return _parity_pick(H2[-1], 0)
@J("J13-คู่-คี่: รูปแบบกลับด้านงวดก่อน (25 ตัว)")
def _(H2, H3, D, nd): return _parity_pick(H2[-1], 1)

@J("J14-เลขบน (3 ตัวหน้าของผล) จับคู่")
def _(H2, H3, D, nd):
    s = _last6(H2)
    return _pairs(uniq(s[:3]), True) if s else []
@J("J15-เลขล่าง (3 ตัวท้ายของผล) จับคู่")
def _(H2, H3, D, nd):
    s = _last6(H2)
    return _pairs(uniq(s[-3:]), True) if s else []
@J("J16-เลขบน×เลขล่าง ไขว้ (สองทิศ)")
def _(H2, H3, D, nd):
    s = _last6(H2)
    if not s: return []
    a, b = uniq(s[:3]), uniq(s[-3:])
    return uniq([x + y for x in a for y in b] + [y + x for x in a for y in b])

for _back in (1, 2):
    for _k in range(4):
        reg(f"J{17 + _k + 4 * (_back - 1)}-หยิบ 2 ตัวจากผล 6 ตัว ตำแหน่ง {_k + 1}-{_k + 2} ({_back} งวดก่อน)",
            lambda H2, H3, D, nd, _back=_back, _k=_k: ([_last6(H2, _back)[_k:_k + 2]] if _last6(H2, _back) else []))

@J("J25-ผลบวกคู่หลัก (หลัก1+2 , หลัก3+4)")
def _(H2, H3, D, nd):
    s = _last6(H2)
    return [f"{(int(s[0]) + int(s[1])) % 10}{(int(s[2]) + int(s[3])) % 10}"] if s else []
@J("J26-ผลบวกคู่หลัก (หลัก3+4 , หลัก5+6)")
def _(H2, H3, D, nd):
    s = _last6(H2)
    return [f"{(int(s[2]) + int(s[3])) % 10}{(int(s[4]) + int(s[5])) % 10}"] if s else []
@J("J27-ผลบวกคู่หลัก (หลัก2+3 , หลัก4+5)")
def _(H2, H3, D, nd):
    s = _last6(H2)
    return [f"{(int(s[1]) + int(s[2])) % 10}{(int(s[3]) + int(s[4])) % 10}"] if s else []

@J("J28-เลขกระจก 2 ตัวบนงวดก่อน (+5 ทุกหลัก)")
def _(H2, H3, D, nd): return [f"{(int(H2[-1][0]) + 5) % 10}{(int(H2[-1][1]) + 5) % 10}"]
@J("J29-เลขกระจก+กลับ")
def _(H2, H3, D, nd): return [f"{(int(H2[-1][1]) + 5) % 10}{(int(H2[-1][0]) + 5) % 10}"]
@J("J30-กระจกของผลบวก 6 ตัว (2 ตัว)")
def _(H2, H3, D, nd):
    s = _last6(H2)
    if not s: return []
    d = sum(map(int, s)) % 10
    return uniq([f"{(d + 5) % 10}{d}", f"{d}{(d + 5) % 10}"])

# --- กลุ่ม K: ทาย 3 ตัวบน ------------------------------------------------------
@J("K01-3 ตัวบน: เลขเดิมงวดก่อน")
def _(H2, H3, D, nd): return [H3[-1]]
@J("K02-3 ตัวบน: เลขเดิม 2 งวดก่อน")
def _(H2, H3, D, nd): return [H3[-2]]
@J("K03-3 ตัวบน: สลับเลขงวดก่อน (≤6 ตัว)")
def _(H2, H3, D, nd): return _perms(H3[-1], 3)
@J("K04-3 ตัวบน: 3 ตัวหน้าของผล 6 ตัวงวดก่อน")
def _(H2, H3, D, nd):
    s = _last6(H2); return [s[:3]] if s else []
@J("K05-3 ตัวบน: สลับ 3 ตัวหน้าของผลงวดก่อน (≤6 ตัว)")
def _(H2, H3, D, nd):
    s = _last6(H2); return _perms(s[:3], 3) if s else []
@J("K06-3 ตัวบน: กลับเลขงวดก่อน")
def _(H2, H3, D, nd): return [H3[-1][::-1]]
@J("K07-3 ตัวบน: ผลบวก 2 งวด mod 1000")
def _(H2, H3, D, nd): return [f"{(int(H3[-1]) + int(H3[-2])) % 1000:03d}"]
@J("K08-3 ตัวบน: ออกบ่อยสุด 10 ตัว [200งวด]")
def _(H2, H3, D, nd): return topk_counter(Counter(H3[-200:]), 10)
@J("K09-3 ตัวบน: ออกบ่อยสุด 20 ตัว [ทั้งหมด]")
def _(H2, H3, D, nd): return topk_counter(Counter(H3), 20)
@J("K10-3 ตัวบน: หน้า2 ของงวดก่อน + หน่วยของ 2 งวดก่อน")
def _(H2, H3, D, nd): return [H3[-1][:2] + H3[-2][2]]


# =====================================================================================
#  ชุดขยาย  (A+ B+ C+ D+ E+ F+ G+ H+ L M N O P)  — รวมแล้วหลายร้อยสูตร
# =====================================================================================
iv = lambda H2, k: int(H2[-k])
def _cold(H2, w, k):
    c = Counter({f"{i:02d}": 0 for i in range(100)}) | Counter(H2[-w:])
    return [n for n, _ in sorted(c.items(), key=lambda kv: (kv[1], kv[0]))[:k]]

# --- A+: ความถี่หลายหน้าต่าง
for _w in (10, 20, 50, 150, 300):
    for _k in (1, 5, 10):
        reg(f"A-Hot{_k} [{_w}งวด]", lambda H2, H3, D, nd, _w=_w, _k=_k: topk_counter(Counter(H2[-_w:]), _k))
for _w in (50, 100, 200):
    reg(f"A-Hot20 [{_w}งวด]", lambda H2, H3, D, nd, _w=_w: topk_counter(Counter(H2[-_w:]), 20))
for _w in (30, 60, 200):
    reg(f"A-Cold10 [{_w}งวด]", lambda H2, H3, D, nd, _w=_w: _cold(H2, _w, 10))

# --- B+: ซ้ำย้อนหลังไกลขึ้น
for _L in range(8, 16):
    reg(f"B-Lag{_L} (เลขเดิมเมื่อ {_L} งวดก่อน)", lambda H2, H3, D, nd, _L=_L: [H2[-_L]])
for _L in (4, 5, 6):
    reg(f"B-กลับเลข Lag{_L}", lambda H2, H3, D, nd, _L=_L: [rev(H2[-_L])])

# --- C+: คำนวณจากหลายงวด
reg("C-ล่าสุด + 3 งวดก่อน", lambda H2, H3, D, nd: [two(iv(H2, 1) + iv(H2, 3))])
reg("C-ล่าสุด - 3 งวดก่อน", lambda H2, H3, D, nd: [two(iv(H2, 1) - iv(H2, 3))])
reg("C-2 งวดก่อน + 3 งวดก่อน", lambda H2, H3, D, nd: [two(iv(H2, 2) + iv(H2, 3))])
reg("C-ล่าสุด × 3 งวดก่อน", lambda H2, H3, D, nd: [two(iv(H2, 1) * iv(H2, 3))])
reg("C-2×ล่าสุด + งวดก่อนหน้า", lambda H2, H3, D, nd: [two(2 * iv(H2, 1) + iv(H2, 2))])
reg("C-ล่าสุด + 2×งวดก่อนหน้า", lambda H2, H3, D, nd: [two(iv(H2, 1) + 2 * iv(H2, 2))])
reg("C-|ต่าง| 2 งวดล่าสุด", lambda H2, H3, D, nd: [two(abs(iv(H2, 1) - iv(H2, 2)))])
reg("C-บวก 4 งวดล่าสุด", lambda H2, H3, D, nd: [two(sum(int(x) for x in H2[-4:]))])
reg("C-บวก 5 งวดล่าสุด", lambda H2, H3, D, nd: [two(sum(int(x) for x in H2[-5:]))])
reg("C-เฉลี่ย 5 งวด", lambda H2, H3, D, nd: [two(round(sum(int(x) for x in H2[-5:]) / 5))])
reg("C-เฉลี่ย 10 งวด", lambda H2, H3, D, nd: [two(round(sum(int(x) for x in H2[-10:]) / 10))])
reg("C-มัธยฐาน 7 งวด", lambda H2, H3, D, nd: [two(sorted(int(x) for x in H2[-7:])[3])])
reg("C-ฐานนิยม 20 งวด", lambda H2, H3, D, nd: [Counter(H2[-20:]).most_common(1)[0][0]])
reg("C-สลับบวกลบ 4 งวด (a-b+c-d)", lambda H2, H3, D, nd: [two(iv(H2, 1) - iv(H2, 2) + iv(H2, 3) - iv(H2, 4))])
reg("C-บวกทีละหลัก 2 งวด (ไม่ทด)", lambda H2, H3, D, nd: [f"{(int(H2[-1][0]) + int(H2[-2][0])) % 10}{(int(H2[-1][1]) + int(H2[-2][1])) % 10}"])
reg("C-ลบทีละหลัก 2 งวด (ไม่ยืม)", lambda H2, H3, D, nd: [f"{(int(H2[-1][0]) - int(H2[-2][0])) % 10}{(int(H2[-1][1]) - int(H2[-2][1])) % 10}"])
reg("C-คูณทีละหลัก 2 งวด", lambda H2, H3, D, nd: [f"{(int(H2[-1][0]) * int(H2[-2][0])) % 10}{(int(H2[-1][1]) * int(H2[-2][1])) % 10}"])

# --- D+: แตกเลข 3 ตัว
reg("D-ต่างสัมบูรณ์หลักติดกัน (ร้อย-สิบ , สิบ-หน่วย)", lambda H2, H3, D, nd: [f"{abs(int(H3[-1][0]) - int(H3[-1][1]))}{abs(int(H3[-1][1]) - int(H3[-1][2]))}"])
reg("D-ผลบวกหลักติดกัน (ร้อย+สิบ , สิบ+หน่วย)", lambda H2, H3, D, nd: [f"{(int(H3[-1][0]) + int(H3[-1][1])) % 10}{(int(H3[-1][1]) + int(H3[-1][2])) % 10}"])
reg("D-เรียงน้อย→มาก 2 ตัวแรก", lambda H2, H3, D, nd: ["".join(sorted(H3[-1]))[:2]])
reg("D-เรียงมาก→น้อย 2 ตัวแรก", lambda H2, H3, D, nd: ["".join(sorted(H3[-1], reverse=True))[:2]])
reg("D-ร้อย+หน่วย ของ 3 ตัว 2 งวดก่อน", lambda H2, H3, D, nd: [H3[-2][0] + H3[-2][2]])
reg("D-ร้อยงวดก่อนหน้า + หน่วยงวดล่าสุด", lambda H2, H3, D, nd: [H3[-2][0] + H3[-1][2]])
reg("D-ทุกการสลับของ 3 ตัวงวดก่อน หยิบ 2 ตัวหน้า", lambda H2, H3, D, nd: uniq([p[:2] for p in _perms(H3[-1], 3)]))

# --- E+: ระดับหลัก
for _a in (1, 2, 3):
    for _b in (1, 2, 3):
        if (_a, _b) == (1, 1): continue
        reg(f"E-หลักสิบจาก {_a} งวดก่อน + หน่วยจาก {_b} งวดก่อน", lambda H2, H3, D, nd, _a=_a, _b=_b: [H2[-_a][0] + H2[-_b][1]])
for _w in (10, 20, 50):
    reg(f"E-หลักสิบ×หลักหน่วย ที่ออกบ่อย [{_w}งวด]", lambda H2, H3, D, nd, _w=_w: [digit_hot(H2, _w, 0) + digit_hot(H2, _w, 1)])

# --- F+: Markov เพิ่ม
for _w in (200, 500):
    reg(f"F-Markov order1 top3 [{_w}งวด]", lambda H2, H3, D, nd, _w=_w: markov_next(H2[-_w:], 1, 3))
reg("F-Markov order3 top1", lambda H2, H3, D, nd: markov_next(H2, 3, 1))
reg("F-Markov รายหลัก [200งวด]", lambda H2, H3, D, nd: digit_markov(H2[-200:]))
def _follow_by(H2, pos, k):
    c = Counter(H2[i + 1] for i in range(len(H2) - 1) if H2[i][pos] == H2[-1][pos])
    return topk_counter(c, k) if c else []
reg("F-เลขที่มักตามหลังเลขหัวเดียวกัน top3", lambda H2, H3, D, nd: _follow_by(H2, 0, 3))
reg("F-เลขที่มักตามหลังเลขหางเดียวกัน top3", lambda H2, H3, D, nd: _follow_by(H2, 1, 3))

# --- G+: วันออก
def _same_dow(H2, D, nd, m):
    return [h for h, d in zip(H2, D) if d == nd][-m:]
reg("G-เลขที่ออกวันเดียวกันครั้งก่อน (1 ตัว)", lambda H2, H3, D, nd: _same_dow(H2, D, nd, 1))
reg("G-เลขที่ออกวันเดียวกัน 2 ครั้งก่อน", lambda H2, H3, D, nd: _same_dow(H2, D, nd, 2))
reg("G-เลขที่ออกวันเดียวกัน 3 ครั้งก่อน", lambda H2, H3, D, nd: _same_dow(H2, D, nd, 3))
for _w in (50, 100):
    reg(f"G-Hot ตามวันออก [{_w}งวด] top5", lambda H2, H3, D, nd, _w=_w: dow_hot(H2, D, nd, 5, _w))
def _dow_digits(H2, D, nd):
    xs = [h for h, d in zip(H2, D) if d == nd]
    if len(xs) < 5: return []
    return [Counter(x[0] for x in xs).most_common(1)[0][0] + Counter(x[1] for x in xs).most_common(1)[0][0]]
reg("G-หลักสิบ×หน่วยฮอตตามวันออก", lambda H2, H3, D, nd: _dow_digits(H2, D, nd))

# --- H+: ตระกูลเลข
def _half(x): return int(x) >= 50
reg("H-ครึ่งเดียวกับงวดก่อน (สูง/ต่ำ 50 ตัว)", lambda H2, H3, D, nd: [f"{i:02d}" for i in range(100) if _half(f"{i:02d}") == _half(H2[-1])])
reg("H-ครึ่งตรงข้ามงวดก่อน (50 ตัว)", lambda H2, H3, D, nd: [f"{i:02d}" for i in range(100) if _half(f"{i:02d}") != _half(H2[-1])])
for _w in (10, 50):
    reg(f"H-หัวร้อน [{_w}งวด] (10 ตัว)", lambda H2, H3, D, nd, _w=_w: [f"{Counter(x[0] for x in H2[-_w:]).most_common(1)[0][0]}{j}" for j in range(10)])
    reg(f"H-หางร้อน [{_w}งวด] (10 ตัว)", lambda H2, H3, D, nd, _w=_w: [f"{j}{Counter(x[1] for x in H2[-_w:]).most_common(1)[0][0]}" for j in range(10)])
reg("H-หัวร้อน×หางร้อน 2 อันดับ [100งวด] (4 ตัว)", lambda H2, H3, D, nd: [a + b for a in [d for d, _ in Counter(x[0] for x in H2[-100:]).most_common(2)] for b in [d for d, _ in Counter(x[1] for x in H2[-100:]).most_common(2)]])
reg("H-ผลบวกหลักเดียวกับงวดก่อน (10 ตัว)", lambda H2, H3, D, nd: [f"{i:02d}" for i in range(100) if (int(f'{i:02d}'[0]) + int(f'{i:02d}'[1])) % 10 == (int(H2[-1][0]) + int(H2[-1][1])) % 10])
reg("H-ผลบวกหลักตรงข้าม +5 (10 ตัว)", lambda H2, H3, D, nd: [f"{i:02d}" for i in range(100) if (int(f'{i:02d}'[0]) + int(f'{i:02d}'[1])) % 10 == (int(H2[-1][0]) + int(H2[-1][1]) + 5) % 10])

# --- L: เลขวิ่ง (ตัวเลขนี้อยู่หลักไหนก็ได้ = 19 ตัว)
def _running(d): return uniq([d + str(j) for j in range(10)] + [str(j) + d for j in range(10)])
def _hot_digit(H2, w): return Counter("".join(H2[-w:])).most_common(1)[0][0]
def _cold_digit(H2, w):
    c = Counter({str(i): 0 for i in range(10)}) | Counter("".join(H2[-w:]))
    return min(c.items(), key=lambda kv: (kv[1], kv[0]))[0]
for _w in (10, 20, 50, 100):
    reg(f"L-วิ่ง เลขร้อน [{_w}งวด] (19 ตัว)", lambda H2, H3, D, nd, _w=_w: _running(_hot_digit(H2, _w)))
    reg(f"L-วิ่ง เลขเย็น [{_w}งวด] (19 ตัว)", lambda H2, H3, D, nd, _w=_w: _running(_cold_digit(H2, _w)))
reg("L-วิ่ง หลักหน่วยงวดก่อน (19 ตัว)", lambda H2, H3, D, nd: _running(H2[-1][1]))
reg("L-วิ่ง หลักสิบงวดก่อน (19 ตัว)", lambda H2, H3, D, nd: _running(H2[-1][0]))
reg("L-วิ่ง ผลบวก 2 หลักงวดก่อน (19 ตัว)", lambda H2, H3, D, nd: _running(str((int(H2[-1][0]) + int(H2[-1][1])) % 10)))
def _longest_absent_digit(H2):
    last = {str(i): -1 for i in range(10)}
    for i, x in enumerate(H2):
        for ch in x: last[ch] = i
    return min(last, key=lambda d: (last[d], d))
reg("L-วิ่ง เลขที่หายไปนานสุด (19 ตัว)", lambda H2, H3, D, nd: _running(_longest_absent_digit(H2)))
reg("L-วิ่ง เลขร้อน 2 ตัว [50งวด] (36 ตัว)", lambda H2, H3, D, nd: uniq(sum([_running(d) for d, _ in Counter("".join(H2[-50:])).most_common(2)], [])))

# --- M: เลขถึงรอบ (ห่างเท่าช่วงห่างเฉลี่ยของตัวเอง)
def _periodic_due(H2, k):
    pos = {}
    for i, x in enumerate(H2): pos.setdefault(x, []).append(i)
    n = len(H2); sc = {}
    for x, p in pos.items():
        if len(p) >= 3:
            mg = (p[-1] - p[0]) / (len(p) - 1)
            if mg > 0: sc[x] = (n - p[-1]) / mg
    return [x for x, _ in sorted(sc.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]
for _k in (1, 3, 5, 10):
    reg(f"M-เลขถึงรอบ top{_k}", lambda H2, H3, D, nd, _k=_k: _periodic_due(H2, _k))
for _k in (3, 10):
    reg(f"M-เลขถึงรอบ [300งวด] top{_k}", lambda H2, H3, D, nd, _k=_k: _periodic_due(H2[-300:], _k))
reg("M-เลขเคยออก 2+ ครั้งแต่ห่างสุด top5", lambda H2, H3, D, nd: [x for x, _ in sorted(((x, len(H2) - max(i for i, y in enumerate(H2) if y == x)) for x, c in Counter(H2).items() if c >= 2), key=lambda t: (-t[1], t[0]))[:5]])

# --- N: รูปแบบเลข
reg("N-เลขเบิ้ลทั้งหมด (10 ตัว)", lambda H2, H3, D, nd: [f"{i}{i}" for i in range(10)])
reg("N-เลขเบิ้ลที่ค้างนานสุด 3 ตัว", lambda H2, H3, D, nd: sorted([f"{i}{i}" for i in range(10)], key=lambda n: max([j for j, x in enumerate(H2) if x == n] or [-1]))[:3])
reg("N-เลขเบิ้ลฮอต [200งวด] top3", lambda H2, H3, D, nd: [n for n, _ in Counter(x for x in H2[-200:] if x[0] == x[1]).most_common(3)])
reg("N-เลขเรียงขึ้น 01,12,..,89 (9 ตัว)", lambda H2, H3, D, nd: [f"{i}{i + 1}" for i in range(9)])
reg("N-เลขเรียงลง 10,21,..,98 (9 ตัว)", lambda H2, H3, D, nd: [f"{i + 1}{i}" for i in range(9)])
reg("N-เลขงวดก่อน + กลับ (2 ตัว)", lambda H2, H3, D, nd: uniq([H2[-1], rev(H2[-1])]))
reg("N-เลขงวดก่อน + กลับ + เสริม (4 ตัว)", lambda H2, H3, D, nd: uniq([H2[-1], rev(H2[-1]), two(99 - int(H2[-1])), rev(two(99 - int(H2[-1])))]))

# --- O: 3 ตัวบนขั้นสูง
def _pos_hot3(H3, w): return "".join(Counter(x[p] for x in H3[-w:]).most_common(1)[0][0] for p in range(3))
for _w in (50, 100, 300):
    reg(f"O-3ตัว: หลักร้อย-สิบ-หน่วยที่ออกบ่อย [{_w}งวด]", lambda H2, H3, D, nd, _w=_w: [_pos_hot3(H3, _w)])
for _L in (3, 4, 5):
    reg(f"O-3ตัว: เลขเดิม {_L} งวดก่อน", lambda H2, H3, D, nd, _L=_L: [H3[-_L]])
for _w in (100, 400):
    reg(f"O-3ตัว: ออกบ่อย 10 ตัว [{_w}งวด]", lambda H2, H3, D, nd, _w=_w: topk_counter(Counter(H3[-_w:]), 10))
def _gap3(H3, k):
    last = {x: i for i, x in enumerate(H3)}
    return sorted([x for x in last], key=lambda x: last[x])[:k]
reg("O-3ตัว: เลขที่เคยออกและห่างสุด 10 ตัว", lambda H2, H3, D, nd: _gap3(H3, 10))
reg("O-3ตัว: Markov เลข 3 ตัวต่อเลข top5", lambda H2, H3, D, nd: topk_counter(Counter(H3[i + 1] for i in range(len(H3) - 1) if H3[i] == H3[-1]), 5))
reg("O-3ตัว: หลักร้อยฮอต × 2 ตัวฮอต (10 ตัว)", lambda H2, H3, D, nd: [Counter(x[0] for x in H3[-100:]).most_common(1)[0][0] + n for n in topk_counter(Counter(H2[-100:]), 10)])
reg("O-3ตัว: บวก 3 งวด mod 1000", lambda H2, H3, D, nd: [f"{sum(int(x) for x in H3[-3:]) % 1000:03d}"])
reg("O-3ตัว: เลข 3 ตัวบน = 3 ตัวท้ายผลบวกงวดก่อน", lambda H2, H3, D, nd: [f"{(int(H3[-1]) * 7) % 1000:03d}"])

# --- P: ผลรวมตำแหน่งของเลข 6 ตัว
_PC = [(0, 2, 1, 3), (0, 3, 1, 2), (0, 5, 1, 4), (1, 4, 2, 5), (0, 4, 1, 5), (2, 5, 3, 4), (0, 1, 4, 5), (1, 2, 3, 5), (0, 2, 3, 5)]
for _i, (_a, _b, _c, _d) in enumerate(_PC):
    reg(f"P{_i + 1:02d}-ผลบวกตำแหน่ง ({_a + 1}+{_b + 1} , {_c + 1}+{_d + 1})",
        lambda H2, H3, D, nd, _a=_a, _b=_b, _c=_c, _d=_d: ([f"{(int(_last6(H2)[_a]) + int(_last6(H2)[_b])) % 10}{(int(_last6(H2)[_c]) + int(_last6(H2)[_d])) % 10}"] if _last6(H2) else []))
reg("P10-ผลบวก 3 ตัวหน้า , 3 ตัวหลัง", lambda H2, H3, D, nd: ([f"{sum(map(int, _last6(H2)[:3])) % 10}{sum(map(int, _last6(H2)[3:])) % 10}"] if _last6(H2) else []))
reg("P11-ผลต่างสัมบูรณ์ (1,2),(3,4)", lambda H2, H3, D, nd: ([f"{abs(int(_last6(H2)[0]) - int(_last6(H2)[1]))}{abs(int(_last6(H2)[2]) - int(_last6(H2)[3]))}"] if _last6(H2) else []))
reg("P12-ผลต่างสัมบูรณ์ (3,4),(5,6)", lambda H2, H3, D, nd: ([f"{abs(int(_last6(H2)[2]) - int(_last6(H2)[3]))}{abs(int(_last6(H2)[4]) - int(_last6(H2)[5]))}"] if _last6(H2) else []))
reg("P13-จำนวนเลขไม่ซ้ำ × ผลบวก", lambda H2, H3, D, nd: ([f"{len(set(_last6(H2))) % 10}{sum(map(int, _last6(H2))) % 10}"] if _last6(H2) else []))
reg("P14-ผลบวก 6 ตัวทั้งหมด (2 หลัก)", lambda H2, H3, D, nd: ([f"{sum(map(int, _last6(H2))) % 100:02d}"] if _last6(H2) else []))
reg("P15-ผลคูณหลักท้าย × หลักแรก", lambda H2, H3, D, nd: ([f"{(int(_last6(H2)[0]) * int(_last6(H2)[5])) % 100:02d}"] if _last6(H2) else []))

# --- กลุ่ม I: โหวตรวม (คำนวณจากตารางคำทายของทุกสูตรหลังจากนั้น ไม่นับเป็นสูตรใน F) -----------
META = [("I-โหวตรวมทุกสูตร top1", 1), ("I-โหวตรวมทุกสูตร top5", 5), ("I-โหวตรวมทุกสูตร top10", 10)]

# --- กลุ่ม Z: ตัวควบคุม (สุ่มล้วน) ที่ต้องแพ้/เสมอ ถ้าสูตรจริงไม่มีผล ------------------
for k in (1, 5, 10):
    reg(f"Z-ควบคุม: สุ่ม {k} ตัว", lambda H2, H3, D, nd, k=k: random.Random(len(H2) * 7919 + k).sample([f"{i:02d}" for i in range(100)], k))
for k in (5, 20):
    reg(f"Z-ควบคุม: สุ่ม 3 ตัวบน {k} ตัว", lambda H2, H3, D, nd, k=k: random.Random(len(H2) * 6151 + k).sample([f"{i:03d}" for i in range(1000)], k))

# ---------------------------------------------------------------- แบ็คเทสต์ / ตารางคำทาย
def binom_p_ge(k, n, p):
    """P(X >= k) แบบ exact (ไม่ใช้ scipy)"""
    if k <= 0: return 1.0
    if p <= 0: return 0.0
    if p >= 1: return 1.0
    lp, lq, lg_n = math.log(p), math.log1p(-p), math.lgamma(n + 1)
    tot = sum(math.exp(lg_n - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq) for i in range(k, n + 1))
    return min(1.0, tot)

def _clean_picks(picks):
    picks = list(dict.fromkeys(picks))
    if not picks: return []
    L = len(picks[0])
    return [p for p in picks if len(p) == L and p.isdigit()]

def bottom_frame(df):
    """ชุดข้อมูลสำหรับทาย '2 ตัวล่าง': ใช้เฉพาะงวดที่มีค่า 2 ตัวล่างครบ แล้วให้ t2 = 2 ตัวล่าง"""
    d = df[df.b2.str.fullmatch(r"\d{2}")].copy().reset_index(drop=True)
    d["t2"] = d.b2
    return d

def _meta_votes(getpk, names):
    out = {}
    w = Counter()
    for nm in names:
        pk = getpk(nm) or []
        for x in pk: w[x] += 1 / len(pk)
    ranked = [n for n, _ in sorted(w.items(), key=lambda kv: (-kv[1], kv[0]))]
    for mname, k in META: out[mname] = ranked[:k]
    return out

def compute_table(df, first, progress=None, should_stop=None, want=None):
    """คำนวณคำทายของทุกสูตรทุกงวดตั้งแต่ first ถึงงวดสุดท้าย (แต่ละงวดเห็นเฉพาะอดีต)"""
    set_history(df)
    H2, H3, D = df.t2.tolist(), df.t3.tolist(), df.dow.tolist()
    n = len(df)
    tbl = {name: {} for name, _ in F}
    km = {}
    for step, i in enumerate(range(first, n)):
        if should_stop and should_stop(): break
        for name, fn in F:
            k0 = km.get(name)
            if want and k0 is not None and k0 != want: continue
            try:
                pk = _clean_picks(fn(H2[:i], H3[:i], D[:i], D[i]))
            except Exception:
                continue
            if pk:
                tbl[name][i] = pk
                km.setdefault(name, len(pk[0]))
        if progress: progress(0.9 * (step + 1) / (n - first))
    if want in (None, 2):
        names2 = [nm for nm in tbl if km.get(nm) == 2 and not nm.startswith("Z-")]
        for mname, _ in META: tbl[mname] = {}
        for i in range(first, n):
            for mname, pk in _meta_votes(lambda nm: tbl[nm].get(i), names2).items():
                if pk: tbl[mname][i] = pk
    return tbl

def predict_next(df, next_dow, want=None):
    set_history(df)
    H2, H3, D = df.t2.tolist(), df.t3.tolist(), df.dow.tolist()
    out = {}
    for name, fn in F:
        try: out[name] = _clean_picks(fn(H2, H3, D, next_dow))
        except Exception: out[name] = []
    if want in (None, 2):
        names2 = [nm for nm, pk in out.items() if pk and len(pk[0]) == 2 and not nm.startswith("Z-")]
        out.update(_meta_votes(lambda nm: out.get(nm), names2))
    return out

def next_draw_date(df):
    """เดางวดถัดไปจากวันที่ออกบ่อยใน 60 งวดล่าสุด -> (YYYY-MM-DD, dow)"""
    dates = pd.to_datetime(df.draw_date)
    last = dates.iloc[-1]
    cnt = Counter(dates.iloc[-60:].dt.dayofweek)
    days = {d for d, c in cnt.items() if c >= 0.15 * min(60, len(dates))} or {(last.dayofweek + 1) % 7}
    for i in range(1, 8):
        c = last + pd.Timedelta(days=i)
        if c.dayofweek in days: return c.strftime("%Y-%m-%d"), c.dayofweek
    c = last + pd.Timedelta(days=1)
    return c.strftime("%Y-%m-%d"), c.dayofweek

def _kind_map(tbl):
    km = {}
    for name, d in tbl.items():
        for pk in d.values():
            km[name] = len(pk[0]); break
    return km

def _prefix(df, tbl, name, kind):
    n = len(df); act = df.t2.tolist() if kind == 2 else df.t3.tolist()
    ch, ce, cv = [0] * (n + 1), [0.0] * (n + 1), [0.0] * (n + 1)
    for i in range(n):
        pk = tbl[name].get(i); h = e = v = 0
        if pk:
            p = len(pk) / 10 ** kind
            h = 1 if act[i] in pk else 0; e = p; v = p * (1 - p)
        ch[i + 1] = ch[i] + h; ce[i + 1] = ce[i] + e; cv[i + 1] = cv[i] + v
    return ch, ce, cv

def _select(prefs, i, win, K):
    """คัด K สูตรที่ 'เกินค่าสุ่มมากสุด' (z-score) ในช่วง win งวดก่อนงวด i — ใช้เฉพาะอดีต"""
    a = max(0, i - win); zs = []
    for name, (ch, ce, cv) in prefs.items():
        var = cv[i] - cv[a]
        if var <= 1e-12: continue
        zs.append((((ch[i] - ch[a]) - (ce[i] - ce[a])) / math.sqrt(var), name))
    zs.sort(key=lambda t: (-t[0], t[1]))
    return zs[:K]

def _vote(sel, getpicks, N):
    w = Counter()
    for rank, (z, name) in enumerate(sel):
        pk = getpicks(name) or []
        for num in pk: w[num] += (len(sel) - rank) / len(pk)     # สูตรที่ทายหลายเลขแบ่งน้ำหนักกัน
    return [n for n, _ in sorted(w.items(), key=lambda kv: (-kv[1], kv[0]))[:N]]

def champion(df, tbl, nxt, kind, start, win=100, K=5, N=3):
    """ชุดเด่นสุดๆ: ทุกงวดคัด K สูตรที่เด่นสุดในอดีต -> โหวตเลข N ตัว  แล้ววัดผลกับงวดจริงที่ยังไม่เห็น"""
    km = _kind_map(tbl); n = len(df)
    pool = [nm for nm in tbl if km.get(nm) == kind and not nm.startswith("Z-")]
    if len(pool) < 3: return None
    prefs = {nm: _prefix(df, tbl, nm, kind) for nm in pool}
    act = df.t2.tolist() if kind == 2 else df.t3.tolist()
    tests = hits = 0; exp = 0.0; seq = []
    for i in range(start, n):
        sel = _select(prefs, i, win, K)
        nums = _vote(sel, lambda nm: tbl[nm].get(i), N) if sel else []
        if not nums: continue
        h = act[i] in nums
        tests += 1; exp += len(nums) / 10 ** kind; hits += h; seq.append(int(h))
    sel = _select(prefs, n, win, K)
    nums = _vote(sel, lambda nm: nxt.get(nm), N) if sel else []
    p_avg = exp / tests if tests else 0
    return dict(kind=kind, K=K, N=N, win=win, tests=tests, hits=hits,
                hit_pct=100 * hits / tests if tests else 0, exp_pct=100 * p_avg,
                p=binom_p_ge(hits, tests, p_avg) if tests else 1.0,
                numbers=nums, formulas=[(nm, z) for z, nm in sel], pool=len(pool), seq=seq)

def streak_stats(hits, ps, W=5):
    """สถิติสตรีค: พลาดติดสูงสุด / พลาดติดตอนนี้ / ถูกอย่างน้อย 1 ครั้งใน W งวด (จริง vs คาดสุ่ม) / หลังพลาด 3 งวดติด"""
    mx = cur = 0
    for h in hits:
        if h: cur = 0
        else:
            cur += 1; mx = max(mx, cur)
    nwin = cov = 0; expc = 0.0
    for st in range(0, len(hits) - W + 1):
        nwin += 1
        if any(hits[st:st + W]): cov += 1
        q = 1.0
        for p in ps[st:st + W]: q *= (1 - p)
        expc += 1 - q
    an = ah = run = 0
    for h in hits:
        if run >= 3:
            an += 1; ah += h
        run = 0 if h else run + 1
    return dict(max_miss=mx, cur_miss=cur, cover5=100 * cov / nwin if nwin else 0.0,
                exp_cover5=100 * expc / nwin if nwin else 0.0, after3_n=an, after3_hit=ah)

def analyze(df, test_n=300, win=100, K=5, N2=3, N3=5, progress=None, should_stop=None, want=None):
    """งานเดียวจบ: ตารางคำทาย -> สถิติ+สตรีคทุกสูตร -> ชุดเด่น -> เลขงวดหน้า  (want=2 -> เฉพาะเลข 2 ตัว)"""
    n = len(df)
    start = max(n - test_n, 60 + win)
    first = start - win
    tbl = compute_table(df, first, progress, should_stop, want)
    nd, dow = next_draw_date(df)
    nxt = predict_next(df, dow, want)
    H2, H3 = df.t2.tolist(), df.t3.tolist()
    km = _kind_map(tbl); m = max(1, len(km)); rows = []
    for name in tbl:
        kind = km.get(name)
        if not kind: continue
        act = H2 if kind == 2 else H3
        tests = hits = picks = 0; exp = 0.0; hs = []; ps = []
        for i in range(start, n):
            pk = tbl[name].get(i)
            if not pk: continue
            h = int(act[i] in pk); p = len(pk) / 10 ** kind
            tests += 1; picks += len(pk); exp += p; hits += h; hs.append(h); ps.append(p)
        if not tests: continue
        p_avg = exp / tests; pv = binom_p_ge(hits, tests, p_avg)
        row = dict(name=name, group=group_of(name), kind=kind, picks=round(picks / tests, 1), tests=tests, hits=hits,
                   hit_pct=100 * hits / tests, exp_pct=100 * p_avg, diff_pct=100 * (hits / tests - p_avg),
                   p=pv, p_adj=min(1.0, pv * m))
        row.update(streak_stats(hs, ps))
        rows.append(row)
    bt = pd.DataFrame(rows).sort_values("p").reset_index(drop=True)
    champ = {2: champion(df, tbl, nxt, 2, start, win, K, N2),
             3: champion(df, tbl, nxt, 3, start, win, K, N3) if want in (None, 3) else None}
    if progress: progress(1.0)
    return dict(bt=bt, champ=champ, next_picks=nxt, next_date=nd, dow=dow, start=start, win=win, n=n, tbl=tbl)

def group_summary(bt):
    """สรุปรายชุดลอจิก"""
    rows = []
    for g, d in bt.groupby("group"):
        rows.append(dict(group=g, formulas=len(d), avg_diff=d.diff_pct.mean(), best=d.iloc[0]["name"],
                         best_hit=f"{int(d.iloc[0].hits)}/{int(d.iloc[0].tests)}", sig_raw=int((d.p < 0.05).sum()),
                         sig_adj=int((d.p_adj < 0.05).sum()), cover5=d.cover5.mean(), exp_cover5=d.exp_cover5.mean()))
    return pd.DataFrame(rows).sort_values("avg_diff", ascending=False).reset_index(drop=True)

def backtest(df, test_n=300, progress=None, should_stop=None):
    return analyze(df, test_n, 100, progress=progress, should_stop=should_stop)["bt"]

# ---------------------------------------------------------------- แผนตามเลข / ตัวจำลองเงิน
def stake_schedule(rounds, stake, mode):
    if mode == "double": return [stake * 2 ** r for r in range(rounds)]
    if mode == "x1.5": return [stake * 1.5 ** r for r in range(rounds)]
    if mode == "fib":
        f = [1, 1]
        while len(f) < rounds: f.append(f[-1] + f[-2])
        return [stake * f[r] for r in range(rounds)]
    return [stake] * rounds

def plan_table(space, n_picks, payout, rounds=5, stake=1.0, mode="flat"):
    """ตารางแผน 'ตามเลข' ทางทฤษฎี: space=100 (2 ตัว) / 1000 (3 ตัว), payout=เท่าที่จ่ายต่อ 1 ส่วนที่แทง"""
    p = n_picks / space
    st = stake_schedule(rounds, stake, mode)
    rows = []; cum = 0.0; miss = 1.0; ev = 0.0
    for r in range(rounds):
        cost = st[r] * n_picks; cum += cost
        p_first = miss * p; profit = st[r] * payout - cum
        rows.append(dict(round=r + 1, stake=st[r], cost=cost, cum_cost=cum, p_first=p_first, p_cum=1 - miss * (1 - p), profit=profit))
        ev += p_first * profit; miss *= (1 - p)
    ev += miss * (-cum)
    return rows, dict(p_hit=1 - miss, p_all_miss=miss, worst_loss=cum, ev=ev, ev_per_cost=ev / cum if cum else 0.0)

def simulate_plan(df, tbl, name, kind, start, rounds, payout, stake, mode):
    """เล่นแผนตามเลขกับ 'ประวัติจริง' ด้วยคำทายของสูตรนั้น: รอบใหม่เริ่มหลังถูกหรือครบ rounds งวด"""
    act = df.t2.tolist() if kind == 2 else df.t3.tolist(); n = len(df)
    st = stake_schedule(rounds, stake, mode)
    t = start; cycles = hits = 0; net = 0.0; worst = 0.0; bal = 0.0; where = Counter()
    while t < n:
        cost = 0.0; won = False; r = 0
        for r in range(rounds):
            i = t + r
            if i >= n: cost = None; break
            pk = tbl[name].get(i)
            if not pk: cost = None; break
            cost += st[r] * len(pk)
            if act[i] in pk:
                net += st[r] * payout - cost; bal += st[r] * payout - cost; won = True; hits += 1; where[r + 1] += 1
                break
        if cost is None: break
        if not won:
            net -= cost; bal -= cost
        worst = min(worst, bal); cycles += 1; t += (r + 1)
    return dict(cycles=cycles, hits=hits, hit_rate=100 * hits / cycles if cycles else 0.0, net=net, worst=worst, where=dict(where))

def verdict_text(bt, n_draws, champ=None, label=""):
    m = len(bt)
    sig_adj = int((bt.p_adj < 0.05).sum()); sig_raw = int((bt.p < 0.05).sum())
    tests = int(bt.tests.max()) if m else 0
    best = bt.iloc[0] if m else None
    lines = [f"[{label}] ทดสอบ {m} สูตร × {tests} งวดล่าสุด (ข้อมูลสะอาด {n_draws} งวด)" if label else
             f"ทดสอบ {m} สูตร × {tests} งวดล่าสุด (ข้อมูลสะอาด {n_draws} งวด)",
             f"• สูตรที่ 'ดูเหมือนแม่น' (p<0.05): {sig_raw}  | คาดว่าเกิดจากดวงล้วนๆ ≈ {0.05 * m:.1f}",
             f"• สูตรที่ผ่านหลังแก้ Bonferroni: {sig_adj}"]
    if best is not None:
        lines.append(f"• อันดับ 1: {best['name']}  ถูก {int(best.hits)}/{int(best.tests)} ({best.hit_pct:.2f}%) "
                     f"คาดสุ่ม {best.exp_pct:.2f}%  p={best.p:.4f}  p-adj={best.p_adj:.3f}")
    if m:
        lines.append(f"• ถูกอย่างน้อย 1 ครั้งใน 5 งวด: เฉลี่ยทุกสูตร {bt.cover5.mean():.1f}%  vs คาดสุ่ม {bt.exp_cover5.mean():.1f}%")
        a_n = int(bt.after3_n.sum()); a_h = int(bt.after3_hit.sum())
        if a_n:
            lines.append(f"• หลังพลาดติด 3 งวด แล้วถูกในงวดถัดไป: {a_h}/{a_n} ({100 * a_h / a_n:.2f}%)  "
                         f"— ถ้า 'ใกล้ถึงรอบ' จริง ต้องสูงกว่าอัตราปกติ ({(bt.exp_pct * bt.after3_n).sum() / a_n:.2f}%)")
    if champ:
        lines.append("")
        lines.append("🏆 ชุดเด่นสุดๆ  (ทุกงวด: คัด K สูตรที่เด่นสุดใน win งวดก่อนหน้า -> โหวตเป็นชุดเดียว แล้ววัดกับงวดจริงที่ยังไม่เห็น)")
        for kind in (2, 3):
            c = champ.get(kind)
            if not c: continue
            lab = f"{label or '2 ตัว'}" if kind == 2 else "3 ตัวบน"
            lines.append(f"  {lab}: ถูก {c['hits']}/{c['tests']} ({c['hit_pct']:.2f}%) คาดสุ่ม {c['exp_pct']:.2f}%  p={c['p']:.3f}"
                         f"   [K={c['K']} สูตร, เลือก {c['N']} ตัว, win={c['win']}]")
            if c["numbers"]:
                lines.append(f"    ชุดสำหรับงวดหน้า: {' '.join(c['numbers'])}   (เด่นสุด: {c['numbers'][0]})")
    lines.append("")
    c2 = (champ or {}).get(2)
    if sig_adj == 0 and (not c2 or c2["p"] >= 0.05):
        lines.append("สรุป: ไม่พบสูตรหรือชุดเด่นใดเหนือกว่าการสุ่มอย่างมีนัยสำคัญ — การ 'เลือกสูตรที่ถูกสูงสุดย้อนหลัง' ไม่ได้ทายงวดถัดไปแม่นขึ้น")
    else:
        lines.append("สรุป: มีบางตัวผ่านเกณฑ์ ควรเฝ้าดูผลจริงในแท็บ 📈 ติดตามผลจริงอีกหลายสิบงวดก่อนเชื่อ (ผลเดียวอาจเป็นดวง)")
    lines.append("⚠️ ผลย้อนหลังไม่ใช่การรับประกันงวดหน้า")
    return "\n".join(lines)

def consensus(picks, top=8):
    c = Counter(n for v in picks.values() for n in v[:1] if v and len(n) == 2)
    return c.most_common(top)

if __name__ == "__main__":
    path = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    df, rep = clean_draws(legacy_csv_to_df(path))
    print("cleaning:", rep, "| formulas:", len(F))
    r = analyze(df, n)
    print(verdict_text(r["bt"], len(df), r["champ"]))
    print(group_summary(r["bt"]).to_string())
