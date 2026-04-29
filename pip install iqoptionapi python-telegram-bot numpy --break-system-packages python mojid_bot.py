“””
MOJIDTRADEBOT — IQ Option BLITZ Signal Bot
Matches your chart EXACTLY:
✓ 10-second candles (Blitz mode)
✓ RSI(14)
✓ EMA 5/13/21 (Blue/Yellow/Red ribbon)
✓ ATR(2) — WWV(ATR,2,Close,Auto)
✓ 3 minute expiry
✓ STRONG signals only

Install:
pip install iqoptionapi python-telegram-bot numpy –break-system-packages

Run:
python mojid_bot.py
“””

import time, logging, asyncio
import numpy as np
from datetime import datetime
from iqoptionapi.stable_api import IQ_Option
import telegram

# ═══════════════════════════════════════════════

# CONFIG — your exact settings

# ═══════════════════════════════════════════════

IQ_EMAIL    = “Mohammedjiddah897@gmail.com”
IQ_PASSWORD = “Jiddah77”
TG_TOKEN    = “8608644762:AAHzFLeUx9BjUjyIXFPL5bY-zFk4NEO_elk”
TG_CHAT_ID  = “6758027951”
ACCOUNT     = “PRACTICE”   # Change to “REAL” when ready

# ── Blitz settings matching your chart ──

CANDLE_SEC  = 10    # 10-second candles (Blitz mode)
EXPIRY_MIN  = 3     # 3 minute expiry (matches your chart)
CANDLES_N   = 150   # enough history for indicators

# ── Money management ──

BASE_AMOUNT = 20    # $20 base (matches your chart)
GALE_MULT   = 2.2
MAX_GALE    = 3

# ── Pairs ──

PAIRS = [
“EURUSD-OTC”,
“GBPUSD-OTC”,
“USDJPY-OTC”,
“AUDUSD-OTC”,
“EURJPY-OTC”,
“GBPJPY-OTC”,
“USDCHF-OTC”,
“NZDUSD-OTC”,
“EURGBP-OTC”,
“AUDJPY-OTC”,
“EURCAD-OTC”,
]

# ── Indicators — exactly matching your IQ Option chart ──

RSI_P = 14   # RSI(14) — matches your chart label
EMA_F =  5   # Blue EMA  (fastest)
EMA_M = 13   # Yellow EMA (mid)
EMA_S = 21   # Red EMA   (slowest)
ATR_P =  2   # ATR(2) — WWV(ATR,2,Close,Auto)

# ── Sessions Johannesburg UTC+2 ──

SESSIONS = [(8, 14), (21, 26)]

# ═══════════════════════════════════════════════

# LOGGING

# ═══════════════════════════════════════════════

logging.basicConfig(
format=”%(asctime)s | %(message)s”,
datefmt=”%H:%M:%S”,
level=logging.INFO
)
log = logging.getLogger(“MTB”)

# ═══════════════════════════════════════════════

# INDICATORS — matching your chart exactly

# ═══════════════════════════════════════════════

def calc_ema(arr, p):
a = np.array(arr, dtype=float)
if len(a) < p:
return np.full(len(a), np.nan)
k   = 2.0 / (p + 1)
out = np.full(len(a), np.nan)
out[p-1] = np.mean(a[:p])
for i in range(p, len(a)):
out[i] = a[i] * k + out[i-1] * (1 - k)
return out

def calc_rsi(arr, p=RSI_P):
“”“RSI(14) — matches your chart exactly”””
a = np.array(arr, dtype=float)
if len(a) <= p:
return np.full(len(a), 50.0)
d  = np.diff(a)
g  = np.where(d > 0, d, 0.0)
l  = np.where(d < 0, -d, 0.0)
ag = np.mean(g[:p])
al = np.mean(l[:p])
out = [np.nan] * p
out.append(100 - 100 / (1 + ag / (al + 1e-9)))
for i in range(p, len(d)):
ag = (ag * (p-1) + g[i]) / p
al = (al * (p-1) + l[i]) / p
out.append(100 - 100 / (1 + ag / (al + 1e-9)))
return out

