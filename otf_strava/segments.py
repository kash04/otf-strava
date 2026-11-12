"""Detect station blocks (tread / row / floor) from OTF telemetry samples."""
from dataclasses import dataclass

MERGE_GAP_S = 60   # a dropout shorter than this between two blocks of the same kind is bridged
MIN_BLOCK_S = 45   # blocks shorter than this are absorbed into the previous block


@dataclass
class Block:
    kind: str      # "tread" | "row" | "floor"
    start: int     # relative seconds
    end: int       # relative seconds (exclusive)

    @property
    def secs(self) -> int:
        return self.end - self.start


def sample_kind(s) -> str:
    if s.get("tread_data"):
        return "tread"
    if s.get("row_data"):
        return "row"
    return "floor"


def detect_blocks(samples: list[dict], class_end: int | None = None) -> list[Block]:
    if not samples:
        return []
    raw: list[Block] = []
    for i, s in enumerate(samples):
        t = s["relative_timestamp"]
        nxt = samples[i + 1]["relative_timestamp"] if i + 1 < len(samples) else (class_end or t + 3)
        k = sample_kind(s)
        if raw and raw[-1].kind == k:
            raw[-1].end = nxt
        else:
            raw.append(Block(k, t, nxt))
    # bridge short floor dropouts between same-kind blocks (sensor gaps, belt stops)
    out: list[Block] = []
    for b in raw:
        if (len(out) >= 2 and out[-1].kind == "floor" and out[-1].secs < MERGE_GAP_S
                and out[-2].kind == b.kind):
            out.pop()
            out[-1].end = b.end
        elif out and out[-1].kind == b.kind:
            out[-1].end = b.end
        else:
            out.append(b)
    # absorb tiny blocks into their predecessor
    res: list[Block] = []
    for b in out:
        if res and b.secs < MIN_BLOCK_S:
            res[-1].end = b.end
        elif res and res[-1].kind == b.kind:
            res[-1].end = b.end
        else:
            res.append(b)
    if len(res) > 1 and res[0].secs < MIN_BLOCK_S:
        res[1].start = res[0].start
        res.pop(0)
    return res
