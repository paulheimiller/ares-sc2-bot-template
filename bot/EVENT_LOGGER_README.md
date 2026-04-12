# EventLogger Documentation

## Overview

The `EventLogger` class captures comprehensive StarCraft 2 game state information using the Python-SC2 framework and exports it to JSON files. This enables detailed analysis of unit movement, behavior evaluation, and debugging of bot logic.

## Features

- Captures complete game state every frame (or at custom intervals)
- Exports detailed unit information including:
  - Position (2D and 3D coordinates)
  - Health, shields, and energy
  - Movement state (is_moving, is_attacking, is_idle)
  - Current orders and targets
  - Unit roles (from Ares framework)
- Tracks enemy units and structures
- Records map and terrain information
- Incremental export to prevent memory buildup
- JSON format for easy analysis with Python or other tools

## Integration

The EventLogger is already integrated into the `TankBot` class in [main.py](main.py).

### Initialization

```python
from bot.event_logger import EventLogger

# In your bot's __init__ or on_start
self.event_logger = EventLogger(self, output_dir="game_logs")
```

### Logging During Game

```python
async def on_step(self, iteration: int) -> None:
    # Log current frame
    self.event_logger.log_frame(iteration)

    # Export incrementally every 100 frames (optional)
    self.event_logger.export_incremental(interval=100)
```

### Export on Game End

```python
async def on_end(self, game_result) -> None:
    if self.event_logger:
        output_path = self.event_logger.export_to_json()
        print(f"Game state exported to: {output_path}")
```

## Output Format

The EventLogger exports JSON files with the following structure:

```json
{
  "session_id": "20260406_143022",
  "export_timestamp": "2026-04-06T14:35:18.123456",
  "total_frames": 1500,
  "frames": [
    {
      "iteration": 0,
      "game_time": 0.0,
      "timestamp": "2026-04-06T14:30:22.456789",
      "map_info": {
        "name": "AbyssalReefLE",
        "size": {"width": 200, "height": 176},
        "playable_area": {...},
        "start_locations": [...]
      },
      "player_info": {
        "minerals": 50,
        "vespene": 0,
        "supply_used": 12,
        "supply_cap": 15,
        "supply_left": 3,
        "worker_count": 12,
        "army_count": 0
      },
      "units": [
        {
          "tag": 12345678,
          "type_id": 48,
          "type_name": "MARINE",
          "position": {"x": 125.5, "y": 88.3},
          "position3d": {"x": 125.5, "y": 88.3, "z": 10.2},
          "health": 45,
          "health_max": 45,
          "health_percentage": 1.0,
          "is_moving": true,
          "is_attacking": false,
          "is_idle": false,
          "weapon_cooldown": 0.0,
          "facing": 2.35,
          "orders": [
            {
              "ability_id": 16,
              "ability_name": "Move",
              "target": {
                "type": "position",
                "x": 150.0,
                "y": 120.0
              },
              "progress": 0.5
            }
          ],
          "role": "CONTROL_GROUP_ONE"
        }
      ],
      "enemy_units": [...],
      "structures": [...],
      "terrain": {...}
    }
  ]
}
```

## Analysis Tools

### Basic Analysis Script

The included [analyze_movement.py](analyze_movement.py) script provides examples of how to analyze the logged data:

```bash
python bot/analyze_movement.py
```

This script demonstrates:
- Loading and parsing game state JSON
- Analyzing individual unit movement
- Analyzing army group coordination
- Detecting stutter-stepping behavior
- Calculating formation coherence

### Custom Analysis

You can write custom analysis scripts using the JSON output:

```python
import json

# Load game state
with open('game_logs/game_state_20260406_143022.json', 'r') as f:
    data = json.load(f)

# Analyze specific units
for frame in data['frames']:
    for unit in frame['units']:
        if unit['type_name'] == 'SIEGETANK':
            print(f"Tank at {unit['position']} - Moving: {unit['is_moving']}")
```

## Use Cases

### 1. Validate Unit Movement

Check if units are following their orders correctly:

```python
def check_movement_compliance(game_state, unit_tag):
    """Verify unit is moving toward its ordered target."""
    for frame in game_state['frames']:
        unit = find_unit(frame, unit_tag)
        if unit and unit['orders']:
            order = unit['orders'][0]
            if order['target']['type'] == 'position':
                target = order['target']
                # Check if unit is getting closer to target
                # ... analysis logic
```

### 2. Evaluate Army Coordination

Analyze if army groups are staying together:

