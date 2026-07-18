"""TBT bot: plays or advises a game over the server API (design/api.md)

The bot is a pure HTTP client of tbt-server; it shares no code with the
server-side rules engine. Package layout:

- client.py  -- thin API client (injectable session for tests)
- view.py    -- GameView: public state + private view + map, merged
- moves.py   -- Move and Decision types the brain produces
- knobs.py   -- tunable strategy weights and difficulty presets
- brain.py   -- Brain interface and the heuristic implementation
- runner.py  -- full-auto loop: poll, decide, execute until finished
- advisor.py -- same decision, rendered as a recommendation instead
- cli.py     -- the tbt-bot console entry point
"""
