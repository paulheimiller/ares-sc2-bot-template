"""Raw python-sc2 build isolation test (NO Ares framework).

Answers:
1. Can an SCV build a Barracks at all on AcropolisAIE?
2. Single-shot build vs rapid re-issue — does re-issuing kill the ghost?
3. What do placement/pathing grids look like around candidate spots?

Runs three configs sequentially:
  A) single-shot @ Ares' chosen spot (29.5, 132.5)
  B) single-shot @ python-sc2 find_placement spot
  C) rapid re-issue @ find_placement spot (mimics BuildingManager behavior)

Usage: .venv/bin/python raw_build_test.py
"""
import sys
from pathlib import Path

sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")

from sc2 import maps
from sc2.bot_ai import BotAI
from sc2.data import AIBuild, ActionResult, Difficulty, Race, Result
from sc2.ids.ability_id import AbilityId
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.ids.unit_typeid import UnitTypeId
from sc2.main import run_game
from sc2.player import Bot, Computer
from sc2.position import Point2
from sc2.unit_command import UnitCommand

ARES_SPOT = Point2((29.5, 132.5))


def dump_grid(ai, center: Point2, label: str, half: int = 6) -> None:
    pg = ai.game_info.placement_grid.data_numpy  # (H, W), 1 = placeable
    fg = ai.game_info.pathing_grid.data_numpy    # 1 = walkable
    cx, cy = int(round(center.x)), int(round(center.y))
    print(f"[GRID] --- {label} around tile ({cx},{cy}) ---", flush=True)
    for y in range(cy - half, cy + half + 1):
        rp = "".join("1" if pg[y][x] else "." for x in range(cx - half, cx + half + 1))
        rf = "".join("1" if fg[y][x] else "." for x in range(cx - half, cx + half + 1))
        mark = " <== build row" if y == cy else ""
        print(f"[GRID]   y={y:3d} P:{rp} F:{rf}{mark}", flush=True)
    xs = "".join(str((cx - half + i) % 10) for i in range(2 * half + 1))
    print(f"[GRID]        x:  {xs}", flush=True)


