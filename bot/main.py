from typing import Optional

from ares import AresBot
from ares.behaviors.macro import BuildStructure, GasBuildingController, Mining, SpawnController, TechUp
from ares.behaviors.combat.group import AMoveGroup
from ares.consts import TECHLAB_TYPES
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

from bot.terran_tech_tree import get_build_requirements


class TankBot(AresBot):
    def __init__(self, game_step_override: Optional[int] = None):
        """Initiate custom bot

        Parameters
        ----------
        game_step_override :
            If provided, set the game_step to this value regardless of how it was
            specified elsewhere
        """
        super().__init__(game_step_override)

        # Fetch build orders for our target units
        self.marine_build_order = get_build_requirements("Marine")
        self.siege_tank_build_order = get_build_requirements("SiegeTank")
        self.viking_build_order = get_build_requirements("Viking")

        # Track which phase of building we're in
        self.current_build_phase = "marines"  # marines -> tanks -> vikings
        self.marines_ready = False
        self.tanks_ready = False
        self.vikings_ready = False
        self.all_builds_complete = False  # Track when all building orders are fulfilled

        # Unit orders - tracks how many of each unit type we want to build
        self.unit_orders = {
            UnitTypeId.MARINE: {"total": 20, "completed": 0, "baseline": 0},
            UnitTypeId.SIEGETANK: {"total": 10, "completed": 0, "baseline": 0},
            UnitTypeId.VIKINGFIGHTER: {"total": 10, "completed": 0, "baseline": 0},
        }

    async def on_start(self) -> None:
        await super(TankBot, self).on_start()

        # Print build orders on game start
        print("\n=== TankBot Build Orders ===")
        print(f"Marine requirements: {self.marine_build_order['buildings']}")
        print(f"Siege Tank requirements: {self.siege_tank_build_order['buildings']}")
        print(f"Viking requirements: {self.viking_build_order['buildings']}")
        print("=" * 40 + "\n")

    async def on_step(self, iteration: int) -> None:
        await super(TankBot, self).on_step(iteration)

        # Register Mining behavior with speed mining optimizations
        # mineral_boost: Enables mineral boosting for faster mineral gathering
        # vespene_boost: Enables vespene boosting (optimizes gas mining)
        # long_distance_mine: Workers can long-distance mine if they have nothing to do
        # workers_per_gas: Optimal worker count per gas geyser (typically 2-3 for speed mining)
        # keep_safe: Workers will flee if they're in danger
        self.register_behavior(
            Mining(
                mineral_boost=True,
                vespene_boost=True,
                long_distance_mine=True,
                workers_per_gas=3,
                keep_safe=True,
            )
        )

        # Build gas buildings (refineries) - one per townhall
        # This automatically handles finding available geysers and building refineries
        num_geysers_to_build = len(self.townhalls.ready) * 2  # 1 geyser per townhall
        self.register_behavior(
            GasBuildingController(to_count=num_geysers_to_build, max_pending=1)
        )

        # Build workers to maintain 16 per command center
        await self.build_workers()

        # Build refineries for vespene mining from available gas geysers
        await self.build_refineries()

        # Mapping from our tech tree names to SC2 UnitTypeId
        name_to_unit_type = {
            "SupplyDepot": UnitTypeId.SUPPLYDEPOT,
            "Barracks": UnitTypeId.BARRACKS,
            "Factory": UnitTypeId.FACTORY,
            "FactoryTechLab": UnitTypeId.FACTORYTECHLAB,
            "Starport": UnitTypeId.STARPORT,
        }

        # Phase 1: Build requirements for Marines
        if self.current_build_phase == "marines":
            if self._build_required_structures(self.marine_build_order, name_to_unit_type):
                print("Marines build requirements complete! Moving to Tanks phase.")
                self.marines_ready = True
                self.current_build_phase = "tanks"

        # Phase 2: Build requirements for Siege Tanks
        elif self.current_build_phase == "tanks":
            if self._build_required_structures(self.siege_tank_build_order, name_to_unit_type):
                print("Siege Tanks build requirements complete! Moving to Vikings phase.")
                self.tanks_ready = True
                self.current_build_phase = "vikings"

        # Phase 3: Build requirements for Vikings
        elif self.current_build_phase == "vikings":
            if self._build_required_structures(self.viking_build_order, name_to_unit_type):
                print("Vikings build requirements complete! All phases done.")
                self.vikings_ready = True
                self.current_build_phase = "complete"

        # Phase 4: Build units when structures are ready
        if self.marines_ready:
            await self.build_units(UnitTypeId.MARINE, self.unit_orders)
        if self.tanks_ready:
            await self.build_units(UnitTypeId.SIEGETANK, self.unit_orders)
        if self.vikings_ready:
            await self.build_units(UnitTypeId.VIKINGFIGHTER, self.unit_orders)

        # Phase 5: Once all builds are complete, move all units to enemy base
        if not self.all_builds_complete and self._check_all_builds_complete():
            print("All build orders fulfilled! Moving all units to enemy base.")
            self.all_builds_complete = True

        # Move all units to enemy base if builds are complete
        if self.all_builds_complete:
            await self._attack_enemy_base()

    def _check_all_builds_complete(self) -> bool:
        """
        Check if all unit build orders have been fulfilled.
        Counts actual units rather than relying on queued count.
        Returns True when all ordered units have been built and exist.
        """
        # Count actual completed units for each type
        for unit_type, order in self.unit_orders.items():
            actual_count = self.units.filter(lambda u: u.type_id == unit_type).amount
            if actual_count < order["total"]:
                print(f"{unit_type.name}: {actual_count}/{order['total']} complete")
                return False
        return True

    async def _attack_enemy_base(self) -> None:
        """
        Move all units to the enemy base.
        Uses AMoveGroup behavior to attack-move all units toward the enemy starting location.
        """
        # Get all army units (combat units)
        army_units = self.units.filter(
            lambda u: u.type_id in [
                UnitTypeId.MARINE,
                UnitTypeId.SIEGETANK,
                UnitTypeId.VIKINGFIGHTER,
            ]
        )

        if army_units.amount == 0:
            return  # No units to move

        # Register attack-move behavior to attack enemy base
        # This will move all units toward the enemy starting location
        self.register_behavior(
            AMoveGroup(
                group=list(army_units),
                group_tags={u.tag for u in army_units},
                target=self.enemy_start_locations[0],
            )
        )

    def _build_required_structures(
        self, build_order: dict, name_to_unit_type: dict
    ) -> bool:
        """
        Build all required structures from a build order.
        Returns True when all structures are ready.
        Automatically builds supply depots if supply is needed.
        """
        required_buildings = build_order["buildings"]

        # Check if all required buildings are ready
        all_ready = True
        for building_name in required_buildings:
            if building_name not in name_to_unit_type:
                continue  # Skip buildings we don't have mapped

            unit_type = name_to_unit_type[building_name]

            # Check if we need more supply before building structures
            # (Some structures require supply, and we want to ensure we can build workers)
            if self.supply_left < 2 and self.supply_cap < 200:
                # Build a supply depot if we can afford it
                if self.can_afford(UnitTypeId.SUPPLYDEPOT):
                    pending_depots = self.structures.filter(
                        lambda s: s.type_id == UnitTypeId.SUPPLYDEPOT and not s.is_ready
                    )
                    if len(pending_depots) == 0:
                        self.register_behavior(
                            BuildStructure(
                                base_location=self.start_location,
                                structure_id=UnitTypeId.SUPPLYDEPOT,
                                production=False,
                            )
                        )

            # For tech labs, check if we have a ready structure with a tech lab attached
            if unit_type in TECHLAB_TYPES:
                # Map tech lab types to their base structures
                techlab_to_structure = {
                    UnitTypeId.BARRACKSTECHLAB: UnitTypeId.BARRACKS,
                    UnitTypeId.FACTORYTECHLAB: UnitTypeId.FACTORY,
                    UnitTypeId.STARPORTTECHLAB: UnitTypeId.STARPORT,
                }

                base_structure = techlab_to_structure.get(unit_type)
                if base_structure:
                    # Check if we have the base structure with a tech lab attached
                    structures_with_techlab = self.structures.filter(
                        lambda s: s.type_id == base_structure and s.has_techlab and s.is_ready
                    )

                    if len(structures_with_techlab) == 0:
                        all_ready = False
                        # Check if we can afford the tech lab before building
                        if self.can_afford(unit_type):
                            # Use TechUp behavior to build tech labs
                            self.register_behavior(
                                TechUp(
                                    desired_tech=unit_type,
                                    base_location=self.start_location,
                                )
                            )
            else:
                # Check if we have this building ready
                existing = self.structures.filter(
                    lambda s: s.type_id == unit_type and s.is_ready
                )

                if len(existing) == 0:
                    all_ready = False

                    # Try to build this structure if we don't have one building/built
                    pending = self.structures.filter(lambda s: s.type_id == unit_type)
                    if len(pending) == 0:
                        # Check if we can afford the structure before building
                        if self.can_afford(unit_type):
                            # Register behavior to build this structure
                            self.register_behavior(
                                BuildStructure(
                                    base_location=self.start_location,
                                    structure_id=unit_type,
                                    production=True if unit_type in [UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT] else False,
                                )
                            )

        return all_ready

    async def build_refineries(self) -> None:
        """
        Placeholder for additional gas building logic if needed.
        GasBuildingController handles the main refinery construction.
        """
        pass

    async def build_workers(self) -> None:
        """
        Build workers (SCVs) to maintain 16 per command center.
        Only builds workers if we have fewer than 16 per townhall.
        """
        # Get all townhalls (CommandCenter, OrbitalCommand, PlanetaryFortress)
        townhalls = self.townhalls.ready

        if not townhalls:
            return

        # Count current workers
        current_workers = self.workers.amount

        # Calculate target workers (16 per command center)
        target_workers = len(townhalls) * 16

        # Don't build if we're at or above target
        # if current_workers <= target_workers:
        #     return

        # Build workers from idle townhalls that can afford it
        for townhall in townhalls:
            if current_workers >= target_workers:
                break

            # Check if townhall is idle and we can afford a worker
            if townhall.is_idle and self.can_afford(UnitTypeId.SCV):
                townhall.train(UnitTypeId.SCV)
                current_workers += 1  # Count the worker we just queued

        # Check if we have enogh supply
        if self.supply_left < 50 and self.supply_cap < 200:
            # Build supply depot if needed
            if self.can_afford(UnitTypeId.SUPPLYDEPOT):
                pending_depots = self.structures.filter(
                    lambda s: s.type_id == UnitTypeId.SUPPLYDEPOT and not s.is_ready
                )
                if len(pending_depots) == 0:
                    self.register_behavior(
                        BuildStructure(
                            base_location=self.start_location,
                            structure_id=UnitTypeId.SUPPLYDEPOT,
                            production=False,
                        )
                    )
        return



    async def build_units(self, unit_type: UnitTypeId, unit_orders: dict) -> None:
        """
        Build units based on the order structure.
        Checks if resources are available before issuing build commands.
        Automatically builds supply depots if supply is insufficient.

        Parameters
        ----------
        unit_type : UnitTypeId
            The type of unit to build (e.g., UnitTypeId.MARINE, UnitTypeId.SIEGETANK)
        unit_orders : dict
            Dictionary tracking unit orders with structure:
            {UnitTypeId: {"total": int, "completed": int}}

        Examples
        --------
        >>> self.build_units(UnitTypeId.MARINE, self.unit_orders)
        >>> self.build_units(UnitTypeId.SIEGETANK, self.unit_orders)
        >>> self.build_units(UnitTypeId.VIKING, self.unit_orders)
        """
        # Check if this unit type has an order
        if unit_type not in unit_orders:
            return

        order = unit_orders[unit_type]

        # Count how many of this unit type we currently have
        actual_count = self.units.filter(lambda u: u.type_id == unit_type).amount
        target_count = order["total"]

        # If order is complete, return early
        if actual_count >= target_count:
            return

        # Calculate how many more units we need to build
        num_units_needed = target_count - actual_count

        # Try to build units, let SpawnController handle resource/supply checks
        try:
            # Create army composition dict with single unit type
            army_comp = {
                unit_type: {
                    "proportion": 1.0,
                    "priority": 0
                }
            }

            # Register SpawnController behavior with maximum set to num_units_needed
            # SpawnController handles resource checking and supply requirements
            self.register_behavior(
                SpawnController(
                    army_composition_dict=army_comp,
                    maximum=num_units_needed,
                    freeflow_mode=True  # Don't worry about proportions for single unit type
                )
            )
        except Exception:
            # If there's any issue, just skip this iteration
            return

    """
    Can use `python-sc2` hooks as usual, but make a call the inherited method in the superclass
    Examples:
    """
    # async def on_end(self, game_result: Result) -> None:
    #     await super(TankBot, self).on_end(game_result)
    #
    #     # custom on_end logic here ...
    #
    # async def on_building_construction_complete(self, unit: Unit) -> None:
    #     await super(TankBot, self).on_building_construction_complete(unit)
    #
    #     # custom on_building_construction_complete logic here ...
    #
    # async def on_unit_created(self, unit: Unit) -> None:
    #     await super(TankBot, self).on_unit_created(unit)
    #
    #     # custom on_unit_created logic here ...
    #
    # async def on_unit_destroyed(self, unit_tag: int) -> None:
    #     await super(TankBot, self).on_unit_destroyed(unit_tag)
    #
    #     # custom on_unit_destroyed logic here ...
    #
    # async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float) -> None:
    #     await super(TankBot, self).on_unit_took_damage(unit, amount_damage_taken)
    #
    #     # custom on_unit_took_damage logic here ...
