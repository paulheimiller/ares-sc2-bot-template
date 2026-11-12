"""
Coordinated Army Group Behavior for Terran forces.

Implements formation movement with Marines, Tanks, and Vikings:
- Tanks: Alternating leapfrog movement with half going siege mode between moves
- Marines: Moving 2 tiles from tank center, then holding position
- Vikings: Centered directly above tanks

This version uses PathGroupToTarget for proper navigation through choke points.
"""

from typing import Set

import numpy as np
from ares.consts import UnitRole
from ares.managers.manager_mediator import ManagerMediator
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.units import Units

from ares.behaviors.combat.group import PathGroupToTarget


class CoordinatedArmyGroup:
    """
    Manages coordinated movement of an army group with Marines, Tanks, and Vikings.

    The behavior implements:
    - Leapfrog tank movement: tanks move incrementally 2 tiles at a time, alternating groups
      Each group that finishes moving goes into siege mode, then the other group moves
    - Marines: stay 2 tiles from tank center, supporting the formation
    - Vikings: positioned above the tank formation for air support
    - Choke point navigation: uses PathGroupToTarget for grid-based pathfinding
    """

    # v27f: 2 → 4. With the state machine fixed (v27e), each cycle now issues
    # real move orders; a 2-tile hop meant the centroid parked within ~2 of
    # the front target and the ratchet barely advanced (v27e: +3.4 tiles in
    # 500 s). 4-tile hops + the arrival boost give steady creep.
    MOVE_DISTANCE = 4.0   # Tiles each group advances per leapfrog step
    # v27: 2 → 6. At 2 tiles, marines stopped exactly where the tanks had to
    # cross (both targets = center + dir*2) and clogged the east gate; the
    # whole formation shuffled in a 4-tile blob for 100+ s (dist frozen at
    # 144.9 in v26). Marines are the clearing element: 6 tiles ahead.
    MARINE_DISTANCE = 6.0  # ADVANCE: marines hover this far ahead of tank center
    VIKING_ALTITUDE = 5.0  # Vikings positioned this distance north of tanks

    # Defense mode (v20): hold & siege when threatened near own base
    DEFENSE_RADIUS = 20.0       # formation within this of start location => defend
    THREAT_RADIUS = 28.0        # visible enemies within this trigger defense/engage
    VIKING_ENGAGE_RANGE = 12.0  # vikings pick fights out to this range
    # v27: enemy close to the BASE itself triggers DEFEND even when the
    # formation has advanced — in v26 the push killed SCVs for 40 s while
    # threats=0 because the camp sat 10 tiles east of the CC.
    STRUCTURE_THREAT_RADIUS = 25.0
    # v21b: 2 → 5. In v21 all 5 marines died in ONE 5s window during wave 1
    # (threats=13): at offset 2 they stood in the frontline instead of behind
    # the tank line. Offset 5 keeps them behind sieged tanks while their own
    # 5-tile range still catches slip-throughs.
    MARINE_REAR_OFFSET = 5.0    # defense: marines hover this far behind tank line

    # v27i: within this distance of the target point, abandon the ratchet
    # and converge directly on the nearest enemy CC (see _assault_base).
    # v27j: 45 → 50 — start the closing phase earlier; the camp at dist~33
    # was still fighting through turret range when our base got raided.
    ASSAULT_DISTANCE = 50.0

    # Timing constants (behavior frames; ares default game_step=2 ≈ 11 fps)
    # v27: 40→56 / 56→72. v26's tight windows left queued sieges unfinished
    # at switch time, so groups re-entered "move" still walking and lost
    # progress every cycle.
    UNSIEGE_FRAMES = 56   # ~5 s to complete unsiege animation
    MOVE_SIEGE_FRAMES = 72  # ~6.5 s to cover 2 tiles + complete siege animation

    def __init__(self, target: Point2, grid: np.ndarray) -> None:
        """
        Parameters
        ----------
        target : Point2
            Enemy location the army marches toward.
        grid : np.ndarray
            Ground grid for pathfinding through choke points.
        """
        self.target = target
        self.grid = grid

        # Leapfrog state machine:
        #   "move"    – issue move+queue_siege to active group at frame 0
        #   "unsiege" – issue unsiege to active group at frame 0, wait, then "move"
        # Transitions: move →(MOVE_SIEGE_FRAMES)→ switch groups → unsiege if needed, else move
        self.tank_state = "move"
        self.frames_since_state_change = 0

        self.active_tank_group = 0
        self.tank_group_0: Set[int] = set()
        self.tank_group_1: Set[int] = set()
        self.tanks_divided = False

        self.last_tank_center = None
        self.path_behavior_registered = False

        # v27: front-line ratchet. The formation's furthest advance along the
        # axis toward the enemy only ever increases; each cycle both groups
        # march to (furthest + MOVE_DISTANCE). Kills the v26 oscillation where
        # the camp shuffled in place at the gate for 100+ s.
        self.anchor_start: Point2 | None = None
        self.furthest_proj: float = 0.0

    def execute(self, ai, config, mediator: ManagerMediator) -> bool:
        """Execute coordinated army movement each frame."""
        # Get army units from the mediator using the role we assigned them to
        army_units = mediator.get_units_from_role(role=UnitRole.CONTROL_GROUP_ONE)
        
        if not army_units.amount:
            return False

        # Separate units by type
        tanks = army_units.filter(
            lambda u: u.type_id in [UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED]
        )
        marines = army_units.filter(lambda u: u.type_id == UnitTypeId.MARINE)
        vikings = army_units.filter(lambda u: u.type_id == UnitTypeId.VIKINGFIGHTER)

        # Calculate tank center
        if tanks.amount > 0:
            tank_center = tanks.center
        elif marines.amount > 0:
            tank_center = marines.center
        else:
            tank_center = army_units.center

        # Threats near the formation (visible enemies, ground or air)
        threats = ai.enemy_units.filter(
            lambda u: u.is_active
            and u.is_visible
            and u.position.distance_to(tank_center) < self.THREAT_RADIUS
        )
        # v27: threats at the base itself — enemy within STRUCTURE_THREAT_RADIUS
        # of start location defends even when the formation has advanced.
        base_threats = ai.enemy_units.filter(
            lambda u: u.is_active
            and u.is_visible
            and u.position.distance_to(ai.start_location) < self.STRUCTURE_THREAT_RADIUS
        )
        defending = (
            (threats.amount > 0 and tank_center.distance_to(ai.start_location) < self.DEFENSE_RADIUS)
            or base_threats.amount > 0
        )

        # Periodic status print (every ~5 seconds at game_step=2)
        if self.frames_since_state_change % 55 == 0:
            dist = tank_center.distance_to(self.target)
            print(
                f"[Army] dist={dist:.1f} state={self.tank_state} group={self.active_tank_group} "
                f"tanks={tanks.amount} marines={marines.amount} vikings={vikings.amount} "
                f"threats={threats.amount} base_thr={base_threats.amount} "
                f"anchor={self.furthest_proj:.0f} mode={'DEFEND' if defending else 'ADVANCE'}"
            )

        # Divide tanks into two groups on first execution — and RE-SPLIT
        # whenever the live tank set changes (v27f: the one-shot split at
        # first-tank left every late spawner unassigned; v27e ran 500 s with
        # "Group 1: 0 tanks" because both tanks landed in Group 0).
        live_tags = {t.tag for t in tanks}
        if not self.tanks_divided or live_tags != (self.tank_group_0 | self.tank_group_1):
            self._divide_tanks_into_groups(tanks)

        if defending:
            # v20: hold position — siege all tanks, marines behind the line,
            # vikings pick off the nearest threats (no leapfrog creep)
            # v27c: face formation threats if any, else base threats (the new
            # STRUCTURE_THREAT_RADIUS trigger can fire with an EMPTY formation
            # threat set → centroid divide-by-zero in v27b)
            hold_threats = threats if threats.amount > 0 else base_threats
            self._hold_defense(tanks, marines, tank_center, hold_threats)
        else:
            # v27i: CLOSE-RANGE DIRECT ASSAULT. The ratchet (leapfrog creep)
            # stalls when it parks against the enemy home perimeter — v27h
            # sat at (49.6,118.1) for ~1500 s bleeding against turrets while
            # the enemy rebuilt its army. Within ASSAULT_DISTANCE of the
            # target point, converge tanks+marines straight onto the nearest
            # enemy CC (siege tanks auto-siege on attack(building)).
            dist_t = tank_center.distance_to(self.target)
            cc = self._nearest_enemy_cc(ai, tank_center)
            if cc is not None and dist_t < self.ASSAULT_DISTANCE:
                self._assault_base(tanks, marines, cc)
            else:
                # Move tanks with leapfrog pattern (BEFORE incrementing counter)
                self._move_tanks_leapfrog(tanks, tank_center, ai, mediator)
                # Move marines relative to tank center (v27g: pass dist so
                # they tuck behind the tank line near the enemy base)
                self._move_marines(marines, tank_center, dist_t)
            # v27j: prove the CC lookup works (v27i no-op'd 800 s silently)
            if self.frames_since_state_change % 55 == 0:
                ccs = "none" if cc is None else f"@({cc.position.x:.0f},{cc.position.y:.0f})"
                print(
                    f"[CCLOOKUP] dist={dist_t:.1f} cc={ccs} "
                    f"{'ASSAULT' if (cc is not None and dist_t < self.ASSAULT_DISTANCE) else 'ratchet'}",
                    flush=True,
                )

        # Increment frame counter AFTER all movement logic
        self.frames_since_state_change += 1

        # Move/engage vikings above tank center
        self._move_vikings(vikings, tank_center, threats, ai)

        self.last_tank_center = tank_center
        return True

    def _divide_tanks_into_groups(self, tanks: Units) -> None:
        """Divide tanks into two groups for alternating movement."""
        tank_list = list(tanks)
        group_size = len(tank_list) // 2 if len(tank_list) > 1 else 1

        self.tank_group_0 = {tank.tag for tank in tank_list[:group_size]}
        self.tank_group_1 = {tank.tag for tank in tank_list[group_size:]}
        self.tanks_divided = True

        print(f"Tank groups formed: Group 0: {len(self.tank_group_0)} tanks, Group 1: {len(self.tank_group_1)} tanks")

    def _hold_defense(
        self,
        tanks: Units,
        marines: Units,
        tank_center: Point2,
        threats: Units,
    ) -> None:
        """Hold position near own base: siege all tanks, marines behind line.

        Tanks stay put (no leapfrog) so sieged damage is sustained; marines
        attack-move to a point behind the tank line toward own side so they
        engage anything that slips past. Vikings are handled by _move_vikings.
        """
        # face the threat centroid (v27c: guard against an empty set — a
        # caller can pass base_threats that vanish between filter and call)
        if threats.amount > 0:
            tc = Point2(
                (
                    sum(u.position.x for u in threats) / threats.amount,
                    sum(u.position.y for u in threats) / threats.amount,
                )
            )
            face = tc - tank_center
            if face.length < 0.1:
                face = Point2((0.0, 1.0))
            else:
                face = face.normalized
        else:
            face = Point2((0.0, 1.0))

        # 1) siege any unsieged tank (idempotent per frame)
        for t in tanks:
            if t.type_id == UnitTypeId.SIEGETANK:
                t(AbilityId.SIEGEMODE_SIEGEMODE)

        # 2) marines hover behind the tank line, attack-moving so they engage
        rear = tank_center - face * self.MARINE_REAR_OFFSET
        for m in marines:
            if m.position.distance_to(rear) > 1.5:
                m.attack(rear)

    def _move_tanks_leapfrog(
        self, tanks: Units, tank_center: Point2, ai, mediator: ManagerMediator
    ) -> None:
        """
        Leapfrog state machine: groups alternate between moving and sieging.

        States
        ------
        "move"    : Issue move+queue_siege once at frame 0. After MOVE_SIEGE_FRAMES,
                    switch to the other group. Skip "unsiege" if that group is already
                    unsieged (e.g. first cycle for group 1).
        "unsiege" : Issue unsiege once at frame 0. After UNSIEGE_FRAMES, transition
                    to "move" so the group can advance.

        Choke Point Navigation:
        Uses PathGroupToTarget behavior for grid-based pathfinding that properly
        navigates through narrow passages and choke points.
        """
        if tanks.amount == 0:
            return

        # Stop when close enough to target
        if tank_center.distance_to(self.target) < 3.0:
            return

        move_direction = self.target - tank_center
        if move_direction.length < 0.1:
            return
        move_direction = move_direction.normalized

        # v27: front-line ratchet — the furthest advance along the enemy axis
        # only increases; each cycle both groups march to (furthest + 2 tiles).
        # Fixes v26's in-place oscillation at the east gate.
        if self.anchor_start is None:
            # NOTE: this sc2api build's Point2 takes ONE tuple arg, not two
            self.anchor_start = Point2((tank_center.x, tank_center.y))
        axis = self.target - self.anchor_start
        if axis.length > 0.1:
            axis = axis.normalized
        else:
            axis = move_direction
        # v27d: manual dot — this sc2api build's Point2 has NO .dot()
        # (v27c crashed here); axis is normalized so proj = signed advance
        _dx = tank_center.x - self.anchor_start.x
        _dy = tank_center.y - self.anchor_start.y
        proj = _dx * axis.x + _dy * axis.y
        self.furthest_proj = max(self.furthest_proj, proj)
        front_target = self.anchor_start + axis * (self.furthest_proj + self.MOVE_DISTANCE)

        # v27f: arrival boost — when any tank reaches the front target, nudge
        # the ratchet forward so the next cycle has a NEW spot to march to.
        # Pure centroid projection stalls when tanks park at the front (v27e:
        # anchor frozen at 3.4 for 500 s).
        # v27h: double the boost within 35 tiles of the enemy base — v27g's
        # camp sat at dist~31 for ~500 s bleeding against home defense; we
        # need to ROLL the base, not siege-camp in turret range.
        if any(t.position.distance_to(front_target) < 2.5 for t in tanks):
            boost = 2.0 if tank_center.distance_to(self.target) < 35.0 else 1.0
            self.furthest_proj += boost
            front_target = self.anchor_start + axis * (
                self.furthest_proj + self.MOVE_DISTANCE
            )

        # v27e: STATE TRANSITIONS FIRST — the old order (issue-block before
        # transitions) meant the transition frame reset counter to 0 AFTER the
        # issue-block had already run, so frame 0 never fired again: tanks got
        # move orders exactly ONCE per game and never unsieged (v27d showed
        # 108 transitions, 0 target prints).
        if self.tank_state == "move" and self.frames_since_state_change >= self.MOVE_SIEGE_FRAMES:
            next_group = 1 - self.active_tank_group
            next_tags = self.tank_group_0 if next_group == 0 else self.tank_group_1
            next_has_sieged = any(
                t.type_id == UnitTypeId.SIEGETANKSIEGED
                for t in tanks if t.tag in next_tags
            )
            self.active_tank_group = next_group
            self.tank_state = "unsiege" if next_has_sieged else "move"
            self.frames_since_state_change = 0
            print(f"[Tank] → Group {next_group}, state={self.tank_state}")

        elif self.tank_state == "unsiege" and self.frames_since_state_change >= self.UNSIEGE_FRAMES:
            self.tank_state = "move"
            self.frames_since_state_change = 0
            print(f"[Tank] Group {self.active_tank_group}: unsiege done → move")

        # v27e: compute AFTER transitions — the transition frame may have
        # switched groups; using pre-switch tags would order the wrong group
        # on exactly the frames that matter.
        active_tags = (
            self.tank_group_0 if self.active_tank_group == 0 else self.tank_group_1
        )

        # Issue orders exactly once per state entry (frame 0 of each state —
        # now includes the transition frame itself)
        if self.frames_since_state_change == 0:
            if self.tank_state == "unsiege":
                for tank in tanks:
                    if tank.tag in active_tags and tank.type_id == UnitTypeId.SIEGETANKSIEGED:
                        tank(AbilityId.UNSIEGE_UNSIEGE)
                print(f"[Tank] Group {self.active_tank_group}: unsieging")

            elif self.tank_state == "move":
                moved = 0
                for tank in tanks:
                    if tank.tag not in active_tags:
                        continue
                    if tank.type_id == UnitTypeId.SIEGETANK:
                        tank.move(front_target)
                        tank(AbilityId.SIEGEMODE_SIEGEMODE, queue=True)
                        moved += 1
                    elif tank.type_id == UnitTypeId.SIEGETANKSIEGED:
                        # Shouldn't be sieged at start of "move" state, but handle it
                        tank(AbilityId.UNSIEGE_UNSIEGE)
                print(
                    f"[Tank] Group {self.active_tank_group}: {moved} tanks → "
                    f"({front_target.x:.1f},{front_target.y:.1f}) anchor={self.furthest_proj:.1f}"
                )

    def _move_marines(
        self, marines: Units, tank_center: Point2, dist_to_target: float = 999.0
    ) -> None:
        """
        Move marines to maintain position relative to tank center.

        v27g: far from the enemy base, marines lead (MARINE_DISTANCE=6 ahead)
        as the clearing element; within 40 tiles they tuck BEHIND the tank
        line (-3) — at close range the +6 spot sits inside missile-turret
        range and shredded the marine line (v27f: 8 trained → 2 left).
        """
        if marines.amount == 0:
            return

        # Calculate direction toward target from current tank center
        move_direction = self.target - tank_center
        if move_direction.length > 0.1:
            move_direction = move_direction.normalized
        else:
            return

        # Target position: ahead while advancing, behind the wall up close
        offset = self.MARINE_DISTANCE if dist_to_target > 40.0 else -3.0
        marine_target = tank_center + move_direction * offset

        # Move marines if they're not already at target (v20: attack-move so
        # they engage enemies along the advance instead of walking past them)
        moving_count = 0
        for marine in marines:
            distance_to_target = marine.position.distance_to(marine_target)

            if distance_to_target > 1.5:
                # Move toward marine target position (attack a Point2 =
                # move there + engage everything on the way)
                marine.attack(marine_target)
                moving_count += 1

    def _nearest_enemy_cc(self, ai, from_pos: Point2):
        """Closest enemy Command Center (None if none left).

        v27j: stop trusting ``ai.structures`` vs ``ai.enemy_structures``
        (AresBot fills BOTH per-frame; v27i/v27j both mis-picked or hit
        visibility gaps). Scan ``ai.all_units`` with an explicit owner
        check — same source of truth as the [FOE] dump — prefer visible
        CCs, fall back to any active CC (blip position is good enough to
        converge on).
        """
        try:
            ccs_all = ai.all_units.filter(
                lambda u: "COMMANDCENTER" in u.type_id.name
                and u.is_active
                and u.owner != ai.ai_id
            )
            if ccs_all.amount == 0:
                return None
            vis = ccs_all.filter(lambda u: u.is_visible)
            pool = vis if vis.amount > 0 else ccs_all
            return min(pool, key=lambda s: s.position.distance_to(from_pos))
        except Exception as e:
            # v27k-diag: swallow but REPORT — two versions of this lookup
            # failed silently in a row; never again without a trace.
            if not getattr(self, "_cc_err_reported", False):
                self._cc_err_reported = True
                import traceback
                print(f"[CCLOOKUP-ERR] {e!r}\n{traceback.format_exc()}", flush=True)
            return None

    def _assault_base(self, tanks: Units, marines: Units, cc) -> None:
        """v27i: converge tanks+marines onto the enemy CC itself.

        Siege tanks: walk in while unsieged, lock SIEGEMODE inside ~20 tiles,
        reposition (unsiege) if they end up too far to fire. Marines converge
        on the building as a damage screen. Vikings keep their normal
        threat-screening behavior (_move_vikings runs after this).
        """
        n_t, n_m = len(list(tanks)), len(list(marines))
        for t in tanks:
            try:
                d = t.position.distance_to(cc.position)
                if t.type_id == UnitTypeId.SIEGETANK:
                    if d > 20.0:
                        t.attack(cc)                 # approach unsieged
                    else:
                        t(AbilityId.SIEGEMODE_SIEGE)  # siege at firing range
                elif t.type_id == UnitTypeId.SIEGETANKSIEGED:
                    if d > 18.0:
                        t(AbilityId.UNSIEGE_UNSIEGE)  # reposition closer
            except Exception:
                pass
        for m in marines:
            try:
                m.attack(cc)
            except Exception:
                pass
        if self.frames_since_state_change % 30 == 0:
            print(
                f"[Assault] {n_t}t/{n_m}m → CC@({cc.position.x:.0f},{cc.position.y:.0f}) "
                f"d={tanks.center.distance_to(cc.position):.1f}",
                flush=True,
            )

    def _move_vikings(
        self, vikings: Units, tank_center: Point2, threats: Units = None, ai=None
    ) -> None:
        """Position vikings above tanks; engage nearest threat in range (v20)."""
        if vikings.amount == 0:
            return

        # Position vikings above tanks: north on the map (decreasing Y)
        # This puts them in a support position relative to the tank center
        viking_target = tank_center + Point2((0, -self.VIKING_ALTITUDE))

        for viking in vikings:
            # 1) engage the closest visible threat within range
            if threats is not None and threats.amount > 0:
                best = min(
                    threats, key=lambda u: u.position.distance_to(viking.position)
                )
                d_best = best.position.distance_to(viking.position)
                if d_best <= self.VIKING_ENGAGE_RANGE:
                    # stick with current target while it's still alive; re-target otherwise
                    cur = viking.order_target
                    keep = viking.orders and cur == best.tag and (
                        ai is None or ai.unit_tag_dict.get(cur) is not None
                    )
                    if not keep:
                        viking.attack(best)
                    continue

            # 2) no fight on — hover over the formation
            distance_to_target = viking.position.distance_to(viking_target)
            if distance_to_target > 1.5:
                # Move to altitude position above tanks
                viking.move(viking_target)
