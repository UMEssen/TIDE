#!/usr/bin/env python3
"""
Ground-truth validation of the 16 TIDE analytical metrics.

Real EEG recordings have no independent ground truth for computed metrics
(signal stability index, entropy, dominant frequency, ...), so this script builds synthetic
signals with known, analytically-derived properties and checks that
compute_slices() - the exact function used by both tide_pipeline.py and
tide_pipeline_v2.py (verified logically identical via diff) - recovers them.

compute_slices() is imported directly, not reimplemented, so this is a
correctness check of the production code path, not a self-consistency check.
"""
import sys
import math
from pathlib import Path

import numpy as np
import pandas as pd
import mne

sys.path.insert(0, str(Path(__file__).parent))
from tide_pipeline import compute_slices, _shannon_entropy  # noqa: E402

mne.set_log_level("WARNING")

PROJECT_ROOT = Path(__file__).parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

RNG = np.random.default_rng(42)
ROWS = []


def _record(metric, case, known, computed, rel_tol=0.01, abs_tol=None, note=""):
    if known is None or computed is None:
        status = "FAIL"
        abs_err = rel_err = None
    else:
        abs_err = abs(computed - known)
        rel_err = abs_err / abs(known) if known != 0 else (0.0 if computed == 0 else float("inf"))
        if abs_tol is not None:
            status = "PASS" if abs_err <= abs_tol else "FAIL"
        else:
            status = "PASS" if (known == 0 and computed == 0) or rel_err <= rel_tol else "FAIL"
    ROWS.append({
        "metric": metric, "case": case,
        "known_value": known, "computed_value": computed,
        "abs_error": abs_err, "rel_error": rel_err,
        "status": status, "note": note,
    })


def _make_raw(data_uv: np.ndarray, fs: float, ch_names=None):
    """data_uv: (n_channels, n_samples) in microvolts -> builds an mne RawArray in volts."""
    n_ch = data_uv.shape[0]
    ch_names = ch_names or [f"ch{i}" for i in range(n_ch)]
    info = mne.create_info(ch_names, sfreq=fs, ch_types="eeg")
    raw = mne.io.RawArray(data_uv * 1e-6, info, verbose=False)
    return raw, ch_names


# Case 1: basic stats + signalStabilityIndex (formula: 20*log10(|mean|/std))
def case_basic_stats():
    fs, n = 250.0, 5000
    values = np.linspace(-500.0, 1500.0, n)  # µV, deterministic
    known_mean, known_std = float(values.mean()), float(values.std())
    known_min, known_max = float(values.min()), float(values.max())
    known_signal_stability_index = 20.0 * math.log10(abs(known_mean) / known_std) if known_std > 0 else 0.0

    raw, chs = _make_raw(values[np.newaxis, :], fs)
    global_slices, per_ch = compute_slices(raw, chs)
    ch = per_ch[chs[0]]

    _record("signalMean", "linspace(-500,1500)", known_mean, ch["signalMean"])
    _record("signalMin", "linspace(-500,1500)", known_min, ch["signalMin"])
    _record("signalMax", "linspace(-500,1500)", known_max, ch["signalMax"])
    _record("signalStdDev", "linspace(-500,1500)", known_std, ch["signalStdDev"])
    _record("signalStabilityIndex", "linspace(-500,1500)", known_signal_stability_index, ch["signalStabilityIndex"],
            note="TIDE's signalStabilityIndex = 20*log10(|mean|/std) — a coefficient-of-variation-style "
                 "formula, not a classical signal-power/noise-floor SNR. This check confirms "
                 "the formula is implemented correctly, not that it is a classical SNR definition.")
    _record("samplingFrequency", "linspace(-500,1500)", fs, global_slices["samplingFrequency"], abs_tol=0)
    _record("sampleCount", "linspace(-500,1500)", n, global_slices["sampleCount"], abs_tol=0)
    _record("channelCount", "linspace(-500,1500)", 1, global_slices["channelCount"], abs_tol=0)
    _record("dataCoverage", "linspace(-500,1500), no NaNs", 100.0, global_slices["dataCoverage"], abs_tol=1e-6)
    _record("dataGaps", "linspace(-500,1500), no annotations", 0, global_slices["dataGaps"], abs_tol=0)
    _record("samplingJitter", "uniform sfreq (mne RawArray)", 0.0, ch["samplingJitter"], abs_tol=1e-6,
            note="mne RawArray enforces uniform sample timing by construction, so this is a "
                 "sanity check on the formula (std of inter-sample intervals), not a test of "
                 "real acquisition-hardware jitter, which EDF export does not expose.")


# Case 2: dominant frequency via Welch PSD
def case_dominant_frequency():
    fs, dur = 250.0, 20.0
    n = int(fs * dur)
    t = np.arange(n) / fs
    f0, amplitude, noise_std = 10.0, 50.0, 2.0
    signal_uv = amplitude * np.sin(2 * np.pi * f0 * t) + RNG.normal(0, noise_std, n)

    raw, chs = _make_raw(signal_uv[np.newaxis, :], fs)
    _, per_ch = compute_slices(raw, chs)

    nperseg = min(n, 4096)
    freq_resolution = fs / nperseg
    computed = per_ch[chs[0]]["dominantFrequency"]
    _record("dominantFrequency", f"10 Hz sine + N(0,{noise_std}) noise", f0, computed,
            abs_tol=freq_resolution, note=f"tolerance = Welch frequency resolution ({freq_resolution:.3f} Hz)")


