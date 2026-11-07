"""Cheap pre-GPU check: a tabular softmax agent using the SAME update rule planned for
the LoRA (on-policy REINFORCE, running baseline, one lived outcome per decision).
Does experience alone push it toward rare-bad and away from rare-good (Hertwig)?"""
import numpy as np, homeostasis as H

FLIP = {"under_oak": "front_row", "front_row": "under_oak", "lawn": "garden_trail", "garden_trail": "lawn"}

def run(seed, days=25, lr=2.0, world="normal", shuffled=False):
    rng = np.random.default_rng(seed)
    tabs = {"D1": H.D1, "D2": H.D2}
    logits = {k: np.zeros(len(t)) for k, t in tabs.items()}
    base = {k: 0.0 for k in tabs}
    picks = {k: np.zeros(len(t)) for k, t in tabs.items()}
    for day in range(days):
        h = H.start_state(rng)
        for k in ("D1", "D2"):
            opts = list(tabs[k]); p = np.exp(logits[k]) / np.exp(logits[k]).sum()
            a = rng.choice(len(opts), p=p)
            o = opts[a] if not shuffled else opts[rng.integers(len(opts))]
            br = tabs[k][o]
            if world == "flipped":   # spec 6.4: rare-bad options get rare-good stats and vice versa (EV still 3)
                br = tabs[k][FLIP.get(o, o)]
            i = rng.choice(len(br), p=[b[0] for b in br])
            h, r = H.apply(h, br[i][1])
            adv = r - base[k]; base[k] += 0.2 * (r - base[k])
            g = -p; g[a] += 1.0                      # grad of log pi(a) wrt logits
            logits[k] += lr * adv * g
            if day >= days // 2: picks[k][a] += 1
            h = H.relax(h)
    return {k: picks[k] / picks[k].sum() for k in picks}

def summarize(label, **kw):
    res = [run(s, **kw) for s in range(2000)]
    out = {}
    for k, t in (("D1", H.D1), ("D2", H.D2)):
        m = np.mean([r[k] for r in res], axis=0)
        out.update({o: f"{v:.3f}" for o, v in zip(t, m)})
    print(label, out)

if __name__ == "__main__":
    print("chance = 0.250 per option; second half of each 25-day life, 2000 lives")
    for lr in (1.0, 4.0, 8.0):
        print(f"--- lr={lr}")
        summarize("lived   ", lr=lr)
        summarize("flipped ", lr=lr, world="flipped")
        summarize("shuffled", lr=lr, shuffled=True)
