"""Build a FIT activity from an OTF workout (our own implementation)."""
import datetime as dt
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.profile_type import (Event, EventType, FileType, Manufacturer, Sport, SubSport,
                                          LapTrigger, Activity)
from .segments import Block


def _ms(t: dt.datetime) -> int:
    return round(t.timestamp() * 1000)


def build_fit(start: dt.datetime, samples: list[dict], blocks: list[Block], has_tread: bool,
              total_calories: int | None) -> tuple[bytes, dict]:
    """Records every telemetry sample with the timer running the whole class (so HR is kept for floor/row).

    distance  = cumulative TREADMILL distance only (held flat off-tread, rower never added)
    speed     = treadmill belt speed on tread, 0 elsewhere (lets Strava's moving-time logic drop non-run time)
    altitude  = synthetic: integral of incline% * tread distance
    power/cadence = rower watts / strokes-per-min, only during row blocks
    """
    b = FitFileBuilder(auto_define=True, min_string_size=50)
    m = FileIdMessage(); m.type = FileType.ACTIVITY; m.manufacturer = Manufacturer.DEVELOPMENT.value
    m.product = 0; m.serial_number = 0x0F7A0001; m.time_created = _ms(start); b.add(m)
    e = EventMessage(); e.event = Event.TIMER; e.event_type = EventType.START; e.timestamp = _ms(start); b.add(e)

    dist = 0.0; alt = 0.0; last_tread = 0.0
    stats = {"records": 0, "hr": 0, "speed": 0, "power": 0, "cadence": 0}
    rec_by_t = []
    for s in samples:
        t = start + dt.timedelta(seconds=s["relative_timestamp"])
        r = RecordMessage(); r.timestamp = _ms(t)
        if s.get("hr"):
            r.heart_rate = int(s["hr"]); stats["hr"] += 1
        td, rd = s.get("tread_data"), s.get("row_data")
        if td:
            nd = float(td["agg_tread_distance"])
            if nd >= last_tread:
                alt += (nd - last_tread) * float(td["tread_incline"]) / 100.0
                dist += nd - last_tread
            last_tread = nd
            r.speed = float(td["tread_speed"]); stats["speed"] += 1
        else:
            r.speed = 0.0
        if rd:
            r.power = int(round(rd["row_pps"])); r.cadence = int(round(rd["row_spm"]))
            stats["power"] += 1; stats["cadence"] += 1
        else:
            # explicit zeros: otherwise Strava forward-fills the last rower values into tread/floor laps
            r.power = 0; r.cadence = 0
        if has_tread:
            r.distance = dist
            r.altitude = alt
        b.add(r); stats["records"] += 1
        rec_by_t.append((s["relative_timestamp"], dist, s.get("hr")))

    end_rel = blocks[-1].end if blocks else (samples[-1]["relative_timestamp"] if samples else 0)
    end = start + dt.timedelta(seconds=end_rel)

    def dist_at(sec):
        d = 0.0
        for t, dd, _ in rec_by_t:
            if t <= sec: d = dd
            else: break
        return d

    laps = []
    for blk in blocks:
        hrs = [h for t, _, h in rec_by_t if blk.start <= t < blk.end and h]
        lap = LapMessage()
        lap.timestamp = _ms(start + dt.timedelta(seconds=blk.end))
        lap.start_time = _ms(start + dt.timedelta(seconds=blk.start))
        lap.total_elapsed_time = float(blk.secs); lap.total_timer_time = float(blk.secs)
        d = dist_at(blk.end) - dist_at(blk.start)
        lap.total_distance = d
        lap.event = Event.LAP; lap.event_type = EventType.STOP; lap.lap_trigger = LapTrigger.MANUAL
        lap.sport = Sport.RUNNING if has_tread else Sport.TRAINING
        if hrs:
            lap.avg_heart_rate = round(sum(hrs) / len(hrs)); lap.max_heart_rate = max(hrs)
        if d and blk.secs:
            lap.avg_speed = d / blk.secs
        b.add(lap); laps.append((blk.kind, blk.secs, d))

    hrs = [h for *_, h in rec_by_t if h]
    s = SessionMessage()
    s.timestamp = _ms(end); s.start_time = _ms(start)
    s.total_elapsed_time = float(end_rel); s.total_timer_time = float(end_rel)
    s.total_distance = dist
    s.sport = Sport.RUNNING if has_tread else Sport.TRAINING
    s.sub_sport = SubSport.TREADMILL if has_tread else SubSport.GENERIC
    s.first_lap_index = 0; s.num_laps = len(blocks)
    s.event = Event.SESSION; s.event_type = EventType.STOP
    if hrs:
        s.avg_heart_rate = round(sum(hrs) / len(hrs)); s.max_heart_rate = max(hrs)
    if total_calories:
        s.total_calories = int(total_calories)
    if alt:
        s.total_ascent = int(round(alt))
    b.add(s)
    e = EventMessage(); e.event = Event.TIMER; e.event_type = EventType.STOP_ALL; e.timestamp = _ms(end); b.add(e)
    a = ActivityMessage(); a.timestamp = _ms(end); a.total_timer_time = float(end_rel); a.num_sessions = 1
    a.type = Activity.MANUAL; a.event = Event.ACTIVITY; a.event_type = EventType.STOP
    a.local_timestamp = int((end.astimezone().replace(tzinfo=None) - dt.datetime(1989, 12, 31)).total_seconds())
    b.add(a)
    stats.update(distance_m=dist, ascent_m=alt, laps=laps)
    return b.build().to_bytes(), stats
