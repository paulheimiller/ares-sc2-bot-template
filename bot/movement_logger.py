"""Headless unit-movement monitor (VersusAI renderer equivalent).

VersusAI's ``sc2/renderer.py`` draws a live pyglet map view of unit positions.
This module gives the same diagnostic power headless: it samples every own
unit on a fixed cadence, writes a CSV trace, and flags units that were
ordered to move/attack/build but barely displaced ("stuck").

Usage in MyBot::

    self.mvlog = MovementLogger(csv_path)   # in on_start
    self.mvlog.sample(self, iteration)      # in on_step
    self.mvlog.close()                      # in on_end
"""
from __future__ import annotations

import csv
from collections import Counter, deque
from pathlib import Path

SAMPLE_EVERY = 10          # behavior ticks between samples (~1s game time at gs=2)
STUCK_WINDOW = 6           # samples kept per unit for stuck detection
STUCK_MIN_DIST = 2.0       # tiles; less displacement than this over the window => stuck
STUCK_RELOG_SECS = 15.0    # min seconds between repeat prints for the same tag

# First-order ability prefixes meaning the unit should be displacing.
# BUILD_* excluded on purpose: an SCV building stands still for ~85s.
MOTION_PREFIXES = (
    "MOVE_",
    "ATTACK_",        # ATTACK_MOVE / ATTACK_*
    "CARRY",          # CARGO/medivac-ish + generic carry
    "RETURN_RESOURCE",
    "HARVEST",        # mining loop counts as motion (SCV walks patches)
    "GATHER",
)


def _derive_state(u) -> str:
    """Derive a state string from the unit's first order (this python-sc2
    build has no Unit.state property; order.ability is an AbilityData whose
    .id is the AbilityId enum)."""
    try:
        if u.orders:
            return u.orders[0].ability.id.name
    except Exception:
        pass
    return "IDLE"


class MovementLogger:
    """Sample own-unit positions, write CSV, detect stuck movers."""

    def __init__(self, csv_path):
        self.csv_path = Path(csv_path)
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.csv_path, "w", newline="")
        self._w = csv.writer(self._fh)
        self._w.writerow(
            ["sample", "t", "tag", "type", "x", "y", "state", "health"]
        )
        self._hist: dict[int, deque] = {}  # tag -> deque[(t, x, y)]
        self._last_stuck_log: dict[int, float] = {}
        self.stuck_events: list[tuple] = []
        self.samples = 0
        self.max_units = 0

    def sample(self, ai, iteration: int) -> None:
        if iteration % SAMPLE_EVERY != 0:
            return
        self.samples += 1
        t = ai.time
        units = list(ai.all_own_units)
        self.max_units = max(self.max_units, len(units))

        for u in units:
            st = _derive_state(u)
            self._w.writerow(
                [
                    self.samples,
                    f"{t:.1f}",
                    u.tag,
                    u.type_id.name,
                    f"{u.position.x:.2f}",
                    f"{u.position.y:.2f}",
                    st,
                    f"{u.health:.0f}",
                ]
            )

            h = self._hist.setdefault(u.tag, deque(maxlen=STUCK_WINDOW))
            h.append((t, u.position.x, u.position.y))

            if len(h) == STUCK_WINDOW and st.startswith(MOTION_PREFIXES):
                dt = t - h[0][0]
                if dt > 3.0:
                    dx = u.position.x - h[0][1]
                    dy = u.position.y - h[0][2]
                    moved = (dx * dx + dy * dy) ** 0.5
                    if moved < STUCK_MIN_DIST:
                        if t - self._last_stuck_log.get(u.tag, -99.0) > STUCK_RELOG_SECS:
                            self.stuck_events.append(
                                (t, u.type_id.name, u.tag, st, round(moved, 2))
                            )
                            print(
                                f"[MV] t={t:6.1f} STUCK {u.type_id.name}#{u.tag} "
                                f"@({u.position.x:.1f},{u.position.y:.1f}) state={st} "
                                f"moved={moved:.2f}/{dt:.0f}s",
                                flush=True,
                            )
                        self._last_stuck_log[u.tag] = t

        alive = {u.tag for u in units}
        for tag in [k for k in self._hist if k not in alive]:
            del self._hist[tag]

    def close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass
        by_type = Counter(e[1] for e in self.stuck_events)
        worst = sorted(self.stuck_events, key=lambda e: -e[4])[:5]
        print(
            f"[MV-SUMMARY] samples={self.samples} peak_units={self.max_units} "
            f"stuck_events={len(self.stuck_events)} by_type={dict(by_type)} "
            f"csv={self.csv_path}",
            flush=True,
        )
        for e in worst:
            print(
                f"[MV-SUMMARY] event t={e[0]:.1f} {e[1]}#{e[2]} {e[3]} moved={e[4]}",
                flush=True,
            )