```python
def check_formation_coherence(game_state):
    """Measure how well units maintain formation."""
    for frame in game_state['frames']:
        units = frame['units']
        # Calculate spread and coherence metrics
        # ... analysis logic
```

### 3. Debug Stutter-Step Behavior

Verify units are properly executing stutter-stepping:

```python
def verify_stutter_step(game_state, unit_tag):
    """Check if unit alternates between attacking and moving."""
    # Track is_moving and is_attacking flags
    # Detect proper attack-move-attack pattern
    # ... analysis logic
```

### 4. Performance Analysis

Identify performance bottlenecks:

```python
def analyze_frame_times(game_state):
    """Check for frame time irregularities."""
    timestamps = [frame['timestamp'] for frame in game_state['frames']]
    # Analyze time between frames
    # ... analysis logic
```

## Configuration Options

### Change Export Frequency

```python
# Export every 50 frames instead of 100
self.event_logger.export_incremental(interval=50)
```

### Disable Incremental Export

```python
# Only export at game end
async def on_step(self, iteration: int) -> None:
    self.event_logger.log_frame(iteration)
    # Don't call export_incremental
```

### Custom Output Directory

```python
self.event_logger = EventLogger(self, output_dir="my_custom_logs")
```

### Custom Filename

```python
# In on_end
output_path = self.event_logger.export_to_json(filename="my_game_log.json")
```

## Performance Considerations

1. **Memory Usage**: Logging every frame can consume significant memory. Use `export_incremental()` for long games.

2. **File Size**: A 10-minute game logged every frame can produce 10-50 MB JSON files depending on unit count.

3. **Logging Frequency**: For movement analysis, logging every frame is ideal. For general analysis, you can log every N frames:

```python
if iteration % 10 == 0:  # Log every 10 frames
    self.event_logger.log_frame(iteration)
```

## Data Fields Reference

### Unit Fields

| Field | Type | Description |
|-------|------|-------------|
| `tag` | int | Unique unit identifier |
| `type_id` | int | Unit type ID (from SC2) |
| `type_name` | str | Human-readable unit type |
| `position` | dict | 2D position {x, y} |
| `position3d` | dict | 3D position {x, y, z} |
| `health` | float | Current health |
| `health_max` | float | Maximum health |
| `is_moving` | bool | Whether unit is currently moving |
| `is_attacking` | bool | Whether unit is currently attacking |
| `is_idle` | bool | Whether unit is idle |
| `weapon_cooldown` | float | Weapon cooldown remaining |
| `facing` | float | Direction unit is facing (radians) |
| `orders` | list | Current order queue |
| `role` | str | Unit role from Ares framework |

### Order Fields

| Field | Type | Description |
|-------|------|-------------|
| `ability_id` | int | Ability/command ID |
| `ability_name` | str | Human-readable ability name |
| `target` | dict | Target information (position or unit tag) |
| `progress` | float | Order completion progress (0.0-1.0) |

## Troubleshooting

### No logs generated

- Check that `event_logger` is initialized in `on_start`
- Verify `log_frame()` is called in `on_step`
- Check that the output directory has write permissions

### Memory issues

- Reduce logging frequency (log every N frames)
- Use `export_incremental()` with a smaller interval
- Clear frame logs more frequently

### Large file sizes

- Reduce logging frequency
- Use incremental exports to create multiple smaller files
- Filter out unnecessary units before logging

## Examples

See [analyze_movement.py](analyze_movement.py) for complete examples of:
- Loading and parsing game state
- Analyzing individual unit paths
- Calculating group movement metrics
- Detecting movement patterns

## Advanced Usage

### Filter Specific Units

Modify `_capture_unit_states()` to only log specific unit types:

```python
def _capture_unit_states(self) -> List[Dict[str, Any]]:
    unit_states = []
    # Only log army units, not workers
    for unit in self.bot.units.filter(lambda u: not u.is_worker):
        # ... existing code
```

### Add Custom Fields

Extend the logger to capture additional information:

```python
def _capture_unit_states(self) -> List[Dict[str, Any]]:
    # ... existing code
    unit_state["custom_data"] = {
        "distance_to_target": calculate_distance(unit, target),
        "nearby_enemies": nearby_enemy_count,
    }
```

## Integration with Testing

Use EventLogger output for automated testing:

```python
def test_unit_movement():
    game_state = load_game_state('game_logs/test_run.json')
    movement_data = analyze_unit_movement(game_state, unit_tag=12345)

    assert movement_data['total_distance'] > 0, "Unit should have moved"
    assert movement_data['average_speed'] > 0.1, "Unit should maintain minimum speed"
```
