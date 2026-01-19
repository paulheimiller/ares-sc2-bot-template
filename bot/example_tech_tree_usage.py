"""
Example usage of the Terran tech tree system in an SC2 bot context.
This demonstrates how to integrate the tech tree requirements into your bot logic.
"""

from terran_tech_tree import get_build_requirements, TERRAN_TECH_TREE


def can_build_unit(unit_name: str, available_buildings: list[str]) -> tuple[bool, list[str]]:
    """
    Check if a unit can be built with the current available buildings.

    Args:
        unit_name: Name of the unit to build (e.g., "Battlecruiser")
        available_buildings: List of buildings currently available

    Returns:
        Tuple of (can_build: bool, missing_buildings: list[str])
    """
    try:
        requirements = get_build_requirements(unit_name)
        required_buildings = set(requirements["buildings"])
        available = set(available_buildings)

        missing = required_buildings - available
        can_build = len(missing) == 0

        return can_build, sorted(list(missing))

    except KeyError:
        return False, [f"Unknown unit: {unit_name}"]


def get_next_building_to_build(target_unit: str, available_buildings: list[str]) -> str | None:
    """
    Determine the next building that should be constructed to reach the target unit.

    Args:
        target_unit: The unit we want to eventually build
        available_buildings: Buildings currently available

    Returns:
        Name of the next building to construct, or None if target is already buildable
    """
    can_build, missing = can_build_unit(target_unit, available_buildings)

    if can_build:
        return None  # Already can build the target

    if not missing:
        return None

    # Get the full build order
    requirements = get_build_requirements(target_unit)
    build_order = requirements["buildings"]

    # Find the first missing building in the build order
    for building in build_order:
        if building not in available_buildings:
            return building

    return None


def get_tech_path(start_buildings: list[str], target_unit: str) -> list[str]:
    """
    Get the sequence of buildings needed to go from current state to target unit.

    Args:
        start_buildings: Buildings currently available
        target_unit: The unit we want to build

    Returns:
        List of buildings to construct in order
    """
    requirements = get_build_requirements(target_unit)
    all_required = requirements["buildings"]
    available = set(start_buildings)

    tech_path = []
    for building in all_required:
        if building not in available:
            tech_path.append(building)

    return tech_path


# Example usage
if __name__ == "__main__":
    print("="*60)
    print("Example 1: Early game scenario")
    print("="*60)

    # Early game: We have a Supply Depot and Barracks
    current_buildings = ["SupplyDepot", "Barracks", "CommandCenter"]

    print(f"Current buildings: {current_buildings}")
    print()

    # Can we build a Marine?
    can_build, missing = can_build_unit("Marine", current_buildings)
    print(f"Can build Marine? {can_build}")
    if missing:
        print(f"  Missing: {missing}")

    # Can we build a Siege Tank?
    can_build, missing = can_build_unit("SiegeTank", current_buildings)
    print(f"Can build Siege Tank? {can_build}")
    if missing:
        print(f"  Missing: {missing}")

    # What's the next building for a Siege Tank?
    next_building = get_next_building_to_build("SiegeTank", current_buildings)
    print(f"  Next building needed: {next_building}")

    print("\n" + "="*60)
    print("Example 2: Planning for Battlecruiser")
    print("="*60)

    # Mid game: We have some tech
    current_buildings = ["SupplyDepot", "Barracks", "Factory", "CommandCenter"]

    print(f"Current buildings: {current_buildings}")
    print()

    tech_path = get_tech_path(current_buildings, "Battlecruiser")
    print(f"Buildings needed for Battlecruiser:")
    for i, building in enumerate(tech_path, 1):
        print(f"  {i}. {building}")

    print("\n" + "="*60)
    print("Example 3: Step-by-step tech progression")
    print("="*60)

    # Start from scratch
    buildings = ["CommandCenter"]
    target = "Thor"

    print(f"Goal: Build a {target}")
    print(f"Starting with: {buildings}\n")

    step = 1
    while True:
        next_building = get_next_building_to_build(target, buildings)
        if next_building is None:
            print(f"\n✓ Can now build {target}!")
            break

        print(f"Step {step}: Build {next_building}")
        buildings.append(next_building)
        step += 1

    print(f"\nFinal building list: {buildings}")

    print("\n" + "="*60)
    print("Example 4: Checking multiple unit options")
    print("="*60)

    current_buildings = ["SupplyDepot", "Barracks", "Factory", "Starport", "CommandCenter"]
    units_to_check = ["Marine", "SiegeTank", "Viking", "Battlecruiser", "Thor"]

    print(f"Current buildings: {current_buildings}\n")
    print("Unit availability:")

    for unit in units_to_check:
        can_build, missing = can_build_unit(unit, current_buildings)
        status = "✓ Available" if can_build else f"✗ Missing: {', '.join(missing)}"
        print(f"  {unit:20s} {status}")
