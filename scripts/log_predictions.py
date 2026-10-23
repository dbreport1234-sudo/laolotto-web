# -*- coding: utf-8 -*-
"""สร้าง 'คำทายล่วงหน้า' ของงวดถัดไป เก็บเป็น data/predictions/YYYY-MM-DD.json.gz (ไม่เขียนทับของเดิม)
เงื่อนไขกันโกง: ต้องสร้างก่อน 19:00 (เวลาไทย) ของวันที่ออกรางวัล — วันที่ commit บน GitHub คือหลักฐานเวลา"""
import gzip, json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import formula_engine as fe

DATA = ROOT / "data" / "lao_lottery_full.csv"
PRED = ROOT / "data" / "predictions"
DEADLINE_HOUR = 19


def to_iso(s):
    d, m, y = s.split("/"); y = int(y); y -= 543 if y > 2400 else 0
    return f"{y:04d}-{int(m):02d}-{int(d):02d}"


def load_raw():
    d = pd.read_csv(DATA, dtype=str, encoding="utf-8-sig")
    return pd.DataFrame({"draw_date": d.draw_date.map(to_iso), "digit_6": d.number6, "top3": d.number3_top,
                         "top2": d.number2_top, "bottom2": d.number2_bottom}).sort_values("draw_date")


def main(force=False):
    clean, _ = fe.clean_draws(load_raw())
    top = fe.analyze(clean, 400, 100)
    nd = top["next_date"]
    path = PRED / f"{nd}.json.gz"
    if path.exists(): print("มีคำทายของ", nd, "อยู่แล้ว — ข้าม"); return
    now_ict = (datetime.now(timezone.utc) + timedelta(hours=7)).replace(tzinfo=None)
    if not force and now_ict >= datetime.fromisoformat(f"{nd} {DEADLINE_HOUR:02d}:00:00"):
        print(f"เลยเวลา {DEADLINE_HOUR}:00 ของวันที่ {nd} แล้ว — ไม่สร้างคำทาย (กันการทายหลังผลออก)"); return
    bot = None
    dfb = fe.bottom_frame(clean)
    if len(dfb) >= 190: bot = fe.analyze(dfb, 400, 100, want=2)
    targets = {"top2": {"champion": top["champ"][2], "picks": {}}, "top3": {"champion": top["champ"][3], "picks": {}}}
    for name, pk in top["next_picks"].items():
        if pk: targets["top3" if len(pk[0]) == 3 else "top2"]["picks"][name] = " ".join(pk)
    if bot:
        targets["bottom2"] = {"champion": bot["champ"][2], "picks": {n: " ".join(pk) for n, pk in bot["next_picks"].items() if pk and len(pk[0]) == 2}}
    for t in targets.values():
        c = t["champion"]
        if c: t["champion"] = {k: c[k] for k in ("numbers", "tests", "hits", "hit_pct", "exp_pct", "p", "K", "N", "win")}
    payload = {"target_date": nd, "created_at_utc": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
               "data_through": clean.draw_date.iloc[-1], "formulas": len(fe.F), "targets": targets}
    PRED.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f: json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print("บันทึกคำทายงวด", nd, "->", path.name, "| ข้อมูลถึง", payload["data_through"])


if __name__ == "__main__":
    main(force="--force" in sys.argv)
