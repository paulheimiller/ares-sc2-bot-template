# Tank Leapfrog Movement - Bug Fixes

## Issues Found

### 1. **Movement Distance Too Small**
- **Problem**: Tanks were moving only 2 tiles at a time
- **Spec Requirement**: Tanks should move the same distance as their firing range (13 tiles for sieged tanks)
- **Fix**: Changed `MOVE_DISTANCE` from 2.0 to 13.0 in [army_group_behavior.py:30](bot/army_group_behavior.py#L30)

### 2. **State Transition Timing Increased**
- **Problem**: `MOVE_SIEGE_FRAMES` was too short (56 frames) for 13-tile movement
- **Fix**: Increased to 120 frames (~11 seconds) to allow tanks to travel 13 tiles and complete siege animation

### 3. **Critical: State Transition Counter Bug**
- **Problem**: When transitioning states, `frames_since_state_change` was reset to 0, but then immediately incremented to 1 in the same frame. This meant on the next frame, the counter was 1 (not 0), so move commands were never issued for alternating groups!
- **Symptoms**:
  - Only Group 0 issued move commands
  - Group 1 would enter "move" state but never actually move
  - Tanks appeared stuck, distance stopped decreasing
- **Fix**: Modified `_move_tanks_leapfrog()` to return `True` when a state transition occurs, and updated `execute()` to skip incrementing the counter when a transition happens
- **Files Changed**:
  - [army_group_behavior.py:139-263](bot/army_group_behavior.py#L139-L263) - Added return value
  - [army_group_behavior.py:116-124](bot/army_group_behavior.py#L116-L124) - Conditional counter increment

### 4. **Queued Move Commands for Sieged Tanks**
- **Problem**: When entering "move" state, if tanks were still sieged, the code would only unsiege them without issuing move commands
- **Fix**: Added queued move and siege commands after unsiege: `tank(UNSIEGE) -> tank.move(target, queue=True) -> tank(SIEGE, queue=True)`
- **Location**: [army_group_behavior.py:237-242](bot/army_group_behavior.py#L237-L242)

### 5. **Enemy Detection and Auto-Siege**
- **Added Feature**: When enemy units are detected within 15 tiles of tank center, ALL tanks immediately siege and attack
- **Spec Compliance**: "when any enemy units are detected within range of army group, then all tanks should stop moving and siege up, and fire at enemy units"
- **Location**: [army_group_behavior.py:154-169](bot/army_group_behavior.py#L154-L169)

### 6. **EventLogger Incremental Export Bug**
- **Problem**: Incremental exports were overwriting the same filename because frame count was reset after each export
- **Fix**: Added `total_frames_exported` counter to track cumulative frames and generate unique filenames
- **Files Changed**: [event_logger.py:40, 303-318](bot/event_logger.py)

## Testing Changes

### Unit Counts Reduced for Faster Testing
- Marines: 20 → 4
- Siege Tanks: 6 → 4
- Vikings: 6 → 0 (skipped for faster testing)
- **Location**: [main.py:39-44](bot/main.py#L39-L44)

### Logging Frequency Reduced
- Changed from every frame to every 10 frames
- Incremental export interval: 100 → 200 frames
- **Location**: [main.py:72-75](bot/main.py#L72-L75)

## Expected Behavior After Fixes

1. **Leapfrog Pattern**: Tanks alternate between two groups
   - Group 0 moves 13 tiles → sieges
   - Group 1 unsieges → moves 13 tiles → sieges
   - Group 0 unsieges → moves 13 tiles → sieges
   - (Repeat)

2. **State Machine Flow**:
   ```
   Group 0: move (120 frames) → Group 1: move/unsiege
   Group 1: move (120 frames) → Group 0: unsiege
   Group 0: unsiege (40 frames) → move
   ```

3. **Enemy Engagement**: When enemies detected within 15 tiles:
   - All tanks siege immediately
   - Sieged tanks attack nearest enemy
   - Movement stops until enemies leave range

4. **Progressive Movement**: Army should steadily advance toward enemy base, with distance decreasing by ~13 tiles per leapfrog cycle

## Verification

Run the bot and check console output for:
- `[Tank] Group X: Y tanks → (target)` messages for BOTH groups
- Distance value decreasing over time (not stuck at same value)
- State transitions: `[Tank] → Group X, state=move/unsiege`
- Tank position changes in EventLogger output

Analyze with:
```bash
python analyze_tank_leapfrog.py  # Custom analysis script
python bot/analyze_movement.py    # General movement analysis
```
