# Handoff: hooks proposed for files this work doesn't own

## Variant B (`world_multicontrol_base.py`): proposals for `world_transfer.py`
Variant B imports world_transfer as is and needed no change. Nice to have, for the "Sim-Transfer on the Mac" session to decide:
1. `text_cache(arrays, ids, rope)` could take several id lists and run them in one sweep over the layers. Variant B calls it
   twice (prompt, negative); the second call re-reads nothing (the weights are already resident), so this only saves a little time.
2. `Generator.__call__` hardcodes 32 heads x 128 and 4096 hidden in its reshapes. Reading them from the weights would let tests
   build a small fake generator (Variant B's tests use a 2-layer fake with the real head shapes for this reason).
