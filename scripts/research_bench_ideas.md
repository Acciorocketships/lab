# Bench ideas for research-lab

Short, verifiable tasks to exercise the orchestrator, workers, memory, and the research brief (`research_idea.md`). Two buckets: **math that requires code**, and **RL that trains in a few minutes** on a typical laptop CPU.

---

## 1. Math problems that require programming

Answers should include runnable code (compute, verify, plot, or search), not only prose.

### Computation and verification

1. **Basel sum numerically** — Estimate \(\sum_{n=1}^{N} 1/n^2\) for increasing \(N\); compare to \(\pi^2/6\); report error vs \(N\) (table or plot).
2. **Harmonic partial sums** — Compute \(H_n\) for large \(n\); compare to \(\ln n + \gamma\) with a published \(\gamma\); quantify error.
3. **Fibonacci closed form** — Implement Binet’s formula vs iteration for \(n = 1..50\); document floating-point error where it blows up.
4. **Primality / factorization** — Trial division (or library) in a range; table timing vs bit length.
5. **GCD and extended Euclidean** — Implement `gcd` and Bézout coefficients; fuzz against `math.gcd` / sympy on random pairs.

### Discrete search and enumeration

6. **Pythagorean triples** — Generate primitive triples with \(a,b,c \le N\) (Euclid or search); count; verify \(a^2+b^2=c^2\).
7. **Collatz stopping times** — For \(n \le 10^6\), stopping time and max value; histogram; optionally note “all reach 1” in that range.
8. **Lattice points on a circle** — Count integer solutions to \(x^2+y^2=n\) for \(n \le N\); optional short note on sum-of-two-squares after the numbers are computed.

### Probability / simulation (RNG required)

9. **Buffon needle (Monte Carlo)** — Estimate \(\pi\); plot estimate vs trials with uncertainty.
10. **Birthday paradox** — Simulate vs closed-form collision probability for group size \(k\).
11. **2D random walk** — Empirical return statistics vs known asymptotics (cite after simulating).

### Linear algebra / numerics

12. **Condition number experiment** — Random or Hilbert matrices; solve \(Ax=b\) for known \(x\); relate error to \(\kappa(A)\).
13. **Eigenvalue sanity** — Structured matrices (e.g. path graph Laplacian); eigenvalues in code vs closed form for small \(n\).

### Number theory (computational core)

14. **Modular exponentiation** — Fast modular exp; verify Fermat’s little theorem for random prime \(p\) and \(a \not\equiv 0 \pmod p\).
15. **Sieve of Eratosthenes** — Count primes \(\le 10^6\); compare to \(\pi(x)\) approximations in a short table.

### Sample success criteria (math + code)

- Runnable script or notebook path; stdout or JSON with numeric outputs.
- Two methods compared with max absolute error on fixed inputs, or error vs parameter curve (CSV/plot).

### Suggested first three (fast pipeline smoke tests)

| Problem                         | Why                                                |
|---------------------------------|----------------------------------------------------|
| Basel partial sums vs \(\pi^2/6\) | Tiny code, clear target, easy to auto-check.       |
| Primitive triples \(\le N\)     | Loops + checks; scales with \(N\).                 |
| Birthday simulation vs formula   | Short sim + closed form; good multi-worker story.  |

---

## 2. RL problems trainable in ~1–5 minutes (CPU)

Wall-clock is approximate; depends on framework, seeds, and stop condition. “Solved” can mean threshold mean return or reward cap.

### Tabular / tiny discrete (often seconds to ~1 minute)

1. **FrozenLake-v1** (4×4) — Q-learning or SARSA; few thousand episodes often enough.
2. **Cliff Walking** — Textbook grid; tabular only.
3. **Taxi-v3** — Tabular Q-learning; may need a few minutes.
4. **Multi-armed bandits** — Instant; good for loop/logging sanity (not full MDP navigation).

### Classic continuous control (~2–5 minutes, SB3-style defaults)

5. **CartPole-v1** — PPO or A2C; default small benchmark on CPU.
6. **MountainCar-v0** — Sparse reward; may need more steps or shaping.
7. **Acrobot-v1** — Harder than CartPole; may exceed “couple minutes” without tuning.

### Minimal custom / “researchy” but still fast

8. **Small gridworld** (e.g. 5×5, goal, walls) — PPO with small timesteps; you control difficulty.
9. **Contextual bandits** — Seconds; tests features + logging.
10. **Tiny key–door grid** — Memory; small grid keeps runs short even if learning is finicky.

### Practical defaults

| Goal                         | Easy choice                          |
|-----------------------------|--------------------------------------|
| Fastest end-to-end          | FrozenLake + tabular Q-learning      |
| Classic control + policy    | CartPole + PPO (Gymnasium + SB3)     |
| Richer discrete             | Taxi-v3 + Q-learning + exploration   |

**Ballpark:** CartPole + PPO, ~100k–300k total timesteps on CPU often lands in a few minutes with default nets. FrozenLake needs far fewer **episodes** (not 1:1 comparable to timesteps). Vectorized envs (`n_envs` > 1) cut wall-clock for the same total steps.

### Caveats

- MountainCar and Acrobot can exceed a couple of minutes without hyperparameter tuning.
- Define “done” (mean return threshold vs. first time hitting env reward cap).

---

*Generated for benching research-lab; edit or prune as needed.*

**Active multi-step bench:** `data/bench_rl_project/` (tabular Q-learning on FrozenLake) — launch with `python scripts/run.py`.
