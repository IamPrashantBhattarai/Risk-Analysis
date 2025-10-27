import numpy as np
import pandas as pd

# ---------- Config ----------
N = 10_000
RNG = np.random.default_rng(42)

# Nepal-ish bounding box for realism (tweak if you want other regions)
LAT_RANGE = (26.3, 30.5)
LON_RANGE = (80.0, 88.3)

# Weather categories (with rough priors)
WEATHERS = ["Clear", "Hot", "Cold", "Rain", "Storm", "Snow", "Windy", "Fog"]
WEATHER_P = np.array([0.28, 0.12, 0.12, 0.18, 0.06, 0.05, 0.10, 0.09])

# ---------- Helpers ----------
def sample_lat_lon(n):
    lat = RNG.uniform(*LAT_RANGE, size=n)
    lon = RNG.uniform(*LON_RANGE, size=n)
    return lat, lon

def sample_altitude(n):
    """
    Mixture: plains (~0–500m), hills (~500–2000m), high mountains (2000–5500m).
    """
    comp = RNG.choice([0,1,2], size=n, p=[0.5, 0.35, 0.15])
    alt = np.empty(n, dtype=float)
    alt[comp==0] = RNG.uniform(0, 500, size=(comp==0).sum())
    alt[comp==1] = RNG.uniform(500, 2000, size=(comp==1).sum())
    alt[comp==2] = RNG.uniform(2000, 5500, size=(comp==2).sum())
    return alt

def sample_weather(n, altitude):
    """
    Slightly bias weather by altitude: more 'Snow' & 'Cold' at higher altitudes,
    more 'Hot' & 'Rain' at lower altitudes.
    """
    base = np.tile(WEATHER_P, (n,1))
    high = altitude >= 2500
    low  = altitude < 800

    # strengthen cold/snow at high altitude
    base[high, WEATHERS.index("Cold")] *= 1.6
    base[high, WEATHERS.index("Snow")] *= 2.0
    base[high, WEATHERS.index("Hot")]  *= 0.6
    base[high, WEATHERS.index("Rain")] *= 0.8

    # strengthen hot/rain at low altitude
    base[low, WEATHERS.index("Hot")]  *= 1.5
    base[low, WEATHERS.index("Rain")] *= 1.3
    base[low, WEATHERS.index("Snow")] *= 0.4
    base[low, WEATHERS.index("Cold")] *= 0.7

    # normalize rows
    base = base / base.sum(axis=1, keepdims=True)

    # categorical draw row-wise
    idx = [RNG.choice(len(WEATHERS), p=base[i]) for i in range(n)]
    return np.array([WEATHERS[i] for i in idx])

def sample_steps(n, activity_boost=None):
    """
    Log-normal-ish steps. Optionally boost by activity level.
    """
    mu, sigma = 8.7, 0.45   # controls scale
    steps = RNG.lognormal(mean=mu, sigma=sigma, size=n).astype(int)
    steps = np.clip(steps, 200, 40000)
    if activity_boost is not None:
        steps = (steps * (0.7 + 0.8*activity_boost)).astype(int)
    return steps

def sample_activity(n):
    # 0..1 with slight skew towards moderate activity
    base = np.clip(RNG.beta(2.0, 2.5, size=n), 0, 1)
    return base

def sample_past_incident(n):
    # low prevalence
    return RNG.binomial(1, 0.10, size=n)

# ---------- Physiology samplers (lightly conditioned on altitude & weather) ----------
def sample_spo2(n, altitude, weather):
    """
    Baseline ~97-99% at low alt; drops with altitude; small weather effects (Storm/Fog -> slight drop).
    """
    spo2 = RNG.normal(98.0, 1.0, size=n)
    spo2 -= np.clip((altitude - 1500) / 1000.0, 0, 6) * RNG.uniform(0.8, 1.5, size=n)  # altitude effect
    bad_w = np.isin(weather, ["Storm", "Fog"])
    spo2[bad_w] -= RNG.uniform(0.5, 1.0, size=bad_w.sum())
    return np.clip(spo2, 72, 100)

