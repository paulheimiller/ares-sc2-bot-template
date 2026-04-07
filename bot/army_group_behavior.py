"""
Coordinated Army Group Behavior for Terran forces.

Implements formation movement with Marines, Tanks, and Vikings:
- Tanks: Alternating leapfrog movement with half going siege mode between moves
- Marines: Moving 2 tiles from tank center, then holding position
- Vikings: Centered directly above tanks
"""

from typing import Set

from ares.consts import UnitRole
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.units import Units


class CoordinatedArmyGroup:
    """
    Manages coordinated movement of an army group with Marines, Tanks, and Vikings.

    The behavior implements:
    - Leapfrog tank movement: tanks move incrementally 2 tiles at a time, alternating groups
      Each group that finishes moving goes into siege mode, then the other group moves
    - Marines: stay 2 tiles from tank center, supporting the formation
    - Vikings: positioned above the tank formation for air support
    """

    MOVE_DISTANCE = 2.0   # Tiles each group advances per leapfrog step
    MARINE_DISTANCE = 2.0  # Marines stay 2 tiles ahead of tank center
    VIKING_ALTITUDE = 5.0  # Vikings positioned this distance north of tanks

    # Timing constants (behavior frames; ares default game_step=2 ≈ 11 fps)
    UNSIEGE_FRAMES = 40   # ~3.5 s to complete unsiege animation
    MOVE_SIEGE_FRAMES = 56  # ~5 s to cover 2 tiles + complete siege animation

    # Attack mode: switch from leapfrog to all-out attack within this range
    ATTACK_RANGE = 10.0
    ATTACK_REISSUE_FRAMES = 55  # Re-issue attack orders every ~5 s to unstick units

    def __init__(self, target: Point2) -> None:
        """
        Parameters
        ----------
        target : Point2
            Enemy location the army marches toward.
        """
        self.target = target

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
        self.attack_mode = False

    def execute(self, ai, config, mediator) -> bool:
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

        # Switch to attack mode when close enough to enemy base
        if not self.attack_mode and tank_center.distance_to(self.target) <= self.ATTACK_RANGE:
            self.attack_mode = True
            self.frames_since_state_change = 0
            print(f"[Army] Entering attack mode — distance {tank_center.distance_to(self.target):.1f}")

        if self.attack_mode:
            self._execute_attack_mode(army_units)
            self.frames_since_state_change += 1
            self.last_tank_center = tank_center
            return True

        # Periodic status print (every ~5 seconds at game_step=2)
        if self.frames_since_state_change % 55 == 0:
            dist = tank_center.distance_to(self.target)
            print(
                f"[Army] dist={dist:.1f} state={self.tank_state} group={self.active_tank_group} "
                f"tanks={tanks.amount} marines={marines.amount}"
            )

        # Divide tanks into two groups on first execution
        if not self.tanks_divided and tanks.amount > 0:
            self._divide_tanks_into_groups(tanks)

        # Move tanks with leapfrog pattern (BEFORE incrementing counter)
        self._move_tanks_leapfrog(tanks, tank_center, ai)

        # Move marines relative to tank center
        self._move_marines(marines, tank_center)

        # Increment frame counter AFTER all movement logic
        self.frames_since_state_change += 1

        # Move vikings directly above tank center
        self._move_vikings(vikings, tank_center)

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

    def _move_tanks_leapfrog(self, tanks: Units, tank_center: Point2, ai) -> None:
        """
        Leapfrog state machine: groups alternate between moving and sieging.

        States
        ------
        "move"    : Issue move+queue_siege once at frame 0. After MOVE_SIEGE_FRAMES,
                    switch to the other group. Skip "unsiege" if that group is already
                    unsieged (e.g. first cycle for group 1).
        "unsiege" : Issue unsiege once at frame 0. After UNSIEGE_FRAMES, transition
                    to "move" so the group can advance.
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

        active_tags = (
            self.tank_group_0 if self.active_tank_group == 0 else self.tank_group_1
        )

        # If active group is wiped out, switch to whichever group still has tanks
        live_tags = {t.tag for t in tanks}
        if not active_tags.intersection(live_tags):
            other_group = 1 - self.active_tank_group
            other_tags = self.tank_group_0 if other_group == 0 else self.tank_group_1
            if other_tags.intersection(live_tags):
                print(f"[Tank] Group {self.active_tank_group} wiped — switching to Group {other_group}")
                self.active_tank_group = other_group
                active_tags = other_tags
                self.tank_state = "move"
                self.frames_since_state_change = 0
            else:
                return  # All tanks dead

        # Issue orders exactly once per state entry (frame 0 of each state)
        if self.frames_since_state_change == 0:
            if self.tank_state == "unsiege":
                for tank in tanks:
                    if tank.tag in active_tags and tank.type_id == UnitTypeId.SIEGETANKSIEGED:
                        tank(AbilityId.UNSIEGE_UNSIEGE)
                print(f"[Tank] Group {self.active_tank_group}: unsieging")

            elif self.tank_state == "move":
                # Move target is computed from active group's center for accuracy
                active_tanks = [t for t in tanks if t.tag in active_tags]
                if active_tanks:
                    group_center = Point2(
                        (
                            sum(t.position.x for t in active_tanks) / len(active_tanks),
                            sum(t.position.y for t in active_tanks) / len(active_tanks),
                        )
                    )
                    # Recalculate direction from this group's center
                    grp_dir = self.target - group_center
                    if grp_dir.length > 0.1:
                        grp_dir = grp_dir.normalized
                    else:
                        grp_dir = move_direction
                    move_target = group_center + grp_dir * self.MOVE_DISTANCE
                else:
                    move_target = tank_center + move_direction * self.MOVE_DISTANCE

                moved = 0
                for tank in tanks:
                    if tank.tag not in active_tags:
                        continue
                    if tank.type_id == UnitTypeId.SIEGETANK:
                        tank.move(move_target)
                        tank(AbilityId.SIEGEMODE_SIEGEMODE, queue=True)
                        moved += 1
                    elif tank.type_id == UnitTypeId.SIEGETANKSIEGED:
                        # Shouldn't be sieged at start of "move" state, but handle it
                        tank(AbilityId.UNSIEGE_UNSIEGE)
                print(f"[Tank] Group {self.active_tank_group}: {moved} tanks → {move_target}")

        # State transitions
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

    def _execute_attack_mode(self, army_units) -> None:
        """
        All-out attack on the target: unsiege tanks then attack-move every unit.

        Orders are re-issued every ATTACK_REISSUE_FRAMES to keep units advancing
        if they get stuck or finish killing a cluster of enemies.
        """
        if self.frames_since_state_change % self.ATTACK_REISSUE_FRAMES != 0:
            return

        issued = 0
        for unit in army_units:
            if unit.type_id == UnitTypeId.SIEGETANKSIEGED:
                unit(AbilityId.UNSIEGE_UNSIEGE)
            else:
                unit.attack(self.target)
            issued += 1

        if issued:
            print(f"[Army] Attack-move: {issued} units → {self.target}")

    def _move_marines(self, marines, tank_center: Point2) -> None:
        """
        Move marines to maintain position 2 tiles from tank center.

        Marines stay close to tanks for support, moving incrementally.
        They stop when reached and wait for tanks.
        """
        if marines.amount == 0:
            return

        # Calculate direction toward target from current tank center
        move_direction = self.target - tank_center
        if move_direction.length > 0.1:
            move_direction = move_direction.normalized
        else:
            return

        marine_target = tank_center + move_direction * self.MARINE_DISTANCE

        # Move marines if they're not already at target
        moving_count = 0
        for marine in marines:
            distance_to_target = marine.position.distance_to(marine_target)

            if distance_to_target > 1.5:
                # Move toward marine target position
                marine.move(marine_target)
                moving_count += 1
        
        # (no per-frame print; army-level status covers this)
            

    def _move_vikings(self, vikings: Units, tank_center: Point2) -> None:
        """
        Position vikings directly above tanks for air support.

        Vikings stay centered above the tank formation, maintaining altitude.
        """
        if vikings.amount == 0:
            return

        # Calculate direction of movement for better positioning
        move_direction = self.target - tank_center
        
        # Position vikings above tanks: north on the map (decreasing Y)
        # This puts them in a support position relative to the tank center
        viking_target = tank_center + Point2((0, -self.VIKING_ALTITUDE))

        for viking in vikings:
            # Check distance to target position
            distance_to_target = viking.position.distance_to(viking_target)

            if distance_to_target > 1.5:
                # Move to altitude position above tanks
                viking.move(viking_target)
            # else: Hold position above tanks

