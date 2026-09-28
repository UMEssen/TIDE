#!/usr/bin/env python3
"""
Shared infrastructure for the quantitative comparison. Builds four resource sets from
the same five source EDF files (TIDE, generic SampledData, DocumentReference, UV PoCD
SampleArrayObservation) against an isolated Blaze instance (port 8081, separate from
the main TIDE Blaze on 8080).

Nothing here touches the existing TIDE pipelines/profiles/data. builders.py imports
compute_slices() and the component builders unmodified from tide_pipeline.py, so the
TIDE resource set built here uses the exact same production code path as the paper's
main (flat-model) pipeline.
"""
import json
import logging
from datetime import timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import mne

mne.set_log_level("WARNING")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = PROJECT_ROOT / "results" / "ac2_comparison"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# isolated Blaze instance (NOT the main port-8080 instance)
FHIR_BASE = "http://localhost:8081/fhir"
HEADERS = {"Content-Type": "application/fhir+json"}

OPENNEURO_S3_BASE = "https://s3.amazonaws.com/openneuro.org"
UCUM = "http://unitsofmeasure.org"

# the same 5 source files used everywhere else in the paper
# (2/2 ds007808, 3/3 ds007823 - identical set already validated end-to-end for TIDE)

FILES = [
    {
        "path": DATA_DIR / "ds007808/sub-03/ses-20240821/eeg/sub-03_ses-20240821_task-speechopen_acq-pangolin_run-01_eeg.edf",
        "subject": "sub-03", "session": "20240821", "dataset": "ds007808", "status": "preliminary",
    },
    {
        "path": DATA_DIR / "ds007808/sub-03/ses-20240821/eeg/sub-03_ses-20240821_task-speechopen_acq-pangolin_run-02_eeg.edf",
        "subject": "sub-03", "session": "20240821", "dataset": "ds007808", "status": "final",
    },
    {
        "path": DATA_DIR / "ds007823/sub-CUCOV003/eeg/sub-CUCOV003_task-COVID_eeg.edf",
        "subject": "sub-CUCOV003", "session": None, "dataset": "ds007823", "status": "final",
    },
    {
        "path": DATA_DIR / "ds007823/sub-CUCOV008/eeg/sub-CUCOV008_task-COVID_eeg.edf",
        "subject": "sub-CUCOV008", "session": None, "dataset": "ds007823", "status": "final",
    },
    {
        "path": DATA_DIR / "ds007823/sub-CUCOV020/eeg/sub-CUCOV020_task-COVID_eeg.edf",
        "subject": "sub-CUCOV020", "session": None, "dataset": "ds007823", "status": "final",
    },
]


# Adjusted window length across all four approaches per file, for a fair same-input
# comparison. Window length varies between files (5s for 128ch/1200Hz ds007808,
# up to 60s for 21-22ch/200Hz ds007823) to keep payload sizes tractable to POST
# and measure. Full-duration bundle size is reported separately as a linear
# extrapolation (valid since SampledData/PoCD payload scales linearly with sample
# count).
WINDOW_TARGET_SCALARS = 300_000
WINDOW_MIN_S = 5.0
WINDOW_MAX_S = 60.0


def openneuro_url(edf_path: Path) -> str:
    relative = edf_path.resolve().relative_to(DATA_DIR.resolve())
    return f"{OPENNEURO_S3_BASE}/{relative.as_posix()}"


def load_sidecars(edf_path: Path):
    sidecar_path = edf_path.with_name(edf_path.name.replace("_eeg.edf", "_eeg.json"))
    sidecar = {}
    if sidecar_path.exists():
        try:
            sidecar = json.loads(sidecar_path.read_text())
        except Exception as exc:
            log.warning("Could not read sidecar %s: %s", sidecar_path.name, exc)

    channels_path = edf_path.with_name(edf_path.name.replace("_eeg.edf", "_channels.tsv"))
    eeg_channel_names = None
    if channels_path.exists():
        try:
            ch_df = pd.read_csv(channels_path, sep="\t")
            eeg_channel_names = ch_df[ch_df["type"] == "EEG"]["name"].tolist()
        except Exception as exc:
            log.warning("Could not read channels TSV: %s", exc)

    return sidecar, eeg_channel_names


def probe_full_recording(edf_path: Path, eeg_channel_names=None):
    """Read only the EDF header (no sample data) to get full-duration metadata
    for the later linear extrapolation. n_channels reflects the EEG-type channel
    count actually analysed, not the raw EDF's total channel count, which also includes non-EEG channels
    (EOG/ECG/trigger/etc.)."""
    raw = mne.io.read_raw_edf(str(edf_path), preload=False, verbose=False)
    raw_ch_set = set(raw.ch_names)
    if eeg_channel_names:
        n_eeg = len([c for c in eeg_channel_names if c in raw_ch_set])
    else:
        n_eeg = len(mne.pick_types(raw.info, eeg=True, meg=False, misc=False, stim=False))
        if n_eeg == 0:
            n_eeg = len(raw.ch_names)
    return {
        "sfreq": float(raw.info["sfreq"]),
        "n_channels": n_eeg,
        "full_sample_count": int(raw.n_times),
        "full_duration_s": float(raw.n_times) / float(raw.info["sfreq"]),
    }