def sample_hr(n, altitude, weather, activity):
    """
    Baseline ~60-85 bpm; higher with activity; small increase with altitude & hot weather.
    """
    hr = RNG.normal(75, 10, size=n)
    hr += 35*activity
    hr += np.clip((altitude - 2500) / 1000.0, 0, 4) * RNG.uniform(2, 5, size=n)
    hot = (weather == "Hot")
    hr[hot] += RNG.uniform(3, 8, size=hot.sum())
    return np.clip(hr, 40, 200)

def sample_skin_temp(n, weather):
    """
    Skin temperature ~33-35C normally; Hot raises, Cold/Fog lowers slightly.
    """
    st = RNG.normal(33.5, 0.8, size=n)
    st[weather=="Hot"]  += RNG.uniform(0.8, 1.8, size=(weather=="Hot").sum())
    st[weather=="Cold"] -= RNG.uniform(0.5, 1.2, size=(weather=="Cold").sum())
    st[weather=="Fog"]  -= RNG.uniform(0.2, 0.6, size=(weather=="Fog").sum())
    # occasional fevers
    fever_mask = RNG.random(n) < 0.05
    st[fever_mask] += RNG.uniform(4.0, 6.0, size=fever_mask.sum())  # ~37.5-39.5+
    return np.clip(st, 30.0, 41.5)

def sample_bp(n, activity):
    """
    Systolic/diastolic with mild dependence on activity and random hypertension spikes.
    """
    sys = RNG.normal(118, 12, size=n) + 10*(activity - 0.5)
    dia = RNG.normal(76,  8, size=n) + 6*(activity - 0.5)

    # some hypertensive and hypotensive cases
    spike = RNG.random(n) < 0.08
    sys[spike] += RNG.uniform(25, 60, size=spike.sum())
    dia[spike] += RNG.uniform(10, 25, size=spike.sum())

    dip = RNG.random(n) < 0.03
    sys[dip]  -= RNG.uniform(20, 35, size=dip.sum())
    dia[dip]  -= RNG.uniform(10, 20, size=dip.sum())

    return np.clip(sys, 70, 220), np.clip(dia, 40, 140)

# ---------- Rule engine (aligned with your earlier thresholds) ----------
THRESHOLDS = {
    "hr": {"low_upper":110,"mod_upper":130,"high_upper":140,"low_lower":60,"mod_lower":50,"high_lower":45},
    "spo2": {"low":95,"mod":92,"high":88},
    "skin_temp": {"fever_low":37.8,"fever_high":38.5,"hypo_low":35.5,"hypo_high":35.0},
    "bp_sys": {"high1":140,"high2":160,"high3":180,"low1":90,"low2":80,"low3":70},
    "bp_dia": {"high1":90,"high2":100,"high3":110,"low1":60,"low2":50,"low3":45},
    "steps": {"very_low":2000,"low":400,"very_high":30000},
    "altitude_spo2": {"alt_high1":2500,"alt_high2":3000,"spo2_soft":94,"spo2_hard":92,"spo2_crit":88},
    "label_bands": [(0,2,"LOW"), (3,6,"MODERATE"), (7,11,"HIGH"), (12,99,"CRITICAL")]
}

def wearable_risk_score(hr_bpm=None, spo2_pct=None, skin_temp_c=None, cfg=THRESHOLDS):
    score = 0
    if hr_bpm is not None and not np.isnan(hr_bpm):
        hr = cfg["hr"]
        if hr_bpm > hr["high_upper"] or hr_bpm < hr["high_lower"]: score += 3
        elif hr_bpm > hr["mod_upper"] or hr_bpm < hr["mod_lower"]: score += 2
        elif hr_bpm > hr["low_upper"] or hr_bpm < hr["low_lower"]: score += 1
    if spo2_pct is not None and not np.isnan(spo2_pct):
        sp = cfg["spo2"]
        if spo2_pct < sp["high"]: score += 3
        elif spo2_pct < sp["mod"]: score += 2
        elif spo2_pct < sp["low"]: score += 1
    if skin_temp_c is not None and not np.isnan(skin_temp_c):
        st = cfg["skin_temp"]
        if skin_temp_c >= st["fever_high"]: score += 3
        elif skin_temp_c >= st["fever_low"]: score += 2
        elif skin_temp_c <= st["hypo_high"]: score += 2
        elif skin_temp_c <= st["hypo_low"]: score += 1
    return score