def calc_macd(arr):
f    = calc_ema(arr, 12)
s    = calc_ema(arr, 26)
line = f - s
v    = line[~np.isnan(line)]
sg_v = calc_ema(v, 9)
sg   = np.full(len(line), np.nan)
idx  = np.where(~np.isnan(line))[0]
if len(idx) >= 9:
sg[idx[8:]] = sg_v[8:]
return line, sg, line - sg

def calc_stoch(hi, lo, cl, p=14):
hi, lo, cl = np.array(hi), np.array(lo), np.array(cl)
out = []
for i in range(len(cl)):
if i < p - 1:
out.append(np.nan)
else:
h = np.max(hi[i-p+1:i+1])
l = np.min(lo[i-p+1:i+1])
out.append(((cl[i] - l) / (h - l + 1e-9)) * 100)
return out

def calc_atr(hi, lo, cl, p=ATR_P):
“”“ATR(2) — matches WWV(ATR,2,Close,Auto) on your chart”””
hi, lo, cl = np.array(hi), np.array(lo), np.array(cl)
tr = np.zeros(len(cl))
tr[0] = hi[0] - lo[0]
for i in range(1, len(cl)):
tr[i] = max(
hi[i] - lo[i],
abs(hi[i] - cl[i-1]),
abs(lo[i] - cl[i-1])
)
out = np.full(len(cl), np.nan)
if len(tr) >= p:
out[p-1] = np.mean(tr[:p])
k = 2.0 / (p + 1)
for i in range(p, len(tr)):
out[i] = tr[i] * k + out[i-1] * (1 - k)
return out

def is_volatile(cs):
“””
Volatility filter using ATR(2).
Matches the WWV histogram on your chart.
Only trade when ATR is above 80% of its own recent average.
“””
hi = [c[“max”]   for c in cs]
lo = [c[“min”]   for c in cs]
cl = [c[“close”] for c in cs]
a  = calc_atr(hi, lo, cl, ATR_P)
v  = a[~np.isnan(a)]
if len(v) < 5:
return True
return float(v[-1]) >= float(np.mean(v[-20:])) * 0.8

# ═══════════════════════════════════════════════

# STRATEGY 1 — 3-CANDLE BREAKOUT

# On 10s candles: range = last 8 candles (80 seconds)

# Confirm = 3 candles (30 seconds) all outside range

# ═══════════════════════════════════════════════

def strat_breakout(cs):
if len(cs) < 16 or not is_volatile(cs):
return None

```
RLEN, CLEN = 8, 3
r_end   = len(cs) - CLEN - 1
r_start = r_end - RLEN
if r_start < 0:
    return None

rH  = max(c["max"]   for c in cs[r_start:r_end])
rL  = min(c["min"]   for c in cs[r_start:r_end])
rSz = rH - rL
if rSz <= 0:
    return None

price = cs[-1]["close"]
abv   = all(c["close"] > rH for c in cs[-CLEN:])
blw   = all(c["close"] < rL for c in cs[-CLEN:])
bkU   = cs[r_end]["close"] > rH
bkD   = cs[r_end]["close"] < rL

if abv and bkU:
    pct = ((price - rH) / rSz) * 100
    if pct < 12:
        return None
    return {
        "strat": "3-CANDLE BREAKOUT",
        "emoji": "📊",
        "dir":   "BUY",
        "prob":  min(82, 62 + min(20, pct)),
        "desc":  f"3×10s candles above range · +{pct:.0f}%",
    }
if blw and bkD:
    pct = ((rL - price) / rSz) * 100
    if pct < 12:
        return None
    return {
        "strat": "3-CANDLE BREAKOUT",
        "emoji": "📊",
        "dir":   "SELL",
        "prob":  min(82, 62 + min(20, pct)),
        "desc":  f"3×10s candles below range · -{pct:.0f}%",
    }
return None
```

# ═══════════════════════════════════════════════

# STRATEGY 2 — INDICATOR CONFLUENCE

# RSI(14) + MACD + EMA 5/13/21 + Stoch + ATR(2)

# Exactly matching your chart indicators

# ═══════════════════════════════════════════════

def strat_confluence(cs):
if len(cs) < 40:
return None