def window_seconds_for(sfreq: float, n_channels: int) -> float:
    w = WINDOW_TARGET_SCALARS / (sfreq * n_channels)
    return float(min(max(w, WINDOW_MIN_S), WINDOW_MAX_S))


def load_window(edf_path: Path, eeg_channel_names, window_s: float):
    """Load ONLY the representative window."""
    raw = mne.io.read_raw_edf(str(edf_path), preload=False, verbose=False)
    raw.crop(tmin=0.0, tmax=min(window_s, raw.times[-1]), include_tmax=False)
    raw.load_data()

    raw_ch_set = set(raw.ch_names)
    if eeg_channel_names:
        eeg_channels = [c for c in eeg_channel_names if c in raw_ch_set]
    else:
        picks = mne.pick_types(raw.info, eeg=True, meg=False, misc=False, stim=False)
        eeg_channels = [raw.ch_names[i] for i in picks]
    if not eeg_channels:
        eeg_channels = list(raw.ch_names)

    return raw, eeg_channels


def resolve_start_dt(meas_date, session_str):
    _ANON_DATE = (1985, 1, 1)
    from datetime import datetime
    start_dt = None
    use_fallback = False
    if meas_date is not None:
        start_dt = meas_date if meas_date.tzinfo else meas_date.replace(tzinfo=timezone.utc)
        start_dt = start_dt.astimezone(timezone.utc)
        if (start_dt.year, start_dt.month, start_dt.day) == _ANON_DATE:
            use_fallback = True
    else:
        use_fallback = True
    if use_fallback and session_str:
        try:
            start_dt = datetime.strptime(session_str, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            start_dt = datetime(1985, 1, 1, tzinfo=timezone.utc)
    elif use_fallback:
        start_dt = datetime(1985, 1, 1, tzinfo=timezone.utc)
    return start_dt


def sampled_data_string(data_uV: np.ndarray) -> str:
    """FHIR SampledData.data: flat, space-separated, interleaved per time point
    across dimensions (channels)."""
    # data_uV shape: (n_channels, n_samples) -> transpose to (n_samples, n_channels) then flatten
    flat = data_uV.T.reshape(-1)
    return " ".join(f"{v:.3f}" for v in flat)


def get_or_create_patient(full_subject_id: str, patient_cache: dict):
    if full_subject_id in patient_cache:
        return patient_cache[full_subject_id]
    patient = {
        "resourceType": "Patient",
        "identifier": [{"system": "urn:tide:bids:subject", "value": full_subject_id}],
    }
    entry_id = f"patient-{full_subject_id}"
    patient_cache[full_subject_id] = entry_id
    return entry_id, patient


def bundle_entry(resource: dict, fullurl_id: str):
    rtype = resource["resourceType"]
    return {
        "fullUrl": f"urn:uuid:{fullurl_id}",
        "resource": resource,
        "request": {"method": "POST", "url": rtype},
    }


# isolated-Blaze transaction / measurement helpers
# measured here but intentionally not reported because of server-implementation-dependency
# can not support any general performance clain
def post_transaction_bundle(bundle: dict, timeout: int = 300):
    """POST one transaction Bundle, return (wall_clock_seconds, response_json_or_None)."""
    import time
    t0 = time.perf_counter()
    r = requests.post(FHIR_BASE, json=bundle, headers=HEADERS, timeout=timeout)
    elapsed = time.perf_counter() - t0
    if not r.ok:
        log.error("Transaction POST failed: HTTP %s: %s", r.status_code, r.text[:500])
        return elapsed, None
    return elapsed, r.json()


def timed_get(path: str, params: dict = None, timeout: int = 60):
    import time
    t0 = time.perf_counter()
    r = requests.get(f"{FHIR_BASE}/{path}", params=params,
                      headers={"Accept": "application/fhir+json"}, timeout=timeout)
    elapsed = time.perf_counter() - t0
    n = None
    if r.ok:
        body = r.json()
        n = body.get("total", len(body.get("entry", [])))
    else:
        log.error("GET %s failed: HTTP %s", path, r.status_code)
    return elapsed, n


def wipe_all_resources():
    """Recreate the isolated Blaze instance from scratch between approach runs so
    each approach's ingestion time is measured against an empty database.

    Per-resource DELETE is deliberately not used: TIDE's hierarchical parent/child
    model links Observations both ways (hasMember on the parent, derivedFrom on
    each child), and Blaze's referential-integrity check refuses to delete either
    side while the other still exists - no deletion order breaks that cycle, so a
    resource-by-resource wipe can turn into a non-terminating retry loop. Tearing
    down and recreating the container's volume sidesteps that entirely.
    """
    import subprocess
    import time
    compose_file = Path(__file__).parent / "docker-compose.ac2.yml"
    subprocess.run(["docker", "compose", "-f", str(compose_file), "down", "-v"],
                    check=True, capture_output=True)
    subprocess.run(["docker", "compose", "-f", str(compose_file), "up", "-d"],
                    check=True, capture_output=True)
    for _ in range(30):
        try:
            if requests.get(f"{FHIR_BASE}/metadata", timeout=2).ok:
                log.info("Isolated Blaze instance recreated and ready.")
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError("Isolated Blaze instance did not become ready after recreation.")
