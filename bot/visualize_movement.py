"""
Optional visualization script for unit movement using matplotlib.

This script creates visual plots of unit movement paths from EventLogger data.
Requires matplotlib to be installed: pip install matplotlib
"""

try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("matplotlib not available. Install with: pip install matplotlib")

import json
from pathlib import Path
from typing import Dict, List, Any


def load_game_state(json_path: str) -> Dict[str, Any]:
    """Load game state from JSON file."""
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def plot_unit_path(game_state: Dict[str, Any], unit_tag: int, save_path: str = None):
    """
    Plot the movement path of a specific unit.

    Parameters
    ----------
    game_state : Dict[str, Any]
        Loaded game state from EventLogger
    unit_tag : int
        Tag of the unit to visualize
    save_path : str, optional
        Path to save the plot image
    """
    if not MATPLOTLIB_AVAILABLE:
        print("matplotlib is required for visualization")
        return

    frames = game_state.get('frames', [])
    positions = []
    moving_states = []

    # Extract positions for the unit
    for frame in frames:
        units = frame.get('units', [])
        unit = next((u for u in units if u['tag'] == unit_tag), None)

        if unit:
            pos = unit['position']
            positions.append((pos['x'], pos['y']))
            moving_states.append(unit.get('is_moving', False))

    if not positions:
        print(f"No data found for unit {unit_tag}")
        return

    # Create plot
    fig, ax = plt.subplots(figsize=(12, 10))

    # Extract x and y coordinates
    x_coords = [p[0] for p in positions]
    y_coords = [p[1] for p in positions]

    # Plot the path
    ax.plot(x_coords, y_coords, 'b-', alpha=0.3, linewidth=1, label='Path')

    # Color points based on movement state
    for i, (x, y, is_moving) in enumerate(zip(x_coords, y_coords, moving_states)):
        color = 'green' if is_moving else 'red'
        ax.scatter(x, y, c=color, s=20, alpha=0.6, zorder=5)

    # Mark start and end points
    ax.scatter(x_coords[0], y_coords[0], c='blue', s=200, marker='o',
               label='Start', edgecolors='black', linewidths=2, zorder=10)
    ax.scatter(x_coords[-1], y_coords[-1], c='purple', s=200, marker='s',
               label='End', edgecolors='black', linewidths=2, zorder=10)

    # Get map info for boundaries
    if frames:
        map_info = frames[0].get('map_info', {})
        map_size = map_info.get('size', {})
        if map_size:
            ax.set_xlim(0, map_size.get('width', 200))
            ax.set_ylim(0, map_size.get('height', 200))

    ax.set_xlabel('X Position')
    ax.set_ylabel('Y Position')
    ax.set_title(f'Unit Movement Path (Tag: {unit_tag})\nGreen=Moving, Red=Stationary')
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_aspect('equal')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Plot saved to: {save_path}")
    else:
        plt.show()