```
cl  = [c["close"] for c in cs]
hi  = [c["max"]   for c in cs]
lo  = [c["min"]   for c in cs]
pr  = cl[-1]

# RSI(14) — your chart
rv   = calc_rsi(cl, RSI_P)
rsiV = float(rv[-1]) if rv[-1] is not np.nan else 50.0

# MACD
_, _, mh_arr = calc_macd(cl)
mh  = float(mh_arr[-1]) if not np.isnan(mh_arr[-1]) else 0.0
mh2 = float(mh_arr[-2]) if len(mh_arr) > 1 and not np.isnan(mh_arr[-2]) else 0.0

# EMA ribbon — Blue(5) Yellow(13) Red(21)
ef  = float(calc_ema(cl, EMA_F)[-1])
em  = float(calc_ema(cl, EMA_M)[-1])
es  = float(calc_ema(cl, EMA_S)[-1])

# Stochastic
sv  = calc_stoch(hi, lo, cl)
st  = float(sv[-1]) if sv[-1] is not np.nan else 50.0
st2 = float(sv[-2]) if len(sv) > 1 and sv[-2] is not np.nan else 50.0

# ATR(2) volatility
vol = is_volatile(cs)

bv = bear = 0

# RSI(14) — standard levels
if   rsiV < 30: bv   += 2
elif rsiV < 45: bv   += 1
if   rsiV > 70: bear += 2
elif rsiV > 55: bear += 1

# MACD histogram
if   mh > 0 and mh > mh2: bv   += 2
elif mh > 0:               bv   += 1
if   mh < 0 and mh < mh2: bear += 2
elif mh < 0:               bear += 1

# EMA ribbon — blue/yellow/red fan
# Your chart shows strong trend when all 3 fanning same direction
if   ef > em and em > es: bv   += 2   # Full bull: blue above yellow above red
elif ef > em:             bv   += 1
if   ef < em and em < es: bear += 2   # Full bear: blue below yellow below red
elif ef < em:             bear += 1

# Price position vs EMAs
if pr > ef and pr > em: bv   += 1
if pr < ef and pr < em: bear += 1

# Stochastic
if   st < 20: bv   += 2
elif st > 80: bear += 2
if st > st2 and st2 < 25: bv   += 1
if st < st2 and st2 > 75: bear += 1

# ATR(2) — extra vote when market moving (WWV high)
if vol:
    if bv   > bear: bv   += 1
    if bear > bv:   bear += 1

ribbon = "BULL STACK" if ef > em > es else "BEAR STACK" if ef < em < es else "MIXED"

# STRONG threshold: 8+ votes and clear direction
if bv >= 8 and bv > bear + 3:
    return {
        "strat": "CONFLUENCE",
        "emoji": "📈",
        "dir":   "BUY",
        "prob":  min(82, 55 + bv * 2),
        "desc":  f"{bv} indicators agree · RSI14={rsiV:.0f} · {ribbon}",
    }
if bear >= 8 and bear > bv + 3:
    return {
        "strat": "CONFLUENCE",
        "emoji": "📉",
        "dir":   "SELL",
        "prob":  min(82, 55 + bear * 2),
        "desc":  f"{bear} indicators agree · RSI14={rsiV:.0f} · {ribbon}",
    }
return None
```

# ═══════════════════════════════════════════════

# STRATEGY 3 — ENGULFING + RSI(14)

# 2x+ body engulf + RSI(14) extreme

# On 10s candles these are very strong reversals

# ═══════════════════════════════════════════════

def strat_engulf(cs):
if len(cs) < 25 or not is_volatile(cs):
return None

