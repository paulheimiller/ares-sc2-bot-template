"""
Main bot file for the Terran TankBot.

This bot implements coordinated army movement with leapfrog tank behavior.
"""

import os
import time
from pathlib import Path
from typing import Optional

import numpy as np
from ares import AresBot
from ares.consts import ALL_STRUCTURES, ID, TARGET, UnitRole
from ares.managers.manager_mediator import ManagerMediator
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from .army_group_behavior import CoordinatedArmyGroup
from .movement_logger import MovementLogger, _derive_state


class MyBot(AresBot):
    # Units handed over to the coordinated army group (marines + tanks first,
    # vikings for air support)
    ARMY_UNIT_TYPES = {
        UnitTypeId.MARINE,
        UnitTypeId.SIEGETANK,
        UnitTypeId.VIKINGFIGHTER,
    }

    def __init__(self, game_step_override: Optional[int] = None):
        """Initiate custom bot

        Parameters
        ----------
        game_step_override :
            If provided, set the game_step to this value regardless of how it was
            specified elsewhere
        """
        super().__init__(game_step_override)
        self.army_group: CoordinatedArmyGroup | None = None
        self.mvlog: MovementLogger | None = None
        # --- Barracks isolation probe state ---
        # While active, MyBot takes over driving of the step-0 tracked worker
        # (BuildingManager._handle_construction_orders is neutered) so we can
        # tell whether "SCV -> build Barracks" works at all on this map.
        self._probe_active = True
        self._probe_builds_issued = 0
        self._probe_built_at: Optional[float] = None
        self._probe_tag: Optional[int] = None
        self._dev_ending = False
        self._mining = None  # persistent Mining behavior, re-registered each frame

    async def on_start(self) -> None:
        await super(MyBot, self).on_start()
        # v18: register the standard Ares Mining behavior — without it, probes
        # re-registered to gas by ResourceManager never get a fresh gather()
        # order and keep their stale mineral orders (gas flatline v14-v17)
        from ares.behaviors.macro import Mining

        # v25: BehaviorExecutioner.execute() CLEARS its list after each run, so a
        # behavior registered once in on_start only survives ONE frame. Upstream
        # docs register Mining() inside on_step every frame. We keep ONE persistent
        # instance (preserves locked_action_tags / debug tick state) and re-add it
        # to the per-frame queue from on_step below.
        self._mining = Mining(workers_per_gas=4)
        import os as _os_dbg_reg
        if _os_dbg_reg.environ.get("ARES_DBG_MINING") == "1":
            print(
                "[DBG-MG] Mining behavior created (workers_per_gas=4)",
                flush=True,
            )
        ts = time.strftime("%Y%m%d_%H%M%S")
        logdir = Path(__file__).resolve().parent.parent / "game_logs"
        self.mvlog = MovementLogger(logdir / f"movement_{ts}.csv")
        print(f"[MV] logging unit movement to {self.mvlog.csv_path}", flush=True)
        if self._probe_active:
            bm = self.manager_hub.building_manager
            bm._orig_hco = bm._handle_construction_orders
            print("[PROBE] Barracks isolation probe ARMED (step 0, t<240s)", flush=True)

    def _probe_drive(self, iteration: int) -> None:
        """Take over driving of the step 0-1 tracked workers; log every 5 ticks."""
        bo = self.build_order_runner
        bt = self.mediator.get_building_tracker_dict
        if not bt or bo.build_step not in (0, 1):
            return
        for wt, info in list(bt.items()):
            w = self.unit_tag_dict.get(wt)
            tgt = info[TARGET]
            tgt_pos = tgt.position if hasattr(tgt, "position") else Point2(tgt)
            sid = info[ID]
            if not w:
                continue
            self._probe_tag = wt
            d = w.position.distance_to(tgt_pos)
            carried = w.is_carrying_resource
            tech = self.tech_requirement_progress(sid)
            if carried:
                w.return_resource()
            elif d > 1.0:
                w.move(tgt_pos)
            elif self.can_afford(sid) and tech >= 0.99 and (
                not w.is_constructing_scv or w.is_idle
            ):
                w.build(sid, tgt_pos)
                self._probe_builds_issued += 1
            if iteration % 5 == 0:
                orders = [o.ability.id.name for o in w.orders]
                print(
                    f"[PROBE] t={self.time:6.1f} {sid.name} w@({w.position.x:.1f},"
                    f"{w.position.y:.1f}) tgt=({tgt_pos.x:.1f},{tgt_pos.y:.1f}) "
                    f"d={d:.2f} state={_derive_state(w)} orders={orders} "
                    f"carry={carried} min={self.minerals:.0f} tech={tech:.2f} "
                    f"builds_issued={self._probe_builds_issued}",
                    flush=True,
                )

    async def on_step(self, iteration: int) -> None:
        # Optional early stop for fast probe iterations
        _mt = os.environ.get("DEV_MAXTIME")
        if _mt and not self._dev_ending and self.time > float(_mt) and self.time < 5000:
            self._dev_ending = True
            try:
                await self._client.debug_leave()
            except Exception as _e:
                print(f"[DEV] maxtime end failed: {_e}", flush=True)

        await super(MyBot, self).on_step(iteration)

        # --- Per-frame macro behavior queue ---
        # BehaviorExecutioner.execute() runs the queue then CLEARS it, so every
        # persistent behavior must be re-registered each iteration (upstream docs
        # pattern: register_behavior(Mining()) inside on_step). One shared instance
        # keeps locked_action_tags / debug state across frames.
        if self._mining is not None:
            self.behavior_executioner.register_behavior(self._mining)

        # --- Movement logger (VersusAI-style headless monitor) ---
        if self.mvlog is not None:
            self.mvlog.sample(self, iteration)

        # --- Barracks isolation probe ---
        if self._probe_active:
            bo = self.build_order_runner
            # Appearance check lives here (not only in _probe_drive) so a
            # 1-frame gap between ghost appearing and step advancing can't
            # lose it.
            if (
                self._probe_built_at is None
                and any(s.type_id == UnitTypeId.BARRACKS for s in self.structures)
            ):
                self._probe_built_at = self.time
                print(
                    f"[PROBE] *** BARRACKS APPEARED at t={self.time:.1f} "
                    f"(builds_issued={self._probe_builds_issued}) ***",
                    flush=True,
                )
            probe_on = bo.build_step in (0, 1) and self.time < 240.0
            bm = self.manager_hub.building_manager
            if probe_on:
                if getattr(bm, "_orig_hco", None) is None:
                    bm._orig_hco = bm._handle_construction_orders
                bm._handle_construction_orders = lambda: None
                self._probe_drive(iteration)
            else:
                if getattr(bm, "_orig_hco", None) is not None:
                    bm._handle_construction_orders = bm._orig_hco
                    print(
                        f"[PROBE-END] t={self.time:.1f} step={bo.build_step} "
                        f"barracks_at={self._probe_built_at} "
                        f"builds_issued={self._probe_builds_issued}",
                        flush=True,
                    )
                    self._probe_active = False

        # --- TEMP DEBUG: periodic build/macro status dump ---
        if iteration % 60 == 0:
            try:
                from collections import Counter
                bo = self.build_order_runner
                nsteps = len(bo.build_order)
                idx = bo.build_step
                cur = bo.build_order[idx].command.name if idx < nsteps else "DONE"
                c = Counter(u.type_id.name for u in self.all_own_units if u.is_structure)
                army = sum(1 for u in self.all_own_units if u.is_active and not u.is_structure)
                marines = len(self.units(UnitTypeId.MARINE))
                # v21: count sieged tanks too (SIEGETANKSIEGED) — defense
                # mode holds them in siege, which hid them from this counter.
                # NOTE: self.units is a property returning a Units object;
                # call it once per type (v21b: 2-arg call raised
                # "Units.__call__() takes 2 positional arguments").
                tanks = len(self.units(UnitTypeId.SIEGETANK)) + len(
                    self.units(UnitTypeId.SIEGETANKSIEGED)
                )
                vikings = len(self.units(UnitTypeId.VIKINGFIGHTER))
                print(
                    f"[DBG] t={self.time:6.1f} sup={self.supply_used}/{self.supply_cap} "
                    f"min={self.minerals:4.0f} gas={self.vespene:3.0f} scv={len(self.workers):2d} "
                    f"step={idx:2d}/{nsteps} ({cur}) army={army:2d} "
                    f"mar={marines} tank={tanks} vik={vikings} structs={dict(c)}",
                    flush=True,
                )
                # --- v27h: ENEMY STATE DUMP. v27g showed our army bleeding at
                # dist~31 with threats=15-22 but we never saw WHAT was out
                # there or where it stood relative to both bases. ---
                try:
                    ec = Counter(u.type_id.name for u in self.enemy_units)
                    es = Counter(u.type_id.name for u in self.structures)
                    nfoe = len(self.enemy_units)
                    fpos = ""
                    gs = [u.position for u in self.enemy_units if not u.is_flying]
                    if gs:
                        cx = sum(p.x for p in gs) / len(gs)
                        cy = sum(p.y for p in gs) / len(gs)
                        fpos = f" gnd_c=({cx:.0f},{cy:.0f})"
                    # v27h: structure POSITIONS — v27h's camp froze at
                    # (49.6,118.1); we need to see what building sat there.
                    spos = ",".join(
                        f"{s.type_id.name[:6]}@{s.position.x:.0f},{s.position.y:.0f}"
                        for s in sorted(
                            self.structures, key=lambda s: s.position.length
                        )[:12]
                    )
                    print(
                        f"[FOE] t={self.time:6.1f} n={nfoe:2d} {dict(ec)} "
                        f"structs={dict(es)}{fpos} pos=[{spos}]",
                        flush=True,
                    )
                except Exception as _fe:
                    print(f"[FOE] err {_fe}", flush=True)
                # --- WORKER ROLE DUMP (gas-stall diagnosis; v10+) ---
                try:
                    tag2role = {}
                    for _r, _tags in self.mediator.get_unit_role_dict.items():
                        for _t in _tags:
                            tag2role[_t] = _r[:5] if isinstance(_r, str) else _r.name[:5]
                    gdict = self.mediator.get_worker_to_vespene_dict
                    mcount = len(self.mediator.get_worker_to_mineral_patch_dict)
                    scv_line = " ".join(
                        f"{(_t % 65536):04x}:{tag2role.get(_t, '???')}"
                        for _t in sorted(self.workers.tags)
                    )
                    print(
                        f"[DBG-W] gasreg={[f'{t % 65536:04x}' for t in gdict]} "
                        f"minreg={mcount} | {scv_line}",
                        flush=True,
                    )
                except Exception as _we:
                    print(f"[DBG-W] err {_we}", flush=True)
                # --- REFINERY DEEP DUMP (v15 gas flatline diagnosis) ---
                try:
                    from sc2.ids.unit_typeid import UnitTypeId as _UTT
                    refs = self.units(_UTT.REFINERY)
                    rinfo = []
                    for r in refs:
                        nreg = sum(1 for g in gdict.values() if g == r.tag)
                        rinfo.append(
                            f"ref@({r.position.x:.0f},{r.position.y:.0f}) "
                            f"ready={int(r.is_ready)} pool={r.vespene_contents:.0f} nreg={nreg}"
                        )
                    pinfo = []
                    for wt, gt in list(gdict.items())[:4]:
                        wu = self.unit_tag_dict.get(wt)
                        if wu is not None:
                            try:
                                o0 = str(wu.orders[0].ability_id.name) if wu.orders else "-"
                            except Exception:
                                o0 = "?"
                            try:
                                tp = f"tp({wu.order_target_position.x:.0f},{wu.order_target_position.y:.0f})" if wu.order_target_position else "tp(-)"
                            except Exception:
                                tp = "tp?"
                            try:
                                ms = str(wu.state.mine_state).split(".")[-1]
                            except Exception:
                                ms = "?"
                            pinfo.append(
                                f"w{wt % 65536:04x}@({wu.position.x:.0f},{wu.position.y:.0f}) "
                                f"{o0} {tp} mine={ms} carry={int(wu.is_carrying_resource)}"
                            )
                        else:
                            pinfo.append(f"w{wt % 65536:04x}=DEAD")
                    print(f"[DBG-R] {' | '.join(rinfo) or 'NO_REF'} || {', '.join(pinfo)}", flush=True)
                except Exception as _re:
                    print(f"[DBG-R] err {_re}", flush=True)
                # --- R2: every ref/gyser structure vs manager's gas_buildings ---
                try:
                    gs = [
                        f"{s.type_id.name}@({s.position.x:.0f},{s.position.y:.0f}) "
                        f"p={s.build_progress:.2f} pool={getattr(s, 'vespene_contents', -1):.0f}"
                        for s in self.structures
                        if any(k in s.type_id.name for k in ("REF", "GEYSER"))
                    ]
                    gb = [
                        f"{g.type_id.name}@({g.position.x:.0f},{g.position.y:.0f}) r={int(g.is_ready)}"
                        for g in self.gas_buildings
                    ]
                    print(f"[DBG-R2] structs={gs} || mgr={gb}", flush=True)
                except Exception as _r2e:
                    print(f"[DBG-R2] err {_r2e}", flush=True)
                # deeper probe of the CURRENT step's gate + worker + placement
                if idx < nsteps and iteration % 240 == 0:
                    st = bo.build_order[idx]
                    sc_ok = bool(st.start_condition())
                    gate = self.supply_used >= st.start_at_supply
                    cbp = bo.current_build_position
                    w = self.mediator.select_worker(
                        target_position=cbp, force_close=True,
                        select_persistent_builder=True, only_select_persistent_builder=False,
                    )
                    pos = (
                        await bo.get_position(st.command, st.target)
                        if isinstance(st.command, UnitTypeId)
                        and st.command in ALL_STRUCTURES
                        else "(unit-step)"
                    )
                    pb = self.mediator.get_units_from_role(role=UnitRole.PERSISTENT_BUILDER)
                    bt = self.mediator.get_building_tracker_dict
                    print(
                        f"[DBG-BO] step{idx}({st.command.name}): cond={sc_ok} "
                        f"gate={gate}(need {st.start_at_supply},have {self.supply_used}) "
                        f"cbp={cbp} worker={'Y' if w else 'N'} pos={pos} "
                        f"persist={len(pb)} tracker_keys={list(bt.keys())[:3]}",
                        flush=True,
                    )
                    # --- OBSERVE each tracked building worker (no perturbation) ---
                    from ares.consts import TARGET as _TGT, ID as _ID
                    from sc2.position import Point2 as _P2
                    under_c = [
                        f"{u.type_id.name}:{u.build_progress:.2f}@{u.position}"
                        for u in self.all_own_units
                        if u.is_structure and u.build_progress < 1.0
                    ]
                    print(f"[DBG-UC] under_construction={under_c}", flush=True)
                    for wt, info in list(self.mediator.get_building_tracker_dict.items())[:4]:
                        try:
                            import asyncio
                            wu = self.unit_tag_dict.get(wt)
                            tgt = info[_TGT]
                            tgt_pos = tgt.position if hasattr(tgt, "position") else _P2(tgt)
                            d = wu.position.distance_to(tgt_pos) if wu else -1.0
                            cpl = self.mediator.can_place_structure(position=tgt_pos, structure_type=info[_ID]) if wu else None
                            cc_dists = [round(c.position.distance_to(tgt_pos), 2) for c in self.townhalls]
                            def _ords(u):
                                return [o.ability.id.name if (o and o.ability) else str(o) for o in (u.orders if u else [])]
                            orders_before = _ords(wu)
                            ret = None
                            if wu and d < 0.6:
                                r = wu.build(info[_ID], tgt_pos)
                                if asyncio.iscoroutine(r):
                                    r = await r
                                ret = r
                            orders_after = _ords(wu)
                            roles = [str(r) for r, tags in self.mediator.get_unit_role_dict.items() if wt in tags]
                            print(
                                f"[DBG-WORKER] tag={wt} id={info[_ID].name} tgt={tgt_pos} dist={d:.2f} "
                                f"idle={wu.is_idle if wu else '?'} constr={wu.is_constructing_scv if wu else '?'} "
                                f"roles={roles} canplace={cpl} cc={cc_dists} ordB={orders_before} ret={ret} ordA={orders_after}",
                                flush=True,
                            )
                        except Exception as _we:
                            print(f"[DBG-WORKER] err {_we}", flush=True)
            except Exception as _e:
                print(f"[DBG] err {_e}", flush=True)
        # --- END DEBUG ---

        # Assign all army units to the control group role so the coordinated
        # army group has command of them (sieged tanks keep their tag/role)
        assigned_tags = self.mediator.get_unit_role_dict[UnitRole.CONTROL_GROUP_ONE]
        for unit in self.all_own_units.filter(
            lambda u: u.type_id in self.ARMY_UNIT_TYPES
        ):
            if unit.tag not in assigned_tags:
                self.mediator.assign_role(tag=unit.tag, role=UnitRole.CONTROL_GROUP_ONE)

        # Initialize army group behavior on first step
        if self.army_group is None:
            # Get the ground grid for pathfinding through choke points
            grid: np.ndarray = self.mediator.get_ground_grid
            # Target the enemy start location
            target = self.enemy_start_locations[0] if self.enemy_start_locations else self.game_info.map_center
            self.army_group = CoordinatedArmyGroup(target, grid)
            print(f"Army group initialized with target: {target}")

        # Register and execute army group behavior every frame
        if self.army_group is not None:
            self.army_group.execute(self, self.config, self.mediator)

    async def on_end(self, result) -> None:
        await super(MyBot, self).on_end(result)
        if self.mvlog is not None:
            self.mvlog.close()
