"""
Terran Tech Tree and Build Order Requirements
Provides data structure and procedures for determining build requirements for any Terran unit or building.
"""

from typing import List, Set, Dict


# Complete Terran tech tree structure
TERRAN_TECH_TREE: Dict[str, Dict[str, List[str]]] = {
    # ========== BUILDINGS ==========

    # Base structures (no requirements)
    "CommandCenter": {
        "buildings": [],
        "units": []
    },
    "SupplyDepot": {
        "buildings": [],
        "units": []
    },
    "Refinery": {
        "buildings": [],
        "units": []
    },

    # Tier 1 structures
    "Barracks": {
        "buildings": ["SupplyDepot"],
        "units": []
    },
    "OrbitalCommand": {
        "buildings": ["Barracks"],
        "units": []
    },
    "PlanetaryFortress": {
        "buildings": ["EngineeringBay"],
        "units": []
    },
    "EngineeringBay": {
        "buildings": ["CommandCenter"],
        "units": []
    },
    "Bunker": {
        "buildings": ["Barracks"],
        "units": []
    },
    "MissileTurret": {
        "buildings": ["EngineeringBay"],
        "units": []
    },
    "SensorTower": {
        "buildings": ["EngineeringBay"],
        "units": []
    },
    "GhostAcademy": {
        "buildings": ["Barracks"],
        "units": []
    },

    # Tier 2 structures
    "Factory": {
        "buildings": ["Barracks"],
        "units": []
    },
    "Armory": {
        "buildings": ["Factory"],
        "units": []
    },

    # Tier 3 structures
    "Starport": {
        "buildings": ["Factory"],
        "units": []
    },
    "FusionCore": {
        "buildings": ["Starport"],
        "units": []
    },

    # Add-ons (require production building)
    "BarracksTechLab": {
        "buildings": ["Barracks"],
        "units": []
    },
    "BarracksReactor": {
        "buildings": ["Barracks"],
        "units": []
    },
    "FactoryTechLab": {
        "buildings": ["Factory"],
        "units": []
    },
    "FactoryReactor": {
        "buildings": ["Factory"],
        "units": []
    },
    "StarportTechLab": {
        "buildings": ["Starport"],
        "units": []
    },
    "StarportReactor": {
        "buildings": ["Starport"],
        "units": []
    },

    # ========== UNITS ==========

    # Command Center units
    "SCV": {
        "buildings": ["CommandCenter"],
        "units": []
    },
    "MULE": {
        "buildings": ["OrbitalCommand"],
        "units": []
    },

    # Barracks units
    "Marine": {
        "buildings": ["Barracks"],
        "units": []
    },
    "Reaper": {
        "buildings": ["Barracks"],
        "units": []
    },
    "Marauder": {
        "buildings": ["Barracks", "BarracksTechLab"],
        "units": []
    },
    "Ghost": {
        "buildings": ["Barracks", "BarracksTechLab", "GhostAcademy"],
        "units": []
    },

    # Factory units
    "Hellion": {
        "buildings": ["Factory"],
        "units": []
    },
    "Hellbat": {
        "buildings": ["Factory", "Armory"],
        "units": []
    },
    "WidowMine": {
        "buildings": ["Factory"],
        "units": []
    },
    "Cyclone": {
        "buildings": ["Factory", "FactoryTechLab"],
        "units": []
    },
    "SiegeTank": {
        "buildings": ["Factory", "FactoryTechLab"],
        "units": []
    },
    "Thor": {
        "buildings": ["Factory", "FactoryTechLab", "Armory"],
        "units": []
    },

    # Starport units
    "Viking": {
        "buildings": ["Starport"],
        "units": []
    },
    "Medivac": {
        "buildings": ["Starport"],
        "units": []
    },
    "Liberator": {
        "buildings": ["Starport"],
        "units": []
    },
    "Banshee": {
        "buildings": ["Starport", "StarportTechLab"],
        "units": []
    },
    "Raven": {
        "buildings": ["Starport", "StarportTechLab"],
        "units": []
    },
    "Battlecruiser": {
        "buildings": ["Starport", "StarportTechLab", "FusionCore"],
        "units": []
    },

    # Summoned units
    "AutoTurret": {
        "buildings": ["Starport", "StarportTechLab"],
        "units": ["Raven"]
    },
}