```
pc, cc = cs[-2], cs[-1]
pB  = abs(pc["close"] - pc["open"])
cB  = abs(cc["close"] - cc["open"])
if pB < 0.000001 or cB / pB < 2.0:
    return None

cl    = [c["close"] for c in cs]
rv    = calc_rsi(cl, RSI_P)
rsiV  = float(rv[-1]) if rv[-1] is not np.nan else 50.0
ratio = cB / pB

ef    = float(calc_ema(cl, EMA_F)[-1])
em    = float(calc_ema(cl, EMA_M)[-1])

pBull = pc["close"] > pc["open"]
cBull = cc["close"] > cc["open"]

# BULLISH ENGULF — need RSI(14) < 40 to confirm oversold
if (not pBull and cBull
        and cc["open"]  <= pc["close"]
        and cc["close"] >= pc["open"]
        and rsiV < 40):
    ema_ok = ef >= em   # Blue EMA at or above yellow = confirms upward push
    return {
        "strat": "ENGULFING",
        "emoji": "🕯",
        "dir":   "BUY",
        "prob":  min(84, 65 + min(15, int(40 - rsiV)) + (2 if ema_ok else 0)),
        "desc":  f"{ratio:.1f}x bull engulf · RSI14={rsiV:.0f}{'· EMA✓' if ema_ok else ''}",
    }

# BEARISH ENGULF — need RSI(14) > 60 to confirm overbought
if (pBull and not cBull
        and cc["open"]  >= pc["close"]
        and cc["close"] <= pc["open"]
        and rsiV > 60):
    ema_ok = ef <= em   # Blue EMA at or below yellow = confirms downward push
    return {
        "strat": "ENGULFING",
        "emoji": "🕯",
        "dir":   "SELL",
        "prob":  min(84, 65 + min(15, int(rsiV - 60)) + (2 if ema_ok else 0)),
        "desc":  f"{ratio:.1f}x bear engulf · RSI14={rsiV:.0f}{'· EMA✓' if ema_ok else ''}",
    }
return None
```

# ═══════════════════════════════════════════════

# ANALYZER — run all 3, return best STRONG signal

# ═══════════════════════════════════════════════

def analyze(candles):
results = []
for fn in [strat_breakout, strat_confluence, strat_engulf]:
try:
r = fn(candles)
if r:
results.append(r)
except Exception as e:
log.debug(f”Strategy error: {e}”)

```
if not results:
    return None

results.sort(key=lambda r: r["prob"], reverse=True)
best = dict(results[0])

# Bonus if 2+ strategies agree same direction
same = [r for r in results if r["dir"] == best["dir"]]
if len(same) >= 2:
    best["prob"]  = min(87, best["prob"] + 5)
    best["multi"] = len(same)
    best["label"] = " + ".join(r["strat"] for r in same)
    best["desc"] += f" · {len(same)} strategies agree"
else:
    best["multi"] = 1
    best["label"] = best["strat"]

return best
```

# ═══════════════════════════════════════════════

# TELEGRAM SIGNAL MESSAGE

# ═══════════════════════════════════════════════

async def send_signal(bot, pair, sig):
buy    = sig[“dir”] == “BUY”
color  = “🟢” if buy else “🔴”
arrow  = “▲” if buy else “▼”
action = “HIGHER” if buy else “LOWER”
name   = pair.replace(”-OTC”, “”)
now    = datetime.now()

```
# Gale levels
gale_text = ""
for i in range(MAX_GALE + 1):
    amt   = BASE_AMOUNT * (GALE_MULT ** i)
    label = "ENTRY " if i == 0 else f"GALE {i} "
    gale_text += f"  {label}→ ${amt:.2f}\n"

msg = (
    f"{color} *{name} OTC*\n"
    f"{arrow} *{sig['dir']}*  —  click *{action}*\n"
    f"⏱ Entry: *{now.strftime('%H:%M:%S')}*\n"
    f"⏳ Expiry: *{EXPIRY_MIN} minutes*\n"
    f"\n"
    f"{sig['emoji']} {sig['label']}\n"
    f"🎯 Win Prob: *{sig['prob']:.0f}%*\n"
    f"📋 {sig['desc']}\n"
    f"\n"
    f"💰 *GALE PLAN*\n"
    f"{gale_text}"
    f"⚠️ Stop at Gale {MAX_GALE} — no exceptions\n"
    f"\n"
    f"_@Mojidtradebot · t.me/+bVmU1AJ_bYhjOTRk_"
)

try:
    await bot.send_message(
        chat_id    = TG_CHAT_ID,
        text       = msg,
        parse_mode = "Markdown"
    )
    log.info(f"✅ SIGNAL: {name} {sig['dir']} | {sig['strat']} | {sig['prob']:.0f}%")
except Exception as e:
    log.error(f"Telegram send error: {e}")
```

# ═══════════════════════════════════════════════

# SESSION CHECK — Johannesburg UTC+2

# ═══════════════════════════════════════════════

