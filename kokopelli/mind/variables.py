"""Planned body variables for a longer agent run. Comments only: nothing reads this, and the first demo doesn't use them.

The first demo is 30 minutes of one continuous Cosmos situation. The agent perceives, appraises how it feels, decides
at decision points, and its action changes the 4D sim, which changes what the world model shows next.

Why not in the first demo
- Hunger and tiredness barely move in 30 story minutes. Faster rates would make the scene look strange: an agent
  starving in the middle of a calm half hour. So these belong to runs long enough for a body to need something.
- The loop can run without them, and each variable is one more thing to debug before the demo works.

Why these variables
- food: falls whatever the agent does, so doing nothing eventually fails. This guards against the "dark room" problem,
  where an agent keeps its state calm by avoiding everything.
- energy: spent by acting and restored by resting, so it competes with food. Cooking feeds you and tires you. One
  variable alone couldn't show competing needs.
- sleep: left until a run spans a day or more. Over a short run it's just a second energy. It only earns its place
  with its own rule: pressure builds with time awake, and only sleeping clears it, however much the agent rests.

Draft rules, all untuned
- Each variable runs 0 to 100, starting at 60, with a healthy range of 40 to 80.
- Every turn: food -5, energy -2.
- cook and eat: food +25, energy -10, one egg fewer, starting from 6 eggs. rest: energy +15. wait: no extra effect.

Why this draft seemed worth keeping
Five scripted strategies over 20 turns, with no model involved. "Off range" is how far outside the range they ended.
    always rest             food 0,  energy 100   off range 60   9 turns at zero   6 eggs left
    do nothing              food 0,  energy 20    off range 60   9 turns at zero   6 eggs left
    cook whenever possible  food 35, energy 100   off range 25   1 turn at zero    0 eggs left
    alternate cook, rest    food 55, energy 100   off range 20   0 turns at zero   0 eggs left
    cook or rest when low   food 60, energy 70    off range 0    0 turns at zero   2 eggs left
Only the strategy that responds to its state stays healthy, and it has eggs to spare, so a neighbour asking for one
is a real tradeoff. These are strategies written by hand, so none of this shows that a model can learn the rules.

What has to hold when these get built
- The world's rules set the values. Never take them from what the model says, or it can just claim to feel fine.
- Reuse the drive and reward in experiments/homeostatic/world.py rather than a second copy. Also report time spent in range,
  because a near-collapse followed by a recovery can otherwise score about the same as staying healthy throughout.
- HOMEOSTATIC_WORLD in settings.py has its own "energy", in a world of security, belonging and ambition. Those change
  over a life, and these change over hours. Decide whether they're one model or two before sharing the name.
"""
