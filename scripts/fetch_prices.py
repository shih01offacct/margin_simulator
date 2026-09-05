#!/usr/bin/env python3
"""
抓取證交所(上市)+ 櫃買中心(上櫃)全部個股的最近交易日收盤價,
寫成 prices.json 供網頁讀取(同網域,不受 CORS 限制)。
由 GitHub Actions 每個交易日收盤後自動執行。
"""
import json, sys, urllib.request, datetime, os

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prices.json")

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def roc_to_iso(s):
    s = (s or "").strip()
    if len(s) < 7: return ""
    return str(int(s[:3]) + 1911) + s[3:]

def to_float(v):
    try:
        v = str(v).replace(",", "").strip()
        return float(v) if v not in ("", "--", "-") else None
    except ValueError:
        return None

data = {}
errors = []

try:
    for r in get_json(TWSE_URL):
        p = to_float(r.get("ClosingPrice"))
        code = (r.get("Code") or "").strip()
        if code and p is not None:
            data[code] = {"p": p, "d": roc_to_iso(r.get("Date")), "n": r.get("Name", ""), "m": "twse"}
    print(f"TWSE ok: {sum(1 for v in data.values() if v['m']=='twse')} rows")
except Exception as e:
    errors.append(f"TWSE: {e}"); print("TWSE failed:", e, file=sys.stderr)

try:
    n = 0
    for r in get_json(TPEX_URL):
        p = to_float(r.get("Close"))
        code = (r.get("SecuritiesCompanyCode") or "").strip()
        if code and p is not None and code not in data:
            data[code] = {"p": p, "d": roc_to_iso(r.get("Date")), "n": r.get("CompanyName", ""), "m": "tpex"}
            n += 1
    print(f"TPEx ok: {n} rows")
except Exception as e:
    errors.append(f"TPEx: {e}"); print("TPEx failed:", e, file=sys.stderr)

if not data:
    print("No data fetched, abort without overwriting.", file=sys.stderr)
    sys.exit(1)

# 若只有一邊成功,保留舊檔裡另一邊的資料,避免整批消失
try:
    with open(OUT, encoding="utf-8") as f:
        old = json.load(f).get("data", {})
    markets_ok = {v["m"] for v in data.values()}
    for code, v in old.items():
        if v.get("m") not in markets_ok and code not in data:
            data[code] = v
except Exception:
    pass

out = {
    "updatedAt": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
    "errors": errors,
    "count": len(data),
    "data": dict(sorted(data.items())),
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(f"Wrote {OUT}: {len(data)} codes, updatedAt {out['updatedAt']}")
