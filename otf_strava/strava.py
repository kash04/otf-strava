"""Minimal Strava API client (refresh-token auth, list, upload)."""
import datetime as dt, time, requests

API = "https://www.strava.com/api/v3"


class Strava:
    def __init__(self, client_id, client_secret, refresh_token):
        r = requests.post("https://www.strava.com/oauth/token", data={
            "client_id": client_id, "client_secret": client_secret,
            "grant_type": "refresh_token", "refresh_token": refresh_token}, timeout=30)
        r.raise_for_status()
        j = r.json()
        self.h = {"Authorization": f"Bearer {j['access_token']}"}
        self.rotated = j.get("refresh_token") and j["refresh_token"] != refresh_token
        self.new_refresh_token = j.get("refresh_token")

    def get(self, path, **params):
        r = requests.get(f"{API}{path}", headers=self.h, params=params, timeout=30)
        r.raise_for_status(); return r.json()

    def update(self, activity_id, **fields):
        r = requests.put(f"{API}/activities/{activity_id}", headers=self.h, json=fields, timeout=30)
        r.raise_for_status(); return r.json()

    def activities_between(self, after: dt.datetime, before: dt.datetime) -> list[dict]:
        out, page = [], 1
        while True:
            r = requests.get(f"{API}/athlete/activities", headers=self.h, timeout=30, params={
                "after": int(after.timestamp()), "before": int(before.timestamp()), "per_page": 100, "page": page})
            r.raise_for_status(); batch = r.json(); out += batch
            if len(batch) < 100: return out
            page += 1

    def upload_fit(self, data: bytes, external_id: str, name: str, description: str) -> dict:
        r = requests.post(f"{API}/uploads", headers=self.h, timeout=60,
                          files={"file": (f"{external_id}.fit", data)},
                          data={"data_type": "fit", "external_id": external_id, "name": name,
                                "description": description})
        r.raise_for_status(); up = r.json()
        for _ in range(30):
            if up.get("activity_id") or up.get("error"): return up
            time.sleep(2)
            up = requests.get(f"{API}/uploads/{up['id']}", headers=self.h, timeout=30).json()
        return up
