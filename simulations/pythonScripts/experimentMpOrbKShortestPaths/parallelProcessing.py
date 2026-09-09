"""Bounded process workers for independent extraction and plotting jobs."""

import multiprocessing


def run_parallel(function, jobs, cores):
    if cores < 1:
        raise ValueError("cores must be positive")
    jobs = list(jobs)
    if not jobs:
        return []
    if cores == 1:
        return [function(job) for job in jobs]
    # Spawn avoids inheriting Matplotlib state and works on macOS. Pool's
    # context manager terminates workers on failure or cancellation.
    with multiprocessing.get_context("spawn").Pool(min(cores, len(jobs))) as pool:
        return list(pool.imap(function, jobs))
