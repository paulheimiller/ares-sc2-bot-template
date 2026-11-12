"""One-shot map geometry probe: dump pathing grid + neutrals around our base."""
import sys
from pathlib import Path

sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")

import numpy as np
from sc2 import maps
from sc2.main import run_game
from sc2.player import Bot, Computer

from bot.main import MyBot


class ProbeBot(MyBot):
    async def on_step(self, iteration: int) -> None:
        await super(ProbeBot, self).on_step(iteration)
        if iteration == 30:
            gi = self.game_info
            g = gi.pathing_grid.data_numpy.T
            import sys as _sys
            print("[MAPPROBE] state attrs:", [a for a in dir(self.state) if 'unit' in a.lower()], file=_sys.stderr, flush=True)
            print("[MAPPROBE] ai attrs:", [a for a in dir(self) if ('unit' in a.lower() or 'neut' in a.lower()) and not a.startswith('_')], file=_sys.stderr, flush=True)
            out = Path("game_logs/map_probe.txt")
            lines = [f"shape={g.shape}"]
            cc = list(self.townhalls)[0].position
            lines.append(f"CC=({cc.x:.1f},{cc.y:.1f}) start={self.start_location}")
            # render x 24..64, y 108..146
            lines.append("     " + "".join(str((x // 10) % 10) for x in range(24, 64)))
            for y in range(146, 107, -1):
                row = ""
                for x in range(24, 64):
                    v = bool(g[y][x]) if y < g.shape[0] and x < g.shape[1] else False
                    row += "#" if v else "."
                lines.append(f"{y:>3} {row}")
            lines.append("--- neutrals (x<80 or y>80 corner near us) ---")
            for u in self.all_units:
                try:
                    if u.alliance != 3:
                        continue
                except Exception:
                    continue
                p = u.position
                if p.x < 90 and p.y > 60:
                    lines.append(f"{str(u.type_id):<28} ({p.x:.1f},{p.y:.1f})")
            out.write_text("\n".join(lines))
            print("[MAPPROBE] written", out, flush=True)
            try:
                await self._client.debug_leave()
            except Exception:
                pass


def main():
    from sc2.data import AIBuild, Difficulty, Race, Result
    result = run_game(maps.get("AcropolisAIE"),
                      [Bot(Race.Terran, ProbeBot(), "Probe"),
                       Computer(Race.Terran, Difficulty.Easy, ai_build=AIBuild.Macro)],
                      realtime=False)
    return 0 if result == Result.Victory else 1


if __name__ == "__main__":
    sys.exit(main())