class RawBot(BotAI):
    def __init__(self, mode: str, spot=None):
        super().__init__()
        self.mode = mode
        self.forced_spot = spot
        self.scv = None
        self.scv_tag = None
        self.spot = None
        self.build_count = 0
        self.last_build_t = 0.0
        self._audited = set()
        self.init_workers = None
        self.phase = "walk_depot"
        self.phase_t = 0.0
        self.depot_spot = None
        self.barracks_spot = None
        self.init_depots = 0
        self.barracks_at = None
        self._grids_dumped = False
        self._ending = False

    async def _end(self) -> None:
        if self._ending:
            return
        self._ending = True
        try:
            await self._client.debug_leave()
        except Exception as e:
            print(f"[RAW] debug_leave failed: {e}", flush=True)

    async def _direct_build(self, unit, struct_type, spot, label):
        """Bypass BotAI.do batching: send one action, capture engine verdict."""
        if struct_type not in self._audited:
            self._audited.add(struct_type)
            ab = self.game_data.units[struct_type.value].creation_ability
            key = struct_type.name.lower().replace("_", "")
            alts = [
                (a.friendly_name, a.id)
                for a in self.game_data.abilities.values()
                if key in a.link_name.lower().replace("_", "")
            ]
            canon = None
            try:
                canon = TRAIN_INFO[UnitTypeId.SCV][struct_type]["ability"]
            except Exception as e:
                canon = f"<none {e}>"
            print(
                f"[AUDIT] {struct_type.name}: creation={ab.friendly_name} "
                f"id={ab.id} exact={ab.exact_id} canon={canon}",
                flush=True,
            )
            print(f"[AUDIT] candidates={alts[:12]}", flush=True)
            uab = self._unit_abilities.get(unit.tag)
            if uab is not None:
                abid = ab.id
                related = sorted(
                    a.name for a in uab if struct_type.name.upper() in a.name
                )
                print(
                    f"[AUDIT] runtime@{str(unit.tag)[-4:]} n={len(uab)} "
                    f"has_{struct_type.name.lower()}={abid in uab} related={related}",
                    flush=True,
                )
        ability_id = self.game_data.units[struct_type.value].creation_ability.id
        uc = UnitCommand(ability_id, unit, target=spot, queue=False)
        res = await self.client.actions([uc], return_successes=True)
        r = res[0] if res else None
        print(f"[{label}] t={self.time:.1f} {struct_type.name} result={r!r}", flush=True)
        return r

    async def on_start(self) -> None:
        cc = self.townhalls.first
        ms = self.game_info.map_size
        print(
            f"[RAW] mode={self.mode} map={ms.width}x{ms.height} "
            f"forced_spot={self.forced_spot} start={self.start_location} cc@{cc.position}",
            flush=True,
        )

    async def on_step(self, iteration: int) -> None:
        if self.time < 8.0:
            return

        if self.scv is None:
            idle = self.workers.idle
            self.scv = idle.first if idle.exists else self.workers.first
            if self.forced_spot is not None:
                # Map rotates per game; pick the mirror of Ares' spot closest
                # to our actual base so we test the same local offset.
                W = self.game_info.map_size.width
                H = self.game_info.map_size.height
                f = self.forced_spot
                candidates = [
                    f,
                    Point2((W - f.x, f.y)),
                    Point2((f.x, H - f.y)),
                    Point2((W - f.x, H - f.y)),
                ]
                self.spot = min(
                    candidates, key=lambda c: c.distance_to(self.start_location)
                )
            else:
                ptype = (
                    UnitTypeId.COMMANDCENTER
                    if self.mode == "directcc"
                    else UnitTypeId.SUPPLYDEPOT
                    if self.mode == "directdepot"
                    else UnitTypeId.BARRACKS
                )
                prad = {"directcc": 10, "directdepot": 6}.get(self.mode, 8)
                self.spot = await self.find_placement(
                    ptype, self.start_location.towards(self.game_info.map_center, prad)
                )
            if self.mode == "depotthenbarracks":
                self.depot_spot = await self.find_placement(
                    UnitTypeId.SUPPLYDEPOT,
                    self.start_location.towards(self.game_info.map_center, 6),
                )
                self.barracks_spot = await self.find_placement(
                    UnitTypeId.BARRACKS,
                    self.depot_spot.towards(self.game_info.map_center, 8),
                )
                self.spot = self.depot_spot
                self.init_depots = self.structures(UnitTypeId.SUPPLYDEPOT).amount
                print(
                    f"[RAW-DT] init_depots={self.init_depots} "
                    f"depot@{self.depot_spot} barr@{self.barracks_spot}",
                    flush=True,
                )
            print(f"[RAW] scv tag={self.scv.tag} spot={self.spot}", flush=True)
            self.scv_tag = self.scv.tag
            self.init_workers = self.workers.amount
            if not self._grids_dumped:
                dump_grid(self, self.spot, f"mode={self.mode} spot")
                if self.forced_spot is not None:
                    dump_grid(self, self.start_location, "start (CC)")
                self._grids_dumped = True
            self.scv.move(self.spot)
            return

        d = self.scv.position.distance_to(self.spot)

        # Fresh resolution of our worker by tag — the stale self.scv object
        # freezes at its grab-time position/orders (suspected root cause).
        matched = self.workers.filter(lambda u: u.tag == self.scv_tag)
        fw = matched.first if matched.exists else None

        if self.mode in ("freshwalk", "freshpure"):
            if fw is not None:
                fd = fw.position.distance_to(self.spot)
                if self.mode == "freshwalk":
                    if self.build_count == 0 and fd <= 0.9 and self.can_afford(
                        UnitTypeId.BARRACKS
                    ):
                        r = fw.build(UnitTypeId.BARRACKS, self.spot)
                        self.build_count += 1
                        print(
                            f"[RAW-FW] build issued t={self.time:.1f} ret={r!r} "
                            f"orders={[o.ability.id.name for o in fw.orders]}",
                            flush=True,
                        )
                    elif fd > 0.8:
                        fw.stop()
                        fw.move(self.spot)
                else:  # freshpure
                    if self.build_count == 0 and self.time >= 9.0 and self.can_afford(
                        UnitTypeId.BARRACKS
                    ):
                        r = fw.build(UnitTypeId.BARRACKS, self.spot)
                        self.build_count += 1
                        print(
                            f"[RAW-FP] build issued t={self.time:.1f} ret={r!r} "
                            f"d={fd:.2f} orders={[o.ability.id.name for o in fw.orders]}",
                            flush=True,
                        )
        elif self.mode in ("directbarracks", "directcc", "directrepeat", "directdepot"):
            # Fresh walk + direct engine action with captured verdict.
            if fw is not None:
                fd = fw.position.distance_to(self.spot)
                struct = (
                    UnitTypeId.COMMANDCENTER
                    if self.mode == "directcc"
                    else UnitTypeId.SUPPLYDEPOT
                    if self.mode == "directdepot"
                    else UnitTypeId.BARRACKS
                )
                if fd > 0.9:
                    fw.stop()
                    fw.move(self.spot)
                elif (
                    self.build_count < 5
                    and self.time >= 10.0
                    and self.time - self.last_build_t >= 4.0
                    and self.can_afford(struct)
                ):
                    lbl = {
                        "directbarracks": "RAW-DB",
                        "directcc": "RAW-DC",
                        "directrepeat": "RAW-DR",
                        "directdepot": "RAW-DD",
                    }[self.mode]
                    await self._direct_build(fw, struct, self.spot, lbl)
                    self.build_count += 1
                    self.last_build_t = self.time
        elif self.mode == "canonbarracks":
            # Canonical SCV build ability from TRAIN_INFO (TERRANBUILD_BARRACKS).
            if fw is not None:
                fd = fw.position.distance_to(self.spot)
                if fd > 0.9:
                    fw.stop()
                    fw.move(self.spot)
                elif (
                    self.build_count < 5
                    and self.time >= 10.0
                    and self.time - self.last_build_t >= 4.0
                    and self.can_afford(UnitTypeId.BARRACKS)
                ):
                    abid = TRAIN_INFO[UnitTypeId.SCV][UnitTypeId.BARRACKS]["ability"]
                    uc = UnitCommand(abid, fw, target=self.spot, queue=False)
                    res = await self.client.actions([uc], return_successes=True)
                    r = res[0] if res else None
                    print(
                        f"[RAW-CB] t={self.time:.1f} {abid} result={r!r} d={fd:.2f}",
                        flush=True,
                    )
                    self.build_count += 1
                    self.last_build_t = self.time
        elif self.mode == "depotthenbarracks":
            # Full chain: depot -> wait for completion -> barracks.
            if fw is None:
                return
            if self.phase == "walk_depot":
                dd = fw.position.distance_to(self.depot_spot)
                if dd > 0.9:
                    fw.stop()
                    fw.move(self.depot_spot)
                elif self.time >= 10.0 and self.can_afford(
                    UnitTypeId.SUPPLYDEPOT
                ):
                    await self._direct_build(
                        fw, UnitTypeId.SUPPLYDEPOT, self.depot_spot, "RAW-DT1"
                    )
                    self.phase = "wait_depot"
                    self.phase_t = self.time
            elif self.phase == "wait_depot":
                depots = self.structures(UnitTypeId.SUPPLYDEPOT)
                building = [x for x in depots if x.build_progress < 1.0]
                if building:
                    if int(self.time) % 4 < 1:
                        print(
                            f"[RAW-DT] depot prog={building[0].build_progress:.2f} "
                            f"n={depots.amount} init={self.init_depots}",
                            flush=True,
                        )
                elif depots.amount > self.init_depots:
                    self.phase = "walk_barracks"
                    self.phase_t = self.time
                    print(
                        f"[RAW-DT] DEPOT COMPLETE t={self.time:.1f} "
                        f"-> barracks @ {self.barracks_spot}",
                        flush=True,
                    )
            elif self.phase == "walk_barracks":
                bd = fw.position.distance_to(self.barracks_spot)
                if bd > 0.9:
                    fw.stop()
                    fw.move(self.barracks_spot)
                elif (
                    self.time - self.phase_t >= 1.0
                    and self.can_afford(UnitTypeId.BARRACKS)
                ):
                    r = await self._direct_build(
                        fw, UnitTypeId.BARRACKS, self.barracks_spot, "RAW-DT2"
                    )
                    self.phase_t = self.time
                    if r == ActionResult.Success:
                        self.phase = "done"
        elif self.mode == "smartbarracks":
            # SMART-click the spot: engine decides move vs build.
            if fw is not None:
                fd = fw.position.distance_to(self.spot)
                if fd > 0.9:
                    fw.stop()
                    fw.move(self.spot)
                elif (
                    self.build_count < 5
                    and self.time >= 10.0
                    and self.time - self.last_build_t >= 4.0
                ):
                    uc = UnitCommand(AbilityId.SMART, fw, target=self.spot, queue=False)
                    res = await self.client.actions([uc], return_successes=True)
                    r = res[0] if res else None
                    print(
                        f"[RAW-SMART] t={self.time:.1f} result={r!r} d={fd:.2f}",
                        flush=True,
                    )
                    self.build_count += 1
                    self.last_build_t = self.time
        elif self.mode == "trainscv":
            # Control: does a TRAIN ability work through the same pipeline?
            cc = self.townhalls.first
            if (
                self.build_count < 3
                and self.time >= 12.0
                and self.time - self.last_build_t >= 5.0
                and self.can_afford(UnitTypeId.SCV)
            ):
                ab = self.game_data.units[UnitTypeId.SCV.value].creation_ability
                uc = UnitCommand(ab.id, cc, target=None, queue=False)
                res = await self.client.actions([uc], return_successes=True)
                r = res[0] if res else None
                print(
                    f"[RAW-TS] t={self.time:.1f} train SCV via {ab.friendly_name} result={r!r}",
                    flush=True,
                )
                self.build_count += 1
                self.last_build_t = self.time
        elif self.mode == "pure":
            # Let python-sc2's build() queue its own move+build; no is_idle gate.
            if self.build_count == 0 and self.time >= 9.0 and self.can_afford(
                UnitTypeId.BARRACKS
            ):
                r = self.scv.build(UnitTypeId.BARRACKS, self.spot)
                self.build_count += 1
                print(
                    f"[RAW-PURE] build issued t={self.time:.1f} ret={r!r} "
                    f"cargo={self.scv.cargo_used}/{self.scv.cargo_max} "
                    f"orders={[o.ability.id.name for o in self.scv.orders]}",
                    flush=True,
                )
        elif self.mode == "stopmove":
            # stop() clears the hidden harvest order queue, then walk + build.
            if self.build_count == 0 and d <= 0.9 and self.can_afford(
                UnitTypeId.BARRACKS
            ):
                r = self.scv.build(UnitTypeId.BARRACKS, self.spot)
                self.build_count += 1
                print(f"[RAW-SM] build issued t={self.time:.1f} ret={r!r}", flush=True)
            elif d > 0.8:
                self.scv.stop()
                self.scv.move(self.spot)
        else:  # single / repeat (original behavior, kept for reference)
            if d > 0.8:
                if self.time < 45.0:
                    pre = [o.ability.id.name for o in self.scv.orders]
                    r = self.scv.move(self.spot)
                    post = [o.ability.id.name for o in self.scv.orders]
                    print(
                        f"[RAW-T] t={self.time:.2f} pos=({self.scv.position.x:.1f},"
                        f"{self.scv.position.y:.1f}) pre={pre} ret={r!r} "
                        f"n_actions={len(self.actions)} post={post}",
                        flush=True,
                    )
                else:
                    self.scv.move(self.spot)
            else:
                if self.mode == "single":
                    if self.build_count == 0 and self.scv.is_idle and self.can_afford(
                        UnitTypeId.BARRACKS
                    ):
                        self.scv.build(UnitTypeId.BARRACKS, self.spot)
                        self.build_count += 1
                        print(f"[RAW] SINGLE build issued t={self.time:.1f}", flush=True)
                else:  # repeat
                    if self.scv.is_idle and self.can_afford(UnitTypeId.BARRACKS):
                        self.scv.build(UnitTypeId.BARRACKS, self.spot)
                        self.build_count += 1

        barracks = self.structures(UnitTypeId.BARRACKS)
        if barracks.exists and self.barracks_at is None:
            self.barracks_at = self.time
            print(f"[RAW] BARRACKS APPEARED t={self.time:.1f}", flush=True)
        if self.mode == "directcc" and self.barracks_at is None:
            ccs = self.structures(UnitTypeId.COMMANDCENTER)
            if ccs.amount > 1:
                self.barracks_at = self.time
                print(f"[RAW] SECOND CC APPEARED t={self.time:.1f}", flush=True)
        if self.mode == "directdepot" and self.barracks_at is None:
            depots = self.structures(UnitTypeId.SUPPLYDEPOT)
            if depots.amount > 1:
                self.barracks_at = self.time
                print(f"[RAW] DEPOT APPEARED t={self.time:.1f}", flush=True)
        if (
            self.mode == "trainscv"
            and self.barracks_at is None
            and self.init_workers
            and self.workers.amount > self.init_workers
        ):
            self.barracks_at = self.time
            print(f"[RAW] NEW SCV APPEARED t={self.time:.1f}", flush=True)

        if iteration % 22 == 0:  # ~1s
            bprog = (
                f"{barracks[0].build_progress:.2f}" if barracks.exists else "-"
            )
            orders = [o.ability.id.name for o in self.scv.orders]
            cargo = f"{self.scv.cargo_used}/{self.scv.cargo_max}"
            wsn = "; ".join(
                f"#{str(w.tag)[-4:]}@({w.position.x:.0f},{w.position.y:.0f})"
                + (":" + w.orders[0].ability.id.name[:8] if w.orders else ":IDLE")
                for w in list(self.workers)[:8]
            )
            print(
                f"[RAW] t={self.time:6.1f} scv@({self.scv.position.x:.1f},"
                f"{self.scv.position.y:.1f}) d={d:.2f} orders={orders} "
                f"cargo={cargo} min={self.minerals:4.0f} builds={self.build_count} "
                f"barr_prog={bprog}",
                flush=True,
            )
            if fw is not None:
                fd = fw.position.distance_to(self.spot)
                folds = [o.ability.id.name for o in fw.orders]
                print(
                    f"[RAW-X] t={self.time:6.1f} fresh@({fw.position.x:.1f},"
                    f"{fw.position.y:.1f}) d={fd:.2f} idle={fw.is_idle} orders={folds}",
                    flush=True,
                )
            print(f"[RAW-W] {wsn}", flush=True)

        if self.time > 170.0:
            verdict = (
                f"WON_BUILD_AT_{self.barracks_at:.1f}"
                if self.barracks_at
                else "NO_BARRACKS"
            )
            print(f"[RAW-END] mode={self.mode} {verdict} builds={self.build_count}", flush=True)
            await self._end()


