#!/usr/bin/env python3
"""
抓取 上市(證交所)+ 上櫃(櫃買中心)全部個股的最近交易日收盤價,
寫成 prices.json 供網頁讀取(同網域,不受 CORS 限制)。
由 GitHub Actions 每個交易日收盤後自動執行。

資料來源(依序):
  上市 1. 證交所「每日收盤行情」MI_INDEX  → 收盤當天下午就有(主要來源)
  上市 2. 證交所 OpenAPI STOCK_DAY_ALL   → 常常晚一個交易日才更新(備援)
  上櫃 1. 櫃買中心 OpenAPI tpex_mainboard_quotes
"""
import json, sys, urllib.request, urllib.error, datetime, os, time

TWSE_MI_INDEX = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALLBUT0999&response=json"
TWSE_OPENAPI  = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_OPENAPI  = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prices.json")

TZ8 = datetime.timezone(datetime.timedelta(hours=8))
NOW = datetime.datetime.now(TZ8)


def get_json(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.twse.com.tw/",
            })
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(3 * (i + 1))
    raise last


def roc_to_iso(s):
    s = (s or "").strip()
    if len(s) < 7:
        return ""
    return str(int(s[:3]) + 1911) + s[3:]


def to_float(v):
    try:
        v = str(v).replace(",", "").strip()
        return float(v) if v not in ("", "--", "-") else None
    except ValueError:
        return None


data = {}
errors = []
notes = []

# ── 上市 1:證交所 每日收盤行情(當天就有)。從今天往回找最多 10 天 ──
twse_ok = False
for back in range(0, 10):
    day = NOW - datetime.timedelta(days=back)
    if day.weekday() >= 5:          # 週六日跳過
        continue
    d = day.strftime("%Y%m%d")
    try:
        j = get_json(TWSE_MI_INDEX.format(d=d))
    except Exception as e:
        errors.append(f"TWSE MI_INDEX {d}: {e}")
        continue
    if j.get("stat") != "OK":
        continue                    # 這天沒交易(休市/尚未公布),往前一天
    tables = j.get("tables") or []
    tbl = next((t for t in tables if "每日收盤行情" in (t.get("title") or "")), None)
    if not tbl:
        continue
    fields = tbl.get("fields") or []
    try:
        i_code, i_name, i_close = fields.index("證券代號"), fields.index("證券名稱"), fields.index("收盤價")
    except ValueError:
        errors.append(f"TWSE MI_INDEX {d}: 欄位格式改變 {fields}")
        break
    n = 0
    for row in tbl.get("data") or []:
        p = to_float(row[i_close]) if len(row) > i_close else None
        code = (row[i_code] or "").strip()
        if code and p is not None:
            data[code] = {"p": p, "d": d, "n": (row[i_name] or "").strip(), "m": "twse"}
            n += 1
    print(f"TWSE MI_INDEX {d}: {n} rows")
    notes.append(f"上市 {d}")
    twse_ok = n > 0
    break

# ── 上市 2:OpenAPI 備援(只在上面失敗時用) ──
if not twse_ok:
    try:
        n = 0
        for r in get_json(TWSE_OPENAPI):
            p = to_float(r.get("ClosingPrice"))
            code = (r.get("Code") or "").strip()
            if code and p is not None:
                data[code] = {"p": p, "d": roc_to_iso(r.get("Date")), "n": r.get("Name", ""), "m": "twse"}
                n += 1
        print(f"TWSE OpenAPI (fallback): {n} rows")
        notes.append("上市 OpenAPI 備援")
    except Exception as e:
        errors.append(f"TWSE OpenAPI: {e}")
        print("TWSE OpenAPI failed:", e, file=sys.stderr)

# ── 上櫃:櫃買中心 OpenAPI ──
try:
    n = 0
    for r in get_json(TPEX_OPENAPI):
        p = to_float(r.get("Close"))
        code = (r.get("SecuritiesCompanyCode") or "").strip()
        if code and p is not None and code not in data:
            data[code] = {"p": p, "d": roc_to_iso(r.get("Date")), "n": r.get("CompanyName", ""), "m": "tpex"}
            n += 1
    print(f"TPEx OpenAPI: {n} rows")
except Exception as e:
    errors.append(f"TPEx: {e}")
    print("TPEx failed:", e, file=sys.stderr)

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
    "updatedAt": NOW.strftime("%Y-%m-%d %H:%M"),
    "notes": notes,
    "errors": errors,
    "count": len(data),
    "data": dict(sorted(data.items())),
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(f"Wrote {OUT}: {len(data)} codes, updatedAt {out['updatedAt']}, errors={errors}")
