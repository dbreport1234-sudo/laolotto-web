# -*- coding: utf-8 -*-
"""ดึงผลหวยลาวจาก thaiorc (ตรรกะ parse เดียวกับ v4) แล้วผสานเข้า data/lao_lottery_full.csv
กติกา: ไม่เขียนทับวันที่ที่มีอยู่ (ถ้าไม่ตรง -> บันทึก data/import_conflicts.csv) | ตรวจความสอดคล้องของเลขก่อนรับเข้า"""
import csv, re, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "lao_lottery_full.csv"
CONFLICT_PATH = ROOT / "data" / "import_conflicts.csv"
URL = "https://lotto.thaiorc.com/lao/stats/lottery-years10.php"
FIELDS = ["draw_date", "number6", "number3_top", "number2_top", "number2_bottom", "source"]
PAGE_LIMIT = 100


def parse_page(html, source_url=URL):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"], recursive=False)
        if len(cells) < 5: continue
        m = re.search(r"(?<!\d)(\d{1,2}/\d{1,2}/\d{4})(?!\d)", cells[0].get_text(" ", strip=True))
        if not m: continue
        v = [c.get_text(" ", strip=True) for c in cells[1:5]]
        if not (re.fullmatch(r"\d{6}", v[0]) and re.fullmatch(r"\d{3}", v[1]) and re.fullmatch(r"\d{2}", v[2]) and re.fullmatch(r"\d{2}", v[3])):
            continue
        records.append({"draw_date": m.group(1), "number6": v[0], "number3_top": v[1], "number2_top": v[2],
                        "number2_bottom": v[3], "source": source_url})
    return records


def fetch_rows():
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"})
    found, prev = {}, None
    for page in range(1, PAGE_LIMIT + 1):
        r = s.get(URL, params={"pg": page}, timeout=35)
        r.raise_for_status(); r.encoding = r.apparent_encoding
        rows = parse_page(r.text)
        if not rows: break
        sig = tuple((x["draw_date"], x["number6"]) for x in rows)
        if sig == prev: break
        for x in rows: found.setdefault(x["draw_date"], x)
        prev = sig; time.sleep(0.35)
    return list(found.values())


def valid(r):
    """ตรวจความสอดคล้อง: 3 ตัวบน/2 ตัวบน = ท้ายของเลข 6 ตัว, 2 ตัวล่าง = หลัก 3-4"""
    n6 = r["number6"]
    return (r["number3_top"] == n6[-3:] and r["number2_top"] == n6[-2:] and r["number2_bottom"] == n6[2:4])


def date_key(t):
    d, m, y = t.split("/"); return int(y), int(m), int(d)


def read_existing():
    if not CSV_PATH.exists(): return {}
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        return {r["draw_date"]: r for r in csv.DictReader(f)}


def merge(existing, incoming):
    """คืน (rows หลังผสาน, รายงาน) — ฟังก์ชันล้วน ทดสอบได้โดยไม่ต้องใช้เน็ต"""
    out = dict(existing); rep = {"added": 0, "same": 0, "conflict": [], "rejected": []}
    used6 = {r["number6"] for r in existing.values()}
    for r in incoming:
        d = r["draw_date"]
        if not valid(r):
            rep["rejected"].append((d, "เลขไม่สอดคล้องกัน")); continue
        if d in out:
            old = out[d]
            if all(old.get(k) == r[k] for k in ("number6", "number3_top", "number2_top", "number2_bottom")): rep["same"] += 1
            else: rep["conflict"].append((old, r))
            continue
        if r["number6"] in used6:
            rep["rejected"].append((d, f"เลข {r['number6']} ซ้ำกับงวดอื่น (น่าจะเป็นข้อมูลเสีย)")); continue
        out[d] = r; used6.add(r["number6"]); rep["added"] += 1
    return out, rep


def main():
    existing = read_existing()
    incoming = fetch_rows()
    print(f"อ่านจากเว็บ {len(incoming)} แถว | ในไฟล์เดิม {len(existing)} แถว")
    if len(incoming) < 50:
        print("ข้อมูลที่อ่านได้น้อยผิดปกติ — ไม่แก้ไฟล์"); sys.exit(0)
    out, rep = merge(existing, incoming)
    print(f"เพิ่ม {rep['added']} | ตรงกันอยู่แล้ว {rep['same']} | ขัดแย้ง {len(rep['conflict'])} | ปฏิเสธ {len(rep['rejected'])}")
    for d, why in rep["rejected"][:20]: print("  REJECT", d, why)
    if rep["conflict"]:
        new = not CONFLICT_PATH.exists()
        with open(CONFLICT_PATH, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if new: w.writerow(["detected_at", "draw_date", "existing", "incoming"])
            for old, r in rep["conflict"]:
                w.writerow([datetime.now().isoformat(timespec="seconds"), r["draw_date"], "|".join(old[k] for k in FIELDS[1:5]), "|".join(r[k] for k in FIELDS[1:5])])
    if rep["added"]:
        with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(FIELDS)
            for d in sorted(out, key=date_key): w.writerow([out[d].get(k, "") for k in FIELDS])
        print("บันทึกไฟล์แล้ว")


if __name__ == "__main__":
    main()