CONFIGS = [
    ("A_single_ares_spot", "single", ARES_SPOT),
    ("B_single_find_placement", "single", None),
    ("C_repeat_find_placement", "repeat", None),
    ("D_pure_find_placement", "pure", None),
    ("E_pure_ares_spot", "pure", ARES_SPOT),
    ("F_stopmove_ares_spot", "stopmove", ARES_SPOT),
    ("G_freshwalk_ares_spot", "freshwalk", ARES_SPOT),
    ("H_freshpure_find_placement", "freshpure", None),
    ("J_directbarracks_fp", "directbarracks", None),
    ("K_directcc_fp", "directcc", None),
    ("L_directrepeat_ares", "directrepeat", ARES_SPOT),
    ("M_smartbarracks_fp", "smartbarracks", None),
    ("N_directdepot_fp", "directdepot", None),
    ("O_trainscv_control", "trainscv", None),
    ("P_canonbarracks_fp", "canonbarracks", None),
    ("Q_depotthenbarracks_fp", "depotthenbarracks", None),
]


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for name, mode, spot in CONFIGS:
        if only and not name.startswith(only):
            continue
        print(f"\n================ CONFIG {name} ================", flush=True)
        bot = RawBot(mode, spot)
        players = [
            Bot(Race.Terran, bot, "RawBot"),
            Computer(Race.Terran, Difficulty.Easy, ai_build=AIBuild.Macro),
        ]
        try:
            result = run_game(maps.get("AcropolisAIE"), players, realtime=False)
            print(f"[RAW-RESULT] {name}: game_result={result}", flush=True)
        except Exception as e:
            print(f"[RAW-ERROR] {name}: {type(e).__name__}: {e}", flush=True)
    print("[RAW] ALL DONE", flush=True)


if __name__ == "__main__":
    main()