def plot_army_formation(game_state: Dict[str, Any], frame_iteration: int, save_path: str = None):
    """
    Plot the army formation at a specific frame.

    Parameters
    ----------
    game_state : Dict[str, Any]
        Loaded game state from EventLogger
    frame_iteration : int
        The iteration/frame number to visualize
    save_path : str, optional
        Path to save the plot image
    """
    if not MATPLOTLIB_AVAILABLE:
        print("matplotlib is required for visualization")
        return

    frames = game_state.get('frames', [])

    # Find the frame
    frame = next((f for f in frames if f['iteration'] == frame_iteration), None)

    if not frame:
        print(f"Frame {frame_iteration} not found")
        return

    # Create plot
    fig, ax = plt.subplots(figsize=(14, 12))

    # Plot friendly units
    units = frame.get('units', [])
    for unit in units:
        pos = unit['position']
        type_name = unit.get('type_name', 'Unknown')

        # Different colors for different unit types
        color_map = {
            'MARINE': 'blue',
            'SIEGETANK': 'red',
            'SIEGETANKSIEGED': 'darkred',
            'VIKINGFIGHTER': 'cyan',
        }
        color = color_map.get(type_name, 'gray')

        # Different markers based on state
        marker = '^' if unit.get('is_moving') else 'o'

        ax.scatter(pos['x'], pos['y'], c=color, s=100, marker=marker,
                   alpha=0.7, edgecolors='black', linewidths=1,
                   label=type_name if type_name not in [l.get_label() for l in ax.lines] else "")

        # Draw facing direction
        facing = unit.get('facing', 0)
        import math
        dx = math.cos(facing) * 2
        dy = math.sin(facing) * 2
        ax.arrow(pos['x'], pos['y'], dx, dy, head_width=0.5,
                 head_length=0.5, fc=color, ec=color, alpha=0.5)

    # Plot enemy units
    enemy_units = frame.get('enemy_units', [])
    for unit in enemy_units:
        pos = unit['position']
        ax.scatter(pos['x'], pos['y'], c='orange', s=150, marker='*',
                   alpha=0.8, edgecolors='red', linewidths=2,
                   label='Enemy' if 'Enemy' not in [l.get_label() for l in ax.lines] else "")

    # Get map info
    map_info = frame.get('map_info', {})
    map_size = map_info.get('size', {})
    if map_size:
        ax.set_xlim(0, map_size.get('width', 200))
        ax.set_ylim(0, map_size.get('height', 200))

    # Plot start locations
    start_locs = map_info.get('start_locations', [])
    for loc in start_locs:
        ax.scatter(loc['x'], loc['y'], c='yellow', s=300, marker='H',
                   alpha=0.5, edgecolors='black', linewidths=2)

    ax.set_xlabel('X Position')
    ax.set_ylabel('Y Position')
    ax.set_title(f'Army Formation at Frame {frame_iteration}\n'
                 f'Time: {frame.get("game_time", 0):.1f}s | '
                 f'Units: {len(units)} | Enemies: {len(enemy_units)}')
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)
    ax.set_aspect('equal')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Plot saved to: {save_path}")
    else:
        plt.show()


def create_movement_animation(game_state: Dict[str, Any], output_dir: str = "movement_plots"):
    """
    Create a series of images showing army movement over time.

    Parameters
    ----------
    game_state : Dict[str, Any]
        Loaded game state from EventLogger
    output_dir : str
        Directory to save plot images
    """
    if not MATPLOTLIB_AVAILABLE:
        print("matplotlib is required for visualization")
        return

    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    frames = game_state.get('frames', [])

    # Create plots for every Nth frame
    step = max(1, len(frames) // 20)  # Create ~20 images

    for i in range(0, len(frames), step):
        frame = frames[i]
        iteration = frame['iteration']
        save_path = output_path / f"frame_{iteration:05d}.png"
        plot_army_formation(game_state, iteration, save_path=str(save_path))
        plt.close()

    print(f"\nCreated {len(range(0, len(frames), step))} images in {output_dir}/")
    print(f"You can create a video with ffmpeg:")
    print(f"  ffmpeg -framerate 2 -pattern_type glob -i '{output_dir}/frame_*.png' -c:v libx264 movement.mp4")


def main():
    """Example usage of visualization functions."""
    if not MATPLOTLIB_AVAILABLE:
        print("Please install matplotlib: pip install matplotlib")
        return

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
    print(f"\nVisualizing: {latest_file}")

    # Load game state
    game_state = load_game_state(str(latest_file))

    print(f"Total frames: {game_state.get('total_frames', 0)}")

    # Example 1: Plot individual unit path
    if game_state.get('frames'):
        first_frame = game_state['frames'][0]
        if first_frame.get('units'):
            first_unit_tag = first_frame['units'][0]['tag']
            print(f"\nPlotting path for unit {first_unit_tag}...")
            plot_unit_path(game_state, first_unit_tag, save_path='unit_path.png')

    # Example 2: Plot formation at a specific frame
    if len(game_state.get('frames', [])) > 100:
        mid_frame_idx = len(game_state['frames']) // 2
        mid_frame_iteration = game_state['frames'][mid_frame_idx]['iteration']
        print(f"\nPlotting army formation at frame {mid_frame_iteration}...")
        plot_army_formation(game_state, mid_frame_iteration, save_path='army_formation.png')

    # Example 3: Create animation frames
    print("\nCreating movement animation frames...")
    create_movement_animation(game_state, output_dir="movement_plots")

    print("\nVisualization complete!")


if __name__ == '__main__':
    main()
