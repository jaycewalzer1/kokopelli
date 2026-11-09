"""How often does the draft pitch rule pass, by true gap and by how spread out family-level effects are?

Unit is the family. Each family has a true explicit-minus-filtered gap drawn around the true mean, with between-family
SD tau. Each family's two arm rates are then estimated from n_trials binary decisions, with paired bootstrap CIs.
"""
import numpy as np

rng = np.random.default_rng(0)
N_SIM, N_BOOT = 2000, 2000


def one(n_fam, base_e, gap, tau, n_trials):
    p_e = np.clip(rng.normal(base_e, 0.15, n_fam), 0.02, 0.98)
    p_f = np.clip(p_e - rng.normal(gap, tau, n_fam), 0.02, 0.98)
    d = rng.binomial(n_trials, p_e) / n_trials - rng.binomial(n_trials, p_f) / n_trials
    boot = d[rng.integers(0, n_fam, (N_BOOT, n_fam))].mean(1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return d.mean(), lo, hi


print("n_fam tau  trials  gap=0(FP)  gap=.10  gap=.15  gap=.25  gap=.35  median CI halfwidth@.25")
for n_fam in (24, 20, 16):
    for tau in (0.2, 0.35):
        for n_trials in (15, 45):
            row, width = [], None
            for gap in (0.0, 0.10, 0.15, 0.25, 0.35):
                res = np.array([one(n_fam, 0.7, gap, tau, n_trials) for _ in range(N_SIM)])
                row.append(np.mean((res[:, 0] >= 0.15) & (res[:, 1] > 0)))
                if gap == 0.25:
                    width = np.median((res[:, 2] - res[:, 1]) / 2)
            print(f"{n_fam:5d} {tau:.2f} {n_trials:6d}  " + "  ".join(f"{p:7.2f}" for p in row) + f"  {width:.3f}")
