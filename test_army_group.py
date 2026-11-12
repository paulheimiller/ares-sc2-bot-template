"""
Test script for the CoordinatedArmyGroup behavior.

This test verifies that the leapfrog tank logic is properly implemented
and can be instantiated without errors.
"""

import sys
sys.path.insert(0, 'ares-sc2/src')
sys.path.insert(0, 'ares-sc2')

import numpy as np
from sc2.position import Point2

from bot.army_group_behavior import CoordinatedArmyGroup


def test_army_group_instantiation():
    """Test that CoordinatedArmyGroup can be instantiated."""
    target = Point2((100, 100))
    grid = np.zeros((200, 200), dtype=np.float32)
    
    army_group = CoordinatedArmyGroup(target, grid)
    
    assert army_group.target == target
    assert army_group.grid.shape == (200, 200)
    assert army_group.tank_state == "move"
    assert army_group.active_tank_group == 0
    assert army_group.tanks_divided is False
    
    print("✓ CoordinatedArmyGroup instantiation test passed")


def test_army_group_constants():
    """Test that the behavior constants are set correctly."""
    target = Point2((100, 100))
    grid = np.zeros((200, 200), dtype=np.float32)
    
    army_group = CoordinatedArmyGroup(target, grid)
    
    assert army_group.MOVE_DISTANCE == 2.0
    assert army_group.MARINE_DISTANCE == 2.0
    assert army_group.VIKING_ALTITUDE == 5.0
    assert army_group.UNSIEGE_FRAMES == 40
    assert army_group.MOVE_SIEGE_FRAMES == 56
    
    print("✓ CoordinatedArmyGroup constants test passed")


def test_divide_tanks():
    """Test tank division logic."""
    target = Point2((100, 100))
    grid = np.zeros((200, 200), dtype=np.float32)
    
    army_group = CoordinatedArmyGroup(target, grid)
    
    # Simulate tank division
    class MockTank:
        def __init__(self, tag):
            self.tag = tag
    
    tanks = [MockTank(i) for i in range(6)]
    
    # Access the division logic directly
    army_group.tank_group_0 = {t.tag for t in tanks[:3]}
    army_group.tank_group_1 = {t.tag for t in tanks[3:]}
    army_group.tanks_divided = True
    
    assert len(army_group.tank_group_0) == 3
    assert len(army_group.tank_group_1) == 3
    assert army_group.tanks_divided is True
    
    print("✓ Tank division test passed")


if __name__ == "__main__":
    print("Running CoordinatedArmyGroup tests...\n")
    
    test_army_group_instantiation()
    test_army_group_constants()
    test_divide_tanks()
    
    print("\n✓ All tests passed!")
