"""
Example script to analyze unit movement from EventLogger JSON output.

This script demonstrates how to load and analyze the game state logs
to evaluate whether units are moving correctly.
"""

import json
from pathlib import Path
from typing import Dict, List, Any
import math


def load_game_state(json_path: str) -> Dict[str, Any]:
    """Load game state from JSON file."""
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def calculate_distance(pos1: Dict[str, float], pos2: Dict[str, float]) -> float:
    """Calculate Euclidean distance between two positions."""
    dx = pos1['x'] - pos2['x']
    dy = pos1['y'] - pos2['y']
    return math.sqrt(dx * dx + dy * dy)


def analyze_unit_movement(game_state: Dict[str, Any], unit_tag: int) -> Dict[str, Any]:
    """
    Analyze movement for a specific unit across all frames.

    Parameters
    ----------
    game_state : Dict[str, Any]
        Loaded game state from EventLogger
    unit_tag : int
        The tag of the unit to analyze

    Returns
    -------
    Dict[str, Any]
        Movement analysis including path, distances, and orders
    """
    frames = game_state.get('frames', [])

    movement_data = {
        'unit_tag': unit_tag,
        'positions': [],
        'orders': [],
        'total_distance': 0.0,
        'average_speed': 0.0,
        'frames_tracked': 0,
    }

    previous_pos = None

    for frame in frames:
        units = frame.get('units', [])

        # Find the unit in this frame
        unit = next((u for u in units if u['tag'] == unit_tag), None)

        if unit:
            current_pos = unit['position']
            movement_data['positions'].append({
                'iteration': frame['iteration'],
                'position': current_pos,
                'is_moving': unit.get('is_moving', False),
                'is_attacking': unit.get('is_attacking', False),
                'is_idle': unit.get('is_idle', False),
            })

            # Track orders
            if unit.get('orders'):
                for order in unit['orders']:
                    movement_data['orders'].append({
                        'iteration': frame['iteration'],
                        'ability': order.get('ability_name', 'Unknown'),
                        'target': order.get('target'),
                        'progress': order.get('progress', 0),
                    })

            # Calculate distance traveled
            if previous_pos:
                distance = calculate_distance(previous_pos, current_pos)
                movement_data['total_distance'] += distance

            previous_pos = current_pos
            movement_data['frames_tracked'] += 1

    # Calculate average speed (distance per frame)
    if movement_data['frames_tracked'] > 1:
        movement_data['average_speed'] = (
            movement_data['total_distance'] / movement_data['frames_tracked']
        )

    return movement_data


def analyze_army_group_movement(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze movement of all army units as a group.

    Parameters
    ----------
    game_state : Dict[str, Any]
        Loaded game state from EventLogger

    Returns
    -------
    Dict[str, Any]
        Group movement analysis including formation coherence
    """
    frames = game_state.get('frames', [])

    group_analysis = {
        'unit_count': 0,
        'average_position_per_frame': [],
        'formation_spread': [],
        'units_moving_together': [],
    }

    for frame in frames:
        units = frame.get('units', [])

        if not units:
            continue

        # Calculate centroid (average position)
        total_x = sum(u['position']['x'] for u in units)
        total_y = sum(u['position']['y'] for u in units)
        count = len(units)

        centroid = {
            'x': total_x / count,
            'y': total_y / count,
        }

        # Calculate spread (average distance from centroid)
        spread = sum(
            calculate_distance(u['position'], centroid)
            for u in units
        ) / count

        # Count moving units
        moving_count = sum(1 for u in units if u.get('is_moving', False))

        group_analysis['average_position_per_frame'].append({
            'iteration': frame['iteration'],
            'centroid': centroid,
            'unit_count': count,
        })

        group_analysis['formation_spread'].append({
            'iteration': frame['iteration'],
            'spread': spread,
        })

        group_analysis['units_moving_together'].append({
            'iteration': frame['iteration'],
            'moving_count': moving_count,
            'total_count': count,
            'percentage': (moving_count / count * 100) if count > 0 else 0,
        })

    group_analysis['unit_count'] = count if frames else 0

    return group_analysis


def detect_stutter_stepping(movement_data: Dict[str, Any], threshold: float = 0.5) -> List[Dict[str, Any]]:
    """
    Detect potential stutter-stepping behavior (alternating between moving and stopping).

    Parameters
    ----------
    movement_data : Dict[str, Any]
        Movement data from analyze_unit_movement
    threshold : float
        Minimum distance to consider as actual movement

    Returns
    -------
    List[Dict[str, Any]]
        List of detected stutter-step patterns
    """
    positions = movement_data.get('positions', [])
    stutter_events = []

    for i in range(1, len(positions) - 1):
        prev_pos = positions[i - 1]
        curr_pos = positions[i]
        next_pos = positions[i + 1]

        # Calculate movement between frames
        dist_to_curr = calculate_distance(prev_pos['position'], curr_pos['position'])
        dist_from_curr = calculate_distance(curr_pos['position'], next_pos['position'])

        # Detect stutter: moved, then stopped, then moved again
        if (dist_to_curr > threshold and
            curr_pos.get('is_idle', False) and
            dist_from_curr > threshold):
            stutter_events.append({
                'iteration': curr_pos['iteration'],
                'position': curr_pos['position'],
            })

    return stutter_events


def main():
    """Example usage of movement analysis functions."""
    # Find the most recent game state file
    log_dir = Path('game_logs')

    if not log_dir.exists():
        print("No game_logs directory found. Run the bot first to generate logs.")
        return

    json_files = list(log_dir.glob('game_state_*.json'))

    if not json_files:
        print("No game state files found in game_logs/")
        return

    # Use the most recent file
    latest_file = max(json_files, key=lambda p: p.stat().st_mtime)
    print(f"\nAnalyzing: {latest_file}")

    # Load game state
    game_state = load_game_state(str(latest_file))

    print(f"\nGame State Summary:")
    print(f"  Session ID: {game_state.get('session_id')}")
    print(f"  Total frames: {game_state.get('total_frames', 0)}")

    # Analyze army group movement
    print("\n=== Army Group Movement Analysis ===")
    group_analysis = analyze_army_group_movement(game_state)
    print(f"Total units tracked: {group_analysis['unit_count']}")

    if group_analysis['formation_spread']:
        avg_spread = sum(f['spread'] for f in group_analysis['formation_spread']) / len(group_analysis['formation_spread'])
        print(f"Average formation spread: {avg_spread:.2f}")

    # Example: Analyze first unit in first frame
    if game_state.get('frames'):
        first_frame = game_state['frames'][0]
        if first_frame.get('units'):
            first_unit_tag = first_frame['units'][0]['tag']
            print(f"\n=== Individual Unit Analysis (Tag: {first_unit_tag}) ===")

            unit_movement = analyze_unit_movement(game_state, first_unit_tag)
            print(f"Frames tracked: {unit_movement['frames_tracked']}")
            print(f"Total distance traveled: {unit_movement['total_distance']:.2f}")
            print(f"Average speed: {unit_movement['average_speed']:.4f} units/frame")

            # Detect stutter stepping
            stutter_events = detect_stutter_stepping(unit_movement)
            print(f"Stutter-step events detected: {len(stutter_events)}")

    print("\n=== Analysis Complete ===\n")


if __name__ == '__main__':
    main()
