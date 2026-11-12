import re
MI = 1609.344


def class_label(name: str) -> str:
    m = re.search(r"\b([123]G)\b", name or "")
    return m.group(1) if m else (name or "Class").replace("Orange ", "")


def title(w: dict, tread_m: float, row_m: float) -> str:
    parts = [f"OTF {class_label(w['otf_class'].get('name'))}"]
    sp = w.get("splat_points") or 0
    parts.append(f"{sp} splat" + ("" if sp == 1 else "s"))
    if tread_m: parts.append(f"{tread_m / MI:.2f} mi tread")
    if row_m: parts.append(f"{row_m:,.0f} m row")
    return " · ".join(parts)


def description(w: dict, blocks, tread_m, row_m, row_stats, mixed: bool) -> str:
    z = w.get("zone_time_minutes") or {}
    L = [f"{w['otf_class'].get('name')} with coach {w.get('coach') or '?'}"
         + (f" at {w['studio'].get('name')}" if w.get('studio') else ""),
         f"Splat points: {w.get('splat_points')} · Calories: {w.get('calories_burned')}",
         "Zones (min): " + " / ".join(f"{k} {z.get(k, 0)}" for k in ("gray", "blue", "green", "orange", "red"))]
    if tread_m:
        L.append(f"Tread: {tread_m / MI:.2f} mi")
    if row_m:
        L.append(f"Row: {row_m:,.0f} m" + (f" · avg {row_stats['w']:.0f} W · {row_stats['spm']:.0f} spm" if row_stats else ""))
    L.append("Blocks: " + ", ".join(f"{b.kind} {b.secs // 60}:{b.secs % 60:02d}" for b in blocks))
    if mixed:
        L.append("")
        L.append("Note: overall avg pace may include rower/floor time; use the Tread lap splits for true run pace. "
                 "Rower power/cadence are shown on the row laps (cadence is the rower stroke rate).")
    L.append("Synced from Orangetheory telemetry.")
    return "\n".join(L)
