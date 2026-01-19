from typing import Optional

from ares import AresBot
from ares.behaviors.macro import BuildStructure, Mining, SpawnController, TechUp
from ares.consts import TECHLAB_TYPES
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

        # Register Mining behavior to automatically assign workers to gather resources
        # Workers not building will be evenly distributed among command centers
        self.register_behavior(Mining())

        # Build workers to maintain 16 per command center
        await self.build_workers()

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
            await self.build_units(UnitTypeId.MARINE, num_units=10)
        if self.tanks_ready:
            await self.build_units(UnitTypeId.SIEGETANK, num_units=5)
        if self.vikings_ready:
            await self.build_units(UnitTypeId.VIKING, num_units=3)

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
        if current_workers >= target_workers:
            return

        # Check if we have enough supply
        if self.supply_left < 1 and self.supply_cap < 200:
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

        # Build workers from idle townhalls that can afford it
        for townhall in townhalls:
            if current_workers >= target_workers:
                break

            # Check if townhall is idle and we can afford a worker
            if townhall.is_idle and self.can_afford(UnitTypeId.SCV):
                townhall.train(UnitTypeId.SCV)
                current_workers += 1  # Count the worker we just queued

    async def build_units(self, unit_type: UnitTypeId, num_units: int) -> None:
        """
        Build a specified number of units when structures are ready.
        Checks if resources are available before issuing build commands.
        Automatically builds supply depots if supply is insufficient.

        Parameters
        ----------
        unit_type : UnitTypeId
            The type of unit to build (e.g., UnitTypeId.MARINE, UnitTypeId.SIEGETANK)
        num_units : int
            The number of units to build

        Examples
        --------
        >>> self.build_units(UnitTypeId.MARINE, 10)
        >>> self.build_units(UnitTypeId.SIEGETANK, 5)
        >>> self.build_units(UnitTypeId.VIKING, 3)
        """
        # Get the supply cost of the unit type
        unit_supply_cost = self.calculate_supply_cost(unit_type)

        # Check if we have enough supply for at least one unit
        if self.supply_left < unit_supply_cost and self.supply_cap < 200:
            # We need more supply - build a supply depot
            if self.can_afford(UnitTypeId.SUPPLYDEPOT):
                # Check if we're not already building a supply depot
                pending_depots = self.structures.filter(
                    lambda s: s.type_id == UnitTypeId.SUPPLYDEPOT and not s.is_ready
                )
                # Only build if we don't have one already in progress
                if len(pending_depots) == 0:
                    self.register_behavior(
                        BuildStructure(
                            base_location=self.start_location,
                            structure_id=UnitTypeId.SUPPLYDEPOT,
                            production=False,
                        )
                    )
            return  # Wait for supply before building units

        # Check if we can afford at least one unit before registering behavior
        if not self.can_afford(unit_type):
            return

        # Create army composition dict with single unit type
        army_comp = {
            unit_type: {
                "proportion": 1.0,
                "priority": 0
            }
        }

        # Register SpawnController behavior with maximum set to num_units
        # Note: SpawnController will handle resource checking for each individual unit
        self.register_behavior(
            SpawnController(
                army_composition_dict=army_comp,
                maximum=num_units,
                freeflow_mode=True  # Don't worry about proportions for single unit type
            )
        )

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
