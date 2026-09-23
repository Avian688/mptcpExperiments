# MpOrbPressure scheduler comparison

Experiment 4's two-path topology, comparing the foreground connection's `default`
and `intBurst` schedulers. The algorithm is **MpOrbPressure** (the implemented name
corresponding to “mptcpPressure”). Five single-subflow MpOrbPressure background
connections compete on path 2. Their scheduler stays `default` in every case.

## Matrix and timing

- Two 100 Mbps bottlenecks; independent 10 Gbps access links.
- RTT profiles: `equal` = 20/20 ms; `longer` = 20/60 ms. These are propagation RTTs;
  serialization and queueing add delay. Background propagation RTT matches path 2.
- Two foreground schedulers × two RTT profiles × five paired seeds = **20 runs**.
- Foreground starts at the same seeded time in 0.1–2 s for each matched case.
- 0–40 s: foreground alone. At 40 s, all five background connections start.
- At 80 s, background **admission** stops; already assigned data may drain.
- Stop at **120 s**, allowing 40 s for recovery.
- Every queue has **173 packets**: ceil(100 Mbps × 20 ms / (8 × 1448)). Keep this
  fixed across profiles to isolate propagation delay, rather than changing RTT
  and buffer capacity together. It is not one 60 ms BDP in the longer case.
- MSS 1448; foreground sendQueueLimit 4 MiB; initial app write 2 GB. The existing
  transport refill mechanism maintains offered load after the write; tClose=-1s.
- PINT probability 1; separate directional queue delay enabled; fixedAvgRTTVal=0s.
- Pressure parameters are held constant: decrease gain 1, max decrease fraction
  0.25, probe interval 4 RTTs, additive increase 0.05, eta 0.95, alpha 0.03.

The RTT comparison is useful because `intBurst` uses forward-delay estimates.
This is a comparison of the complete current schedulers, including intBurst's
unsent-backlog bound, not an isolated measurement of the INT score's benefit.
The current starvation threshold comes from the compiled scheduler, not this INI.

**Scheduler configuration belongs on `tcp.conn-*.schedulerMode`.** The generated
configs set both foreground endpoints there explicitly; `tcp.schedulerMode`
would not select the scheduler. Background endpoints are explicitly `default`.

## Run from the OMNeT++ checkout root

Use a Python environment with numpy, pandas and matplotlib. Build the current
MPTCP/MpORB dependencies yourself before launching. This experiment adds no C++.

```sh
python3 samples/mptcpExperiments/simulations/pythonScripts/experimentScheduler/runExperimentScheduler.py --cores 10 --retries 0
```

A small first check (both schedulers, equal RTT, one seed):

```sh
python3 samples/mptcpExperiments/simulations/pythonScripts/experimentScheduler/runExperimentScheduler.py --cores 2 --runs 1 --configs Pressure_equal_default Pressure_equal_intBurst --retries 0
```

The runner generates INIs, simulates, exports, extracts, then plots. Stages have
barriers; simulation, export and extraction use the requested core count.
Use `--start-step 2` to reprocess existing simulations, `--end-step 1` to simulate
only, or `--skip-generate` to preserve hand-edited INIs. `--runs N` selects seeds
1 through N (up to five). `--sim-time-limit` is a diagnostic override; short runs
should use `--end-step 1`, since standard summaries assume the full 120 seconds.

`--resume` skips only runs with nonempty vec/sca files and a successful completion
marker matching the INI, topology, scenario, launch command and library file
identities. A timeout, nonzero exit or teardown abort is not marked complete.
Raw vec/sca existence alone is insufficient. Filenames retain `-#0`.

## Outputs

Under `simulations/plots/experimentScheduler/`:

- `goodput_comparison.png/pdf`: paired scheduler curves for each RTT profile;
  lines are run means, bands are min/max across available runs.
- `phase_goodput.png/pdf`: foreground phase means with sample standard deviations.
- `phase_summary.csv`: per-run, time-weighted foreground/background goodput,
  receiver HoL bytes and total foreground unsent send-queue bytes.
- `phase_aggregate.csv` and `coverage.csv`: summary statistics and run coverage.
- `<profile>/<scheduler>/runN.png/pdf`: foreground/background goodput, per-subflow
  cwnd, unsent queue, bytes in flight, receiver HoL and forward queueing delay.
  Subflow labels retain connection IDs; order follows connection creation.

Phase summaries cover baseline 10–40 s, competition 40–80 s and recovery 80–120 s.
They include competition and recovery transients. Goodput is integrated as an
interval-ending measurement; state vectors use sample-and-hold integration.
Missing requested foreground runs are reported as an error, rather than silently
presenting a complete comparison. Optional unavailable telemetry remains missing.

Validation performed: generator/config checks, NED syntax validation, CSV
extraction and plots using synthetic data only. No simulations or builds run.
