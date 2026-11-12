# OTF → Strava

Uploads each [Orangetheory Fitness](https://www.orangetheory.com/) class to [Strava](https://www.strava.com/) as one FIT activity, built from the class telemetry: real heart-rate charts, treadmill pace and incline, rower power and stroke rate, and a lap per station.

This is an unofficial, self-hosted tool. It is **not affiliated with, endorsed by, or associated with Orangetheory Fitness or Strava.** Orangetheory and Strava are trademarks of their respective owners. It fetches your workout data with the community [`otf-api`](https://github.com/NodeJSmith/otf-api) library (also unofficial) and uploads through the official [Strava API](https://developers.strava.com/). You run it with your own accounts, and you must create [your own Strava API application](https://www.strava.com/settings/api).

## What it does

- **Run (treadmill)** for any class with tread data, otherwise **Workout**.
- Distance is treadmill distance only (rower meters are never added). Speed is belt speed on the tread and 0 off it, so Strava can treat off-tread time as not moving.
- Synthetic elevation from treadmill incline.
- Rower watts become power, and strokes/min become cadence, on row blocks only.
- One lap per station block (tread / row / floor), detected from the telemetry.
- Titles look like `OTF 2G · 6 splats · 2.47 mi tread · 700 m row`. The description includes zones, splat points, calories, and coach.

### 3G classes and average pace

On 3G classes — and any class with row or floor blocks — Strava’s **overall average pace looks slower than you actually ran**. The activity covers the whole class, including time off the treadmill when the belt is stopped, and Strava folds that into the overall pace. This is more noticeable on 3G because a larger share of the class is off the tread.

Use the **Tread lap splits** on the Strava activity for your true run pace. Each upload already includes this note in the activity description. Rower power and stroke rate show on the row laps.

## Deduping and skips

The sync is stateless. A class is skipped only if Strava already has an activity *this tool uploaded* (`external_id` `otf-<id>`) within five minutes of the class start. Other overlapping activities are not treated as duplicates: they are logged and left untouched.

```
python sync.py --dry-run --list-overlaps --days 60
```

lists non-sync activities that overlap your classes (useful before a backfill). If Strava rotates the refresh token, it is saved to `.env` locally; in GitHub Actions a warning asks you to update the secret. Classes with no heart-rate telemetry are skipped and retried on the next run; after 48 hours they produce a workflow warning. The tool never creates text-only or manual activities.

## Setup

Repo secrets (or a local `.env`):

- `OTF_EMAIL` and `OTF_PASSWORD` — your Orangetheory account
- `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, and `STRAVA_REFRESH_TOKEN` — from **your** Strava API application, with scope `activity:read_all,activity:write`

Do not reuse someone else’s Strava API credentials. Create an app at [https://www.strava.com/settings/api](https://www.strava.com/settings/api).

### Scheduled sync and public logs

A GitHub Actions workflow is included (`workflow_dispatch`). If you add a cron schedule, run it from a **private** repository or private fork. On a public repo, Actions logs are public and will include class times, titles, splat counts, and Strava activity IDs. Keep your secrets and your scheduled sync private.

## Local

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python sync.py --dry-run --days 30 --cache cache
```

That writes FIT files to `out/` and a report to `out/report.json`, with no Strava calls. Drop the `--dry-run` flag to upload.

## License

MIT
