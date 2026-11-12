"""Deterministic match runner for the bot-dev loop.

Usage:
    python dev_run.py [--map AcropolisAIE] [--opp terran|zerg|protoss] [--diff easy|medium]
Exits 0 on Victory, 1 otherwise. Prints RESULT: line last.
"""
import argparse
import sys
from pathlib import Path

sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")

from sc2 import maps
from sc2.data import AIBuild, Difficulty, Race, Result
from sc2.main import run_game
from sc2.player import Bot, Computer

from bot.main import MyBot


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default="AcropolisAIE")
    ap.add_argument("--opp", default="terran", choices=["terran", "zerg", "protoss"])
    ap.add_argument("--diff", default="easy", choices=["easy", "medium", "hard"])
    args = ap.parse_args()

    opp_race = Race[args.opp.title()]
    diff = Difficulty[args.diff.title()]

    players = [
        Bot(Race.Terran, MyBot(), "MyBot"),
        Computer(opp_race, diff, ai_build=AIBuild.Macro),
    ]
    print(f"[dev_run] map={args.map} opp={args.opp}/{args.diff}", flush=True)
    result = run_game(maps.get(args.map), players, realtime=False)
    won = result == Result.Victory
    print(f"RESULT: {'WON' if won else 'LOST'} ({result})", flush=True)
    return 0 if won else 1


if __name__ == "__main__":
    sys.exit(main())
