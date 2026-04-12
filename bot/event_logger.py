import json
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Any
from datetime import datetime

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

if TYPE_CHECKING:
    from ares import AresBot


class EventLogger:
    """
    Captures StarCraft 2 game state for unit movement evaluation.

    Exports comprehensive unit and map state to JSON files that can be used
    to analyze whether units are moving correctly and following orders.
    """

    def __init__(self, bot: "AresBot", output_dir: str = "game_logs"):
        """
        Initialize the EventLogger.

        Parameters
        ----------
        bot : AresBot
            The bot instance to query for game state
        output_dir : str
            Directory to save log files (default: "game_logs")
        """
        self.bot = bot
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        # Create a unique session ID based on timestamp
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.frame_logs: List[Dict[str, Any]] = []
        self.total_frames_exported = 0

    def capture_game_state(self, iteration: int) -> Dict[str, Any]:
        """
        Capture the current game state including units, map info, and orders.

        Parameters
        ----------
        iteration : int
            Current game iteration/frame number

        Returns
        -------
        Dict[str, Any]
            Complete game state snapshot
        """
        game_state = {
            "iteration": iteration,
            "game_time": self.bot.time,
            "timestamp": datetime.now().isoformat(),
            "map_info": self._capture_map_info(),
            "player_info": self._capture_player_info(),
            "units": self._capture_unit_states(),
            "enemy_units": self._capture_enemy_unit_states(),
            "structures": self._capture_structure_states(),
            "terrain": self._capture_terrain_info(),
        }

        return game_state

    def _capture_map_info(self) -> Dict[str, Any]:
        """Capture map-level information."""
        return {
            "name": self.bot.game_info.map_name,
            "size": {
                "width": self.bot.game_info.map_size.width,
                "height": self.bot.game_info.map_size.height,
            },
            "playable_area": {
                "x_min": self.bot.game_info.playable_area.x,
                "y_min": self.bot.game_info.playable_area.y,
                "width": self.bot.game_info.playable_area.width,
                "height": self.bot.game_info.playable_area.height,
            },
            "start_locations": [
                {"x": pos.x, "y": pos.y}
                for pos in self.bot.enemy_start_locations
            ],
        }

    def _capture_player_info(self) -> Dict[str, Any]:
        """Capture player-level information."""
        return {
            "minerals": self.bot.minerals,
            "vespene": self.bot.vespene,
            "supply_used": self.bot.supply_used,
            "supply_cap": self.bot.supply_cap,
            "supply_left": self.bot.supply_left,
            "worker_count": self.bot.workers.amount,
            "army_count": self.bot.supply_army,
        }

    def _capture_unit_states(self) -> List[Dict[str, Any]]:
        """
        Capture detailed state for all friendly units.

        Returns comprehensive information needed to evaluate unit movement.
        """
        unit_states = []

        for unit in self.bot.units:
            unit_state = {
                "tag": unit.tag,
                "type_id": unit.type_id.value,
                "type_name": unit.type_id.name,
                "position": {"x": unit.position.x, "y": unit.position.y},
                "position3d": {"x": unit.position3d.x, "y": unit.position3d.y, "z": unit.position3d.z},
                "health": unit.health,
                "health_max": unit.health_max,
                "health_percentage": unit.health_percentage,
                "shield": unit.shield,
                "shield_max": unit.shield_max,
                "energy": unit.energy,
                "energy_max": unit.energy_max,
                "is_moving": unit.is_moving,
                "is_attacking": unit.is_attacking,
                "is_idle": unit.is_idle,
                "is_selected": unit.is_selected,
                "weapon_cooldown": unit.weapon_cooldown,
                "facing": unit.facing,
                "radius": unit.radius,
                "is_flying": unit.is_flying,
                "is_burrowed": unit.is_burrowed,
                "is_powered": unit.is_powered,
                "is_active": unit.is_active,
                "cargo_used": unit.cargo_used if hasattr(unit, "cargo_used") else 0,
                "cargo_max": unit.cargo_max if hasattr(unit, "cargo_max") else 0,
            }

            # Capture current orders
            if unit.orders:
                unit_state["orders"] = [
                    {
                        "ability_id": order.ability.id.value,
                        "ability_name": order.ability.button_name,
                        "target": self._serialize_target(order.target),
                        "progress": order.progress,
                    }
                    for order in unit.orders
                ]
            else:
                unit_state["orders"] = []

            # Add role information if available (from Ares framework)
            if hasattr(self.bot, "mediator"):
                try:
                    role = self.bot.mediator.get_unit_role_dict.get(unit.tag)
                    if role:
                        unit_state["role"] = role.name
                except Exception:
                    unit_state["role"] = None

            unit_states.append(unit_state)

        return unit_states

    def _capture_enemy_unit_states(self) -> List[Dict[str, Any]]:
        """Capture state for all visible enemy units."""
        enemy_states = []

        for unit in self.bot.enemy_units:
            enemy_state = {
                "tag": unit.tag,
                "type_id": unit.type_id.value,
                "type_name": unit.type_id.name,
                "position": {"x": unit.position.x, "y": unit.position.y},
                "health": unit.health,
                "health_max": unit.health_max,
                "health_percentage": unit.health_percentage,
                "shield": unit.shield,
                "is_flying": unit.is_flying,
                "is_visible": unit.is_visible,
                "is_snapshot": unit.is_snapshot,
            }
            enemy_states.append(enemy_state)

        return enemy_states

    def _capture_structure_states(self) -> List[Dict[str, Any]]:
        """Capture state for all friendly structures."""
        structure_states = []

        for structure in self.bot.structures:
            structure_state = {
                "tag": structure.tag,
                "type_id": structure.type_id.value,
                "type_name": structure.type_id.name,
                "position": {"x": structure.position.x, "y": structure.position.y},
                "health": structure.health,
                "health_max": structure.health_max,
                "is_ready": structure.is_ready,
                "is_idle": structure.is_idle,
                "build_progress": structure.build_progress,
                "is_powered": structure.is_powered if hasattr(structure, "is_powered") else True,
            }

            # Capture add-ons for production structures
            if hasattr(structure, "add_on_tag") and structure.add_on_tag:
                structure_state["has_addon"] = True
                structure_state["addon_tag"] = structure.add_on_tag

            structure_states.append(structure_state)

        return structure_states

    def _capture_terrain_info(self) -> Dict[str, Any]:
        """Capture terrain-related information."""
        return {
            "expansion_locations": [
                {"x": pos.x, "y": pos.y}
                for pos in self.bot.expansion_locations_list
            ],
            "vision_blockers": [
                {"x": p.x, "y": p.y}
                for p in self.bot.game_info.vision_blockers
            ] if hasattr(self.bot.game_info, "vision_blockers") else [],
        }

    def _serialize_target(self, target: Any) -> Dict[str, Any]:
        """
        Serialize order target which can be a Point2, unit tag, or None.

        Parameters
        ----------
        target : Any
            The order target to serialize

        Returns
        -------
        Dict[str, Any]
            Serialized target information
        """
        if target is None:
            return {"type": "none"}
        elif isinstance(target, Point2):
            return {
                "type": "position",
                "x": target.x,
                "y": target.y,
            }
        elif isinstance(target, int):
            return {
                "type": "unit_tag",
                "tag": target,
            }
        else:
            return {
                "type": "unknown",
                "value": str(target),
            }

    def log_frame(self, iteration: int) -> None:
        """
        Log the current frame's game state.

        Parameters
        ----------
        iteration : int
            Current game iteration number
        """
        game_state = self.capture_game_state(iteration)
        self.frame_logs.append(game_state)

    def export_to_json(self, filename: str = None) -> str:
        """
        Export all logged frames to a JSON file.

        Parameters
        ----------
        filename : str, optional
            Custom filename for the export. If None, generates a filename
            based on session_id and timestamp.

        Returns
        -------
        str
            Path to the exported file
        """
        if filename is None:
            filename = f"game_state_{self.session_id}.json"

        output_path = self.output_dir / filename

        export_data = {
            "session_id": self.session_id,
            "export_timestamp": datetime.now().isoformat(),
            "total_frames": len(self.frame_logs),
            "frames": self.frame_logs,
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        return str(output_path)

    def export_incremental(self, interval: int = 100) -> None:
        """
        Export logs incrementally every N frames to avoid memory buildup.

        Parameters
        ----------
        interval : int
            Number of frames between exports (default: 100)
        """
        if len(self.frame_logs) >= interval:
            start_frame = self.total_frames_exported
            end_frame = start_frame + len(self.frame_logs)
            filename = f"game_state_{self.session_id}_frames_{start_frame}_{end_frame}.json"
            path = self.export_to_json(filename)
            print(f"EventLogger: Exported frames {start_frame}-{end_frame} to {path}")
            # Update counter and clear logs to free memory
            self.total_frames_exported = end_frame
            self.frame_logs.clear()

    def get_summary_stats(self) -> Dict[str, Any]:
        """
        Get summary statistics from logged frames.

        Returns
        -------
        Dict[str, Any]
            Summary statistics about logged frames
        """
        if not self.frame_logs:
            return {"total_frames": 0}

        latest_frame = self.frame_logs[-1]

        return {
            "total_frames": len(self.frame_logs),
            "latest_iteration": latest_frame.get("iteration"),
            "latest_game_time": latest_frame.get("game_time"),
            "total_units": len(latest_frame.get("units", [])),
            "total_enemy_units": len(latest_frame.get("enemy_units", [])),
            "total_structures": len(latest_frame.get("structures", [])),
        }
