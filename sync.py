"""OTF -> Strava sync. Stateless: dedupes against Strava itself.

  python sync.py --dry-run --days 30      # fetch from OTF, write FIT files to out/, no Strava calls
  python sync.py --days 7                 # real sync (needs STRAVA_* env vars)
"""
import argparse, datetime as dt, json, logging, os, sys
from pathlib import Path
from zoneinfo import ZoneInfo

from otf_strava.segments import detect_blocks
from otf_strava.fitwriter import build_fit
from otf_strava.describe import title, description

CT = ZoneInfo("America/Chicago")
GIVE_UP_HOURS = 48          # missing telemetry after this long -> warn in the workflow log
OUT = Path("out")
log = logging.getLogger("otf-strava")


def load_workouts(days: int, cache: Path | None):
    if cache and cache.is_dir() and any(cache.glob("*.json")):
        return [json.loads(p.read_text()) for p in cache.glob("*.json")]
    from otf_api import Otf, OtfUser
    otf = Otf(user=OtfUser(os.environ["OTF_EMAIL"].strip().lower(), os.environ["OTF_PASSWORD"]))
    start = (dt.datetime.now(CT) - dt.timedelta(days=days)).date()
    out = []
    for w in otf.workouts.get_workouts(start_date=start, max_data_points=1000):
        d = w.model_dump(mode="json")
        d["_telemetry_full"] = [t.model_dump(mode="json") for t in w.telemetry.telemetry] if w.telemetry else []
        out.append(d)
        if cache:
            cache.mkdir(exist_ok=True)
            (cache / f"{w.performance_summary_id}.json").write_text(json.dumps(d, default=str))
    return out


def class_start(w) -> dt.datetime:
    tel = w.get("telemetry") or {}
    if tel.get("class_start_time"):
        return dt.datetime.fromisoformat(tel["class_start_time"].replace("Z", "+00:00"))
    tz = ZoneInfo((w.get("studio") or {}).get("time_zone") or "America/Chicago")
    return dt.datetime.fromisoformat(w["otf_class"]["starts_at"]).replace(tzinfo=tz)


MARKER = "Synced from Orangetheory telemetry."


def is_ours(x: dict) -> bool:
    """An activity this sync uploaded: external_id otf-<id>[.fit] (set on upload) or our description marker."""
    return (x.get("external_id") or "").startswith("otf-") or MARKER in (x.get("description") or "")


def overlaps(x, start, end) -> bool:
    xs = dt.datetime.fromisoformat(x["start_date"].replace("Z", "+00:00"))
    return xs < end and xs + dt.timedelta(seconds=x.get("elapsed_time", 0)) > start


def save_rotated_token(tok):
    if os.environ.get("GITHUB_ACTIONS"):
        print("::warning::Strava returned a new refresh token; update the STRAVA_REFRESH_TOKEN secret "
              "(run locally with --list-overlaps to capture it)")
        return
    p = Path(".env")
    if p.exists():
        import re
        p.write_text(re.sub(r"^STRAVA_REFRESH_TOKEN=.*$", f"STRAVA_REFRESH_TOKEN={tok}", p.read_text(), flags=re.M))
        p.chmod(0o600)
        log.info("Saved rotated Strava refresh token to .env")