def map_total_to_label(total, bands):
    for lo, hi, lab in bands:
        if lo <= total <= hi:
            return lab
    return "LOW"

def rule_label_row(r):
    # Base score from vitals
    s = wearable_risk_score(r["hr_bpm"], r["spo2_pct"], r["skin_temp"])

    # Blood pressure penalties
    bp = THRESHOLDS
    sys = r["bloodpressure_systolic"]
    dia = r["bp_diastolic"]
    if not np.isnan(sys):
        if   sys >= bp["bp_sys"]["high3"]: s += 3
        elif sys >= bp["bp_sys"]["high2"]: s += 2
        elif sys >= bp["bp_sys"]["high1"]: s += 1
        elif sys <= bp["bp_sys"]["low3"]:  s += 3
        elif sys <= bp["bp_sys"]["low2"]:  s += 2
        elif sys <= bp["bp_sys"]["low1"]:  s += 1
    if not np.isnan(dia):
        if   dia >= bp["bp_dia"]["high3"]: s += 2
        elif dia >= bp["bp_dia"]["high2"]: s += 2
        elif dia >= bp["bp_dia"]["high1"]: s += 1
        elif dia <= bp["bp_dia"]["low3"]:  s += 2
        elif dia <= bp["bp_dia"]["low2"]:  s += 2
        elif dia <= bp["bp_dia"]["low1"]:  s += 1

    # Altitude + SpO2 interaction
    alt = r["altitude"]
    spo2 = r["spo2_pct"]
    as_ = THRESHOLDS["altitude_spo2"]
    if alt >= as_["alt_high2"] and spo2 < as_["spo2_hard"]:
        s += 3
        if spo2 < as_["spo2_crit"]:
            s += 1
    elif alt >= as_["alt_high1"] and spo2 < as_["spo2_soft"]:
        s += 2

    # Steps (too low or extreme)
    st_cfg = THRESHOLDS["steps"]
    steps = r["steps"]
    if steps <= st_cfg["very_low"]:
        s += 2
    elif steps <= 1000:
        s += 1
    elif steps >= st_cfg["very_high"]:
        s += 1

    # Past incident flag escalates risk
    if r["past_incident_flag"] == 1:
        s += 2

    # Weather condition influence
    w = r["weather_condition"]
    if w == "Storm":
        s += 2
    elif w in ("Rain","Snow","Fog"):
        s += 1
    elif w == "Hot":
        # if also high skin temp or high HR, add 1
        if (r["skin_temp"] >= 37.8) or (r["hr_bpm"] > 110):
            s += 1

    return map_total_to_label(int(s), THRESHOLDS["label_bands"])

# ---------- Generate data ----------
user_id = np.arange(1, N+1)

latitude, longitude = sample_lat_lon(N)
altitude = sample_altitude(N)
weather  = sample_weather(N, altitude)
activity = sample_activity(N)

steps    = sample_steps(N, activity_boost=activity)
spo2     = sample_spo2(N, altitude, weather)
hr       = sample_hr(N, altitude, weather, activity)
skin_t   = sample_skin_temp(N, weather)
bp_sys, bp_dia = sample_bp(N, activity)
past_inc = sample_past_incident(N)

# Assemble dataframe with requested columns
df = pd.DataFrame({
    "user_id": user_id,
    "hr_bpm": hr.round(0).astype(int),
    "spo2_pct": spo2.round(1),
    "skin_temp": skin_t.round(1),
    "bloodpressure_systolic": bp_sys.round(0).astype(int),
    "bp_diastolic": bp_dia.round(0).astype(int),     # <- use this; rename if you prefer "bp_distolic"
    "altitude": altitude.round(0).astype(int),
    "latitude": latitude.round(5),
    "longitude": longitude.round(5),
    "steps": steps.astype(int),
    "past_incident_flag": past_inc.astype(int),
    "weather_condition": weather
})

# Apply rule-based labeling
df["risk_label"] = df.apply(rule_label_row, axis=1)

# (Optional) quick sanity check distribution
print(df["risk_label"].value_counts())

# Save
out_path = "synthetic_risk_10k.csv"
df.to_csv(out_path, index=False)
print(f"[OK] Wrote {len(df):,} rows to {out_path}")
