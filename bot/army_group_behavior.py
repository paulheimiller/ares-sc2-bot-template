"""
Coordinated Army Group Behavior for Terran forces.

Implements formation movement with Marines, Tanks, and Vikings:
- Tanks: Alternating leapfrog movement with half going siege mode between moves
- Marines: Moving 2 tiles from tank center, then holding position
- Vikings: Centered directly above tanks
"""

from abc import ABC
from typing import Set

from ares.behaviors.behavior import Behavior
from ares.consts import UnitRole
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units


class CoordinatedArmyGroup(Behavior, ABC):
    """
    Manages coordinated movement of an army group with Marines, Tanks, and Vikings.

    The behavior implements:
    - Leapfrog tank movement: tanks move incrementally 2 tiles at a time, alternating groups
      Each group that finishes moving goes into siege mode, then the other group moves
    - Marines: stay 2 tiles from tank center, supporting the formation
    - Vikings: positioned above the tank formation for air support
    """

    MOVE_DISTANCE = 2.0  # Distance in tiles for incremental movement
    TILE_SIZE = 1.0  # SC2 tile size
    MARINE_DISTANCE = 2.0  # Marines stay 2 tiles from tank center
    VIKING_ALTITUDE = 5.0  # Vikings positioned this distance above tanks

    def __init__(
        self,
        target: Point2,
    ) -> None:
        """
        Initialize coordinated army group behavior.

        Parameters
        ----------
        target : Point2
            Target location for the army to move toward
        """
        self.target = target

        # Track movement state
        self.frames_since_state_change = 0

        # Tank movement state machine: "move" -> "siege" -> "wait" -> "unsiege" -> "move"
        self.tank_state = "move"  # Start by moving tanks (they start unsieged)

        # Track which tank group is actively moving
        self.active_tank_group = 0
        # Track tank IDs in each group for consistent grouping
        self.tank_group_0: Set[int] = set()
        self.tank_group_1: Set[int] = set()
        self.tanks_divided = False

        self.last_tank_center = None

    def execute(self, ai, config, mediator) -> None:
        """Execute coordinated army movement each frame."""
        # Get army units from the mediator using the role we assigned them to
        army_units = mediator.get_units_from_role(role=UnitRole.CONTROL_GROUP_ONE)
        
        if not army_units.amount:
            return

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

        # Debug: Print movement target info every 30 frames
        if self.frames_since_state_change % 30 == 0:
            print(f"[Army] Center: {tank_center}, Target: {self.target}, Distance: {tank_center.distance_to(self.target):.2f}")
            print(f"[Army] Units - Tanks: {tanks.amount}, Marines: {marines.amount}, Vikings: {vikings.amount}")
            print(f"[Army] Tank State: {self.tank_state}, Frames: {self.frames_since_state_change}, Active Group: {self.active_tank_group}")

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
        Move tanks in alternating groups with leapfrog pattern using a state machine.

        States:
        - wait: Waiting for next group to move (inactive group is sieged)
        - move: Move the active group forward
        - siege: Siege the active group after they've moved
        """
        if tanks.amount == 0:
            return

        # Calculate move direction from tank center toward target
        move_direction = self.target - tank_center
        if move_direction.length > 0.1:
            move_direction = move_direction.normalized
        else:
            print(f"[Tank] Already at target, stopping")
            return  # Already at target

        move_target = tank_center + move_direction * self.MOVE_DISTANCE * self.TILE_SIZE

        # Determine active group
        active_group_tags = (
            self.tank_group_0 if self.active_tank_group == 0 else self.tank_group_1
        )

        # Count tank types in active group for debugging
        active_sieged = sum(1 for t in tanks if t.tag in active_group_tags and t.type_id == UnitTypeId.SIEGETANKSIEGED)
        active_unsieged = sum(1 for t in tanks if t.tag in active_group_tags and t.type_id == UnitTypeId.SIEGETANK)

        print(f"[Tank Debug] State: {self.tank_state}, Frames: {self.frames_since_state_change}, Active Group: {self.active_tank_group}")
        print(f"[Tank Debug] Active group - Sieged: {active_sieged}, Unsieged: {active_unsieged}")

        # State machine for tank movement - Proper leapfrog pattern
        if self.tank_state == "move":
            # Move active group forward ONCE, then wait
            if self.frames_since_state_change == 0:
                move_count = 0
                for tank in tanks:
                    if tank.tag in active_group_tags:
                        # Unsiege if sieged
                        if tank.type_id == UnitTypeId.SIEGETANKSIEGED:
                            tank(AbilityId.UNSIEGE_UNSIEGE)
                        # If unsieged, move and queue siege
                        elif tank.type_id == UnitTypeId.SIEGETANK:
                            tank.move(move_target)
                            tank(AbilityId.SIEGEMODE_SIEGEMODE, queue=True)
                            move_count += 1

                if move_count > 0:
                    print(f"[Tank] Group {self.active_tank_group}: Moving {move_count} tanks to {move_target} (will auto-siege)")

            # After 72 frames (~3 seconds), switch groups and move again
            # This gives time for: unsiege (3s) + move (2s) + siege (3s)
            if self.frames_since_state_change >= 72:
                self.active_tank_group = 1 - self.active_tank_group
                self.frames_since_state_change = 0  # Reset to move next group
                print(f"[Tank] Switching to Group {self.active_tank_group}")

    def _move_marines(self, marines: Units, tank_center: Point2) -> None:
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

        # Target position: 2 tiles from tank center in direction of movement
        marine_target = (
            tank_center + move_direction * self.MARINE_DISTANCE * self.TILE_SIZE
        )

        # Move marines if they're not already at target
        moving_count = 0
        for marine in marines:
            distance_to_target = marine.position.distance_to(marine_target)

            if distance_to_target > 1.5:
                # Move toward marine target position
                marine.move(marine_target)
                moving_count += 1
        
        if moving_count > 0 and self.frames_since_state_change % 15 == 0:
            print(f"[Marines] Moving {moving_count}/{marines.amount} marines to {marine_target} (distance: {marines.center.distance_to(self.target):.1f} to target)")
            

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