def process(w):
    samples = sorted(w.get("_telemetry_full") or [], key=lambda s: s["relative_timestamp"])
    start = class_start(w)
    has_hr = any(s.get("hr") for s in samples)
    has_tread = any(s.get("tread_data") for s in samples)
    has_row = any(s.get("row_data") for s in samples)
    info = {"id": w.get("performance_summary_id"), "name": w["otf_class"].get("name"),
            "start_ct": start.astimezone(CT).strftime("%Y-%m-%d %H:%M %Z"), "hr": has_hr,
            "tread": has_tread, "row": has_row, "samples": len(samples),
            "window_s": (w.get("telemetry") or {}).get("window_size")}
    if not samples or not has_hr:
        return start, info, None
    blocks = detect_blocks(samples)
    row_m = max((s["row_data"]["agg_row_distance"] for s in samples if s.get("row_data")), default=0)
    rs = [s["row_data"] for s in samples if s.get("row_data") and s["row_data"]["row_spm"] > 0]
    row_stats = {"w": sum(r["row_pps"] for r in rs) / len(rs), "spm": sum(r["row_spm"] for r in rs) / len(rs)} if rs else None
    data, st = build_fit(start, samples, blocks, has_tread, w.get("calories_burned"))
    mixed = has_tread and any(b.kind != "tread" for b in blocks)
    info.update(blocks=[(b.kind, b.start, b.end) for b in blocks], tread_m=round(st["distance_m"]),
                row_m=row_m, ascent_m=round(st["ascent_m"], 1), sport="Run (treadmill)" if has_tread else "Workout")
    info["title"] = title(w, st["distance_m"], row_m)
    info["description"] = description(w, blocks, st["distance_m"], row_m, row_stats, mixed)
    return start, info, data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--since", help="sync classes on/after this date (YYYY-MM-DD, Central); overrides --days")
    ap.add_argument("--only", help="only this class date (YYYY-MM-DD, Central)")
    ap.add_argument("--list-overlaps", action="store_true",
                    help="read Strava, list non-sync activities overlapping each class, upload nothing")
    ap.add_argument("--cache", type=Path, help="read/write raw OTF JSON here (local debugging)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)
    try:
        from dotenv import load_dotenv; load_dotenv(Path(__file__).with_name(".env"))
    except ImportError:
        pass
    OUT.mkdir(exist_ok=True)
    strava = None
    if not a.dry_run or a.list_overlaps:
        from otf_strava.strava import Strava
        strava = Strava(os.environ["STRAVA_CLIENT_ID"], os.environ["STRAVA_CLIENT_SECRET"], os.environ["STRAVA_REFRESH_TOKEN"])
        if strava.rotated:
            save_rotated_token(strava.new_refresh_token)
    now = dt.datetime.now(dt.timezone.utc)
    report = []
    days = a.days
    if a.since:
        days = (dt.datetime.now(CT).date() - dt.date.fromisoformat(a.since)).days + 1
    for w in sorted(load_workouts(days, a.cache), key=lambda w: w["otf_class"]["starts_at"]):
        if a.since and w["otf_class"]["starts_at"][:10] < a.since:
            continue
        if a.only and not w["otf_class"]["starts_at"].startswith(a.only):
            continue
        start, info, data = process(w)
        report.append(info)
        if data is None:
            age_h = (now - start).total_seconds() / 3600
            msg = f"{info['start_ct']} {info['name']}: no HR telemetry yet"
            if age_h > GIVE_UP_HOURS:
                print(f"::warning::{msg} after {age_h:.0f} h, not uploaded (check OTF app)")
            else:
                log.info(msg + "; will retry on a later run")
            continue
        ext = f"otf-{info['id']}"
        (OUT / f"{ext}.fit").write_bytes(data)
        if strava is None:
            continue
        end = start + dt.timedelta(seconds=info["blocks"][-1][2])
        near = strava.activities_between(start - dt.timedelta(hours=3), end + dt.timedelta(hours=1))
        mine = [x for x in near if is_ours(x)
                and abs((dt.datetime.fromisoformat(x["start_date"].replace("Z", "+00:00")) - start).total_seconds()) < 300]
        others = [x for x in near if not is_ours(x) and overlaps(x, start, end)]
        if a.list_overlaps:
            for x in others:
                log.info(f"{info['start_ct']} overlapping non-sync activity {x['id']} '{x.get('name')}' ({x.get('sport_type')})")
            continue
        if mine:
            log.info(f"{info['start_ct']} already synced (activity {mine[0]['id']}), skipping"); continue
        for x in others:
            log.info(f"{info['start_ct']} note: overlaps non-sync activity {x['id']} '{x.get('name')}' (left untouched)")
        up = strava.upload_fit(data, ext, info["title"], info["description"])
        log.info(f"{info['start_ct']} upload -> {up.get('activity_id') or up.get('error') or up.get('status')}")
        info["activity_id"] = up.get("activity_id")
    (OUT / "report.json").write_text(json.dumps(report, indent=1))
    for r in report:
        log.info(f"{r['start_ct']} | {r['name']} | hr={r['hr']} tread={r['tread']} row={r['row']} "
                 f"n={r['samples']} win={r['window_s']}s | {r.get('title', 'SKIPPED')}")


if __name__ == "__main__":
    sys.exit(main())
