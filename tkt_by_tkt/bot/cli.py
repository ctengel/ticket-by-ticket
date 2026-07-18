"""tbt-bot console entry point

tbt-bot auto   --server URL --game ID [--name N | --player P --token T] ...
tbt-bot advise --server URL --game ID --player P --token T [--json] [--watch]

Both modes share the knob flags; --profile picks a preset and any
explicit knob flag overrides it. The bot never creates or starts games:
in auto mode it joins and waits for someone to POST /start.
"""

import argparse
import dataclasses
import random
import sys

from . import advisor
from .brain import HeuristicBrain
from .client import Client
from .knobs import PRESETS, Knobs
from .runner import BotStuck, Runner

KNOB_FLAGS = [field.name for field in dataclasses.fields(Knobs)]


def _add_common(parser):
    parser.add_argument("--server", required=True,
                        help="base URL, e.g. http://127.0.0.1:8080")
    parser.add_argument("--game", required=True, help="game ID")
    parser.add_argument("--profile", choices=sorted(PRESETS), default="hard",
                        help="knob preset (default: hard)")
    for name in KNOB_FLAGS:
        parser.add_argument("--" + name.replace("_", "-"), type=float,
                            default=None, help="override the %s knob" % name)
    parser.add_argument("--seed", type=int, default=None,
                        help="seed the RNG for reproducible decisions")
    parser.add_argument("--poll", type=float, default=None,
                        help="seconds between state polls")


def _knobs(args):
    overrides = {name: getattr(args, name) for name in KNOB_FLAGS
                 if getattr(args, name) is not None}
    return dataclasses.replace(PRESETS[args.profile], **overrides)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="tbt-bot", description="play or advise a TBT game over its API")
    sub = parser.add_subparsers(dest="command", required=True)

    auto = sub.add_parser("auto", help="join a game and play it to the end")
    _add_common(auto)
    auto.add_argument("--name", default="TBT Bot", help="seat name on join")
    auto.add_argument("--player", help="resume this seat instead of joining")
    auto.add_argument("--token", help="token for --player")
    auto.add_argument("--verbose", action="store_true",
                      help="also log idle polling")

    advise = sub.add_parser("advise",
                            help="recommend a move for an existing seat")
    _add_common(advise)
    advise.add_argument("--player", required=True, help="your player id")
    advise.add_argument("--token", required=True, help="your bearer token")
    advise.add_argument("--json", action="store_true",
                        help="machine-readable output")
    advise.add_argument("--watch", action="store_true",
                        help="keep advising every time it is your move")

    args = parser.parse_args(argv)
    brain = HeuristicBrain(_knobs(args))
    rng = random.Random(args.seed)
    client = Client(args.server, token=args.token)

    if args.command == "auto":
        if bool(args.player) != bool(args.token):
            parser.error("--player and --token go together")
        if args.player:
            player_id = args.player
        else:
            seat = client.join(args.game, args.name)
            player_id = seat["player_id"]
            print("joined %s as %s (token: %s)"
                  % (args.game, player_id, seat["token"]))
        runner = Runner(client, args.game, player_id, brain,
                        poll_interval=args.poll or 1.0, rng=rng,
                        debug=print if args.verbose else None)
        try:
            runner.run()
        except BotStuck as stuck:
            print("bot is stuck: %s" % stuck, file=sys.stderr)
            return 3
        except KeyboardInterrupt:
            print("interrupted; seat %s can be resumed with --player/--token"
                  % player_id)
            return 130
        return 0

    if args.watch:
        try:
            return advisor.watch(client, args.game, args.player, brain, rng,
                                 poll_interval=args.poll or 2.0,
                                 json_out=args.json)
        except KeyboardInterrupt:
            return 130
    return advisor.advise_once(client, args.game, args.player, brain, rng,
                               json_out=args.json)


if __name__ == "__main__":
    sys.exit(main())
