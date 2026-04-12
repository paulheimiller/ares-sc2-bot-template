# Ralph Fix Plan

## High Priority
- [x] Fix CoordinatedArmyGroup not executing each frame (behavior only registered once, not per step)
- [x] Fix CoordinatedArmyGroup inheriting from Protocol+ABC (incorrect, removed inheritance)
- [x] Fix execute() missing return bool (Protocol requires bool return)

## Medium Priority
- [x] Improve leapfrog tank state machine (proper "move"/"unsiege" 2-state machine; orders issued once per state entry; smart first-cycle handling)
- [x] Reduce excessive debug print spam (reduced to periodic ~5s interval summary)
- [x] Supply management: fixed threshold 50→6 in build_workers, 2→4 in _build_required_structures (standard ~6 supply headroom for 14s build time)

## Low Priority
- [x] Re-enable Vikings in unit_orders once core army behavior is stable
- [x] Add attack-move fallback when army reaches enemy base
- [x] Handle edge case: what if tanks are destroyed and groups become unbalanced
- [x] Fix: state machine counter advancing during enemy engagement (tanks freeze after combat)

## Completed
- [x] Project initialization
- [x] Basic bot structure (TankBot with Marines + Siege Tanks)
- [x] Tech tree build order system (terran_tech_tree.py)
- [x] Army group behavior framework (CoordinatedArmyGroup)
- [x] Leapfrog tank movement skeleton
- [x] Fix army group behavior registration bug

## Notes
- This is a SC2 bot using ares-sc2 framework (Terran TankBot)
- Behaviors must be registered every step to execute every frame - critical design constraint
- ares-sc2 Behavior is a Protocol, not an ABC - implement the interface, don't inherit it
- The leapfrog pattern: Group A moves while Group B is sieged, then swap