def get_build_requirements(unit_name: str) -> Dict[str, List[str]]:
    """
    Get the complete build order requirements for a given unit or building.

    Args:
        unit_name: Name of the unit or building (e.g., "Battlecruiser", "SiegeTank")

    Returns:
        Dictionary containing:
            - "buildings": List of all required buildings in dependency order
            - "units": List of all required units
            - "immediate": Direct requirements for the requested unit

    Raises:
        KeyError: If unit_name is not found in the tech tree
    """
    if unit_name not in TERRAN_TECH_TREE:
        raise KeyError(f"Unit '{unit_name}' not found in Terran tech tree. "
                      f"Available units: {sorted(TERRAN_TECH_TREE.keys())}")

    all_buildings: List[str] = []
    all_units: List[str] = []
    visited: Set[str] = set()

    def resolve_dependencies(name: str) -> None:
        """Recursively resolve all dependencies for a unit/building."""
        if name in visited:
            return

        visited.add(name)

        if name not in TERRAN_TECH_TREE:
            # This shouldn't happen if the tech tree is properly defined
            return

        requirements = TERRAN_TECH_TREE[name]

        # First, resolve all building dependencies recursively
        for building in requirements["buildings"]:
            resolve_dependencies(building)
            if building not in all_buildings:
                all_buildings.append(building)

        # Then, resolve all unit dependencies recursively
        for unit in requirements["units"]:
            resolve_dependencies(unit)
            if unit not in all_units:
                all_units.append(unit)

    # Get immediate requirements
    immediate_requirements = TERRAN_TECH_TREE[unit_name]

    # Resolve all dependencies
    resolve_dependencies(unit_name)

    return {
        "buildings": all_buildings,
        "units": all_units,
        "immediate": {
            "buildings": immediate_requirements["buildings"],
            "units": immediate_requirements["units"]
        }
    }


def print_build_order(unit_name: str) -> None:
    """
    Print a human-readable build order for a given unit or building.

    Args:
        unit_name: Name of the unit or building
    """
    try:
        requirements = get_build_requirements(unit_name)

        print(f"\n{'='*60}")
        print(f"Build Order for: {unit_name}")
        print(f"{'='*60}")

        if not requirements["buildings"] and not requirements["units"]:
            print("✓ No requirements - can be built immediately")
        else:
            if requirements["buildings"]:
                print(f"\nRequired Buildings (in order):")
                for i, building in enumerate(requirements["buildings"], 1):
                    print(f"  {i}. {building}")

            if requirements["units"]:
                print(f"\nRequired Units:")
                for i, unit in enumerate(requirements["units"], 1):
                    print(f"  {i}. {unit}")

            print(f"\nDirect Requirements:")
            print(f"  Buildings: {', '.join(requirements['immediate']['buildings']) or 'None'}")
            print(f"  Units: {', '.join(requirements['immediate']['units']) or 'None'}")

        print(f"{'='*60}\n")

    except KeyError as e:
        print(f"Error: {e}")


def get_all_terran_units() -> List[str]:
    """
    Get a list of all available Terran units and buildings.

    Returns:
        Sorted list of all unit and building names
    """
    return sorted(TERRAN_TECH_TREE.keys())


# Example usage and testing
if __name__ == "__main__":
    # Test with various units
    test_units = [
        "Marine",
        "Battlecruiser",
        "SiegeTank",
        "Ghost",
        "Thor",
        "CommandCenter",
        "FusionCore"
    ]

    for unit in test_units:
        print_build_order(unit)

    # Demonstrate getting requirements programmatically
    print("\n" + "="*60)
    print("Programmatic Access Example")
    print("="*60)

    bc_requirements = get_build_requirements("Battlecruiser")
    print(f"\nBattlecruiser requirements:")
    print(f"  All buildings needed: {bc_requirements['buildings']}")
    print(f"  All units needed: {bc_requirements['units']}")
    print(f"  Direct requirements: {bc_requirements['immediate']}")

    # Show all available units
    print("\n" + "="*60)
    print("All Available Terran Units and Buildings")
    print("="*60)
    all_units = get_all_terran_units()
    for i, unit in enumerate(all_units, 1):
        print(f"{i:2d}. {unit}")