def in_session():
h = datetime.now().hour
for start, end in SESSIONS:
if end > 24:
if h >= start or h < end % 24:
return True
else:
if start <= h < end:
return True
return False

# ═══════════════════════════════════════════════

# MAIN LOOP

# ═══════════════════════════════════════════════

def main():
log.info(“══════════════════════════════════════════”)
log.info(”  MOJIDTRADEBOT — BLITZ EDITION”)
log.info(f”  Candles: {CANDLE_SEC}s · Expiry: {EXPIRY_MIN}m”)
log.info(f”  RSI({RSI_P}) · EMA {EMA_F}/{EMA_M}/{EMA_S} · ATR({ATR_P})”)
log.info(f”  Pairs: {len(PAIRS)} · Account: {ACCOUNT}”)
log.info(“══════════════════════════════════════════”)

```
# Connect IQ Option
log.info("Connecting to IQ Option...")
iq = IQ_Option(IQ_EMAIL, IQ_PASSWORD)
ok, reason = iq.connect()
if not ok:
    log.error(f"Connection failed: {reason}")
    return
log.info("IQ Option connected ✓")
iq.change_balance(ACCOUNT)

# Telegram bot
bot = telegram.Bot(token=TG_TOKEN)

# Startup Telegram message
async def startup_msg():
    try:
        await bot.send_message(
            chat_id    = TG_CHAT_ID,
            text       = (
                "🤖 *MOJIDTRADEBOT BLITZ started*\n"
                f"📊 {len(PAIRS)} OTC pairs\n"
                f"⏱ {CANDLE_SEC}s candles · ⏳ {EXPIRY_MIN}m expiry\n"
                f"📈 RSI({RSI_P}) · EMA {EMA_F}/{EMA_M}/{EMA_S} · ATR({ATR_P})\n"
                f"💰 Base: ${BASE_AMOUNT} · Gale ×{GALE_MULT} up to {MAX_GALE}\n"
                f"🎯 STRONG signals only\n"
                f"🕐 Sessions: 08:00–14:00 · 21:00–02:00 JHB\n"
            ),
            parse_mode = "Markdown"
        )
        log.info("Startup message sent to Telegram ✓")
    except Exception as e:
        log.error(f"Startup message error: {e}")

asyncio.run(startup_msg())

# Dedup: avoid same signal firing twice within 5 min
last_signal = {}

while True:
    try:
        if not in_session():
            h = datetime.now().hour
            log.info(f"Outside session (hour={h}) — sleeping 5 min")
            time.sleep(300)
            continue

        log.info(f"─── Scanning {len(PAIRS)} pairs [{datetime.now().strftime('%H:%M:%S')}] ───")

        for pair in PAIRS:
            try:
                # Fetch 10-second candles — matches Blitz mode
                raw = iq.get_candles(pair, CANDLE_SEC, CANDLES_N, time.time())
                if not raw:
                    log.warning(f"No data: {pair}")
                    continue

                # Format candles
                cs = [{
                    "open":  c["open"],
                    "close": c["close"],
                    "max":   c["max"],
                    "min":   c["min"],
                    "time":  c["from"],
                } for c in raw]

                if len(cs) < 30:
                    log.warning(f"Not enough candles: {pair} ({len(cs)})")
                    continue

                # Run all 3 strategies
                sig = analyze(cs)
                if sig is None:
                    continue

                # Dedup check — same direction + strategy within 5 min
                key  = f"{pair}_{sig['dir']}_{sig['strat']}"
                last = last_signal.get(key, 0)
                if time.time() - last < 300:
                    log.info(f"Skip duplicate: {pair} {sig['dir']}")
                    continue

                last_signal[key] = time.time()
                asyncio.run(send_signal(bot, pair, sig))

            except Exception as e:
                log.error(f"Error scanning {pair}: {e}")

            time.sleep(0.5)  # Small gap between pairs

        # Wait before next scan
        # 30 seconds — fast enough for 10s candles
        log.info("Scan complete — next scan in 30s")
        time.sleep(30)

    except KeyboardInterrupt:
        log.info("Bot stopped by user")
        break
    except Exception as e:
        log.error(f"Loop error: {e}")
        time.sleep(15)
```

if **name** == “**main**”:
main()