# Case 3: anomalyCount (|z|>3 threshold)
def case_anomaly_count():
    fs, n = 250.0, 4000
    baseline = RNG.uniform(-5.0, 5.0, n)  # bounded, never exceeds ~1.8 sigma naturally
    outlier_idx = [100, 500, 1000, 1500, 2000, 2500, 3000]
    baseline[outlier_idx] = 500.0  # far beyond any 3-sigma threshold
    known_count = len(outlier_idx)

    raw, chs = _make_raw(baseline[np.newaxis, :], fs)
    _, per_ch = compute_slices(raw, chs)
    _record("anomalyCount", f"{known_count} injected 500µV outliers in U(-5,5) baseline",
            known_count, per_ch[chs[0]]["anomalyCount"], abs_tol=0)


# Case 4a: dataCoverage (NaN fraction)
def case_data_coverage():
    fs, n = 100.0, 1000
    values = RNG.normal(0, 10, n)
    nan_idx = np.arange(50)  # first 50 samples missing
    values[nan_idx] = np.nan
    known_coverage = round((n - len(nan_idx)) / n * 100, 4)

    raw, chs = _make_raw(values[np.newaxis, :], fs)
    global_slices, _ = compute_slices(raw, chs)
    _record("dataCoverage", f"{len(nan_idx)}/{n} samples NaN", known_coverage,
            global_slices["dataCoverage"], abs_tol=1e-4)


# Case 4b: dataGaps (boundary/edge annotations)
def case_data_gaps():
    fs, n = 100.0, 1000
    values = RNG.normal(0, 10, n)
    raw, chs = _make_raw(values[np.newaxis, :], fs)
    known_gaps = 3
    raw.set_annotations(mne.Annotations(
        onset=[1.0, 3.0, 5.0], duration=[0.1, 0.1, 0.1],
        description=["boundary", "boundary", "edge"],
    ))
    global_slices, _ = compute_slices(raw, chs)
    _record("dataGaps", "3 injected boundary/edge annotations", known_gaps,
            global_slices["dataGaps"], abs_tol=0)


# Case 5: trendSlope (linear polyfit)
def case_trend_slope():
    fs, n = 250.0, 5000
    t = np.arange(n) / fs
    slope_known = 3.0  # µV/s
    signal_uv = slope_known * t

    raw, chs = _make_raw(signal_uv[np.newaxis, :], fs)
    _, per_ch = compute_slices(raw, chs)
    _record("trendSlope", "pure linear ramp, 3.0 µV/s", slope_known,
            per_ch[chs[0]]["trendSlope"], rel_tol=0.001)


# Case 6: signalEntropy (behavioral: noise > sine)
def case_signal_entropy():
    fs, dur = 250.0, 10.0
    n = int(fs * dur)
    t = np.arange(n) / fs
    sine_uv = 50.0 * np.sin(2 * np.pi * 10.0 * t)
    noise_uv = RNG.normal(0, 50.0, n)

    entropy_sine = _shannon_entropy(sine_uv)
    entropy_noise = _shannon_entropy(noise_uv)
    status = "PASS" if entropy_noise > entropy_sine else "FAIL"
    ROWS.append({
        "metric": "signalEntropy", "case": "sine (10Hz) vs Gaussian noise, same amplitude",
        "known_value": "entropy(noise) > entropy(sine)",
        "computed_value": f"sine={entropy_sine:.4f}, noise={entropy_noise:.4f}",
        "abs_error": None, "rel_error": None, "status": status,
        "note": "No closed-form target exists for Shannon entropy of a continuous signal from "
                "a histogram estimator, so this is a directional/behavioral check, not an "
                "exact-value one: white noise must have higher entropy than a pure tone.",
    })


def main():
    for fn in (case_basic_stats, case_dominant_frequency, case_anomaly_count,
               case_data_coverage, case_data_gaps, case_trend_slope, case_signal_entropy):
        fn()

    df = pd.DataFrame(ROWS)
    df.to_csv(RESULTS_DIR / "metric_validation_synthetic.csv", index=False)

    n_pass = (df["status"] == "PASS").sum()
    n_fail = (df["status"] == "FAIL").sum()

    lines = [
        "# TIDE Metric Ground-Truth Validation (Synthetic Signals)",
        "",
        "Validates `compute_slices()` (scripts/tide_pipeline.py, identical logic in "
        "tide_pipeline_v2.py per diff) against synthetic signals with known, "
        "analytically-derived properties. Real EEG recordings have no independent "
        "ground truth for these computed metrics; synthetic signals are the standard "
        "approach for validating signal-processing correctness.",
        "",
        f"**Result: {n_pass}/{len(df)} checks passed, {n_fail} failed.**",
        "",
        "Not covered here: `eventCount`, which is a direct pass-through count of "
        "`_events.tsv` rows (no signal computation involved).",
        "",
        "| Metric | Case | Known | Computed | Rel. error | Status | Note |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for _, r in df.iterrows():
        rel = f"{r['rel_error']:.4%}" if isinstance(r["rel_error"], float) else "—"
        lines.append(
            f"| {r['metric']} | {r['case']} | {r['known_value']} | {r['computed_value']} "
            f"| {rel} | {r['status']} | {r['note']} |"
        )
    (RESULTS_DIR / "metric_validation_report.md").write_text("\n".join(lines))

    print(df.to_string(index=False))
    print(f"\n{n_pass}/{len(df)} checks passed, {n_fail} failed.")
    print(f"Saved results/metric_validation_synthetic.csv and results/metric_validation_report.md")


if __name__ == "__main__":
    main()
