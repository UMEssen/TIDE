#!/usr/bin/env python3
"""
TIDE pipeline: discovers all BIDS EDF files under data/ds007808/, computes all 16 TIDE slices,
and pushes Patient / Device / Endpoint / TIDEObservation resources to Blaze FHIR.
"""
import json
import math
import re
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import welch
import requests
import mne

mne.set_log_level("WARNING")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# constants
FHIR_BASE = "http://localhost:8080/fhir"
HEADERS = {"Content-Type": "application/fhir+json"}

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PROCESSED_FILE = PROJECT_ROOT / "processed_files.json"

OPENNEURO_S3_BASE = "https://s3.amazonaws.com/openneuro.org"

# URLs confirmed from profiles/TIDEObservation.fsh, TIDEEndpoint.fsh,
# TIDE.cs.fsh, TIDERawdataEndpoint.ext.fsh, TIDESupplemental.cs.fsh
TIDE_OBS_PROFILE = "http://example.org/tide/StructureDefinition/tide-observation"
TIDE_EP_PROFILE  = "http://example.org/tide/StructureDefinition/tide-endpoint"
TIDE_CS          = "http://example.org/tide/CodeSystem/tide-code-system"
TIDE_SUP_CS      = "http://example.org/tide/CodeSystem/tide-supplemental-codes"
TIDE_RAWDATA_EXT = "http://example.org/tide/StructureDefinition/tide-rawdata-endpoint"
UCUM             = "http://unitsofmeasure.org"

BIDS_RE = re.compile(
    r"sub-(?P<subject>[^_]+)_ses-(?P<session>[^_]+)_task-(?P<task>[^_]+)_"
    r"acq-(?P<acq>[^_]+)_run-(?P<run>\d+)_eeg\.edf$"
)


# I/O helpers
def load_processed() -> list:
    if PROCESSED_FILE.exists():
        try:
            return json.loads(PROCESSED_FILE.read_text())
        except json.JSONDecodeError:
            log.warning("processed_files.json was invalid, starting fresh.")
    return []


def save_processed(files: list):
    PROCESSED_FILE.write_text(json.dumps(files, indent=2))
    log.info("Saved %d processed entries to %s", len(files), PROCESSED_FILE.name)


# FHIR helpers
def fhir_post(resource_type: str, body: dict):
    try:
        r = requests.post(
            f"{FHIR_BASE}/{resource_type}", json=body, headers=HEADERS, timeout=30
        )
        if r.status_code == 201:
            rid = r.json().get("id")
            log.info("Created %s/%s", resource_type, rid)
            return rid
        log.error("POST %s → HTTP %s: %s", resource_type, r.status_code, r.text[:400])
    except requests.RequestException as exc:
        log.error("POST %s failed: %s", resource_type, exc)
    return None


def fhir_get(path: str, params: dict = None):
    try:
        r = requests.get(
            f"{FHIR_BASE}/{path}",
            params=params,
            headers={"Accept": "application/fhir+json"},
            timeout=30,
        )
        if r.ok:
            return r.json()
        log.error("GET %s → HTTP %s", path, r.status_code)
    except requests.RequestException as exc:
        log.error("GET %s failed: %s", path, exc)
    return None


# signal analysis
def _shannon_entropy(signal: np.ndarray, bins: int = 100) -> float:
    clean = signal[~np.isnan(signal)]
    if clean.size == 0:
        return 0.0
    hist, _ = np.histogram(clean, bins=bins)
    hist = hist[hist > 0].astype(float)
    hist /= hist.sum()
    return float(-np.sum(hist * np.log2(hist + 1e-12)))


def compute_slices(raw: mne.io.BaseRaw, eeg_channels: list):
    """
    Returns (global_slices dict, per_ch dict keyed by channel name).
    Data is assumed preloaded; values are converted from V to µV internally.
    """
    data, times = raw.get_data(picks=eeg_channels, return_times=True)
    data = data * 1e6  # V → µV

    fs = raw.info["sfreq"]
    n_ch, n_times = data.shape

    # global slices
    total_samples = data.size
    valid_samples = int(np.sum(~np.isnan(data)))
    data_coverage = round(valid_samples / total_samples * 100, 4) if total_samples > 0 else 100.0

    gap_count = sum(
        1 for ann in raw.annotations
        if "boundary" in ann["description"].lower()
        or "edge" in ann["description"].lower()
    )

    global_slices = {
        "samplingFrequency": float(fs),
        "sampleCount":       int(n_times),
        "channelCount":      int(n_ch),
        "dataCoverage":      data_coverage,
        "dataGaps":          gap_count,
    }

    # samplingJitter: standard deviation of inter-sample intervals in ms (same for all EDF channels)
    time_diffs = np.diff(times) * 1000.0
    jitter = float(np.std(time_diffs)) if time_diffs.size > 1 else 0.0

    # per-channel slices
    per_ch = {}
    for i, ch in enumerate(eeg_channels):
        sig = data[i]
        valid = sig[~np.isnan(sig)]
        if valid.size == 0:
            per_ch[ch] = {
                k: 0.0 for k in [
                    "signalMean", "signalMin", "signalMax", "signalStdDev",
                    "signalStabilityIndex", "dominantFrequency", "trendSlope", "signalEntropy",
                    "samplingJitter",
                ]
            }
            per_ch[ch]["anomalyCount"] = 0
            continue

        mean = float(np.mean(valid))
        std  = float(np.std(valid))
        signal_stability_index = 20.0 * math.log10(abs(mean) / std) if (std > 0 and mean != 0) else 0.0

        # dominant frequency via Welch PSD
        try:
            freqs, psd = welch(valid, fs=fs, nperseg=min(valid.size, 4096))
            dom_freq = float(freqs[np.argmax(psd)])
        except Exception:
            dom_freq = 0.0

        # trend slope via polyfit (subsample large arrays for speed)
        try:
            if valid.size > 100_000:
                idx = np.linspace(0, valid.size - 1, 10_000, dtype=int)
                t_sub = idx / fs
                slope = float(np.polyfit(t_sub, valid[idx], 1)[0])
            else:
                slope = float(np.polyfit(np.arange(valid.size) / fs, valid, 1)[0])
        except Exception:
            slope = 0.0

        # Z-score anomaly count (threshold |z| > 3)
        anomaly_count = int((np.abs((valid - mean) / std) > 3).sum()) if std > 0 else 0

        per_ch[ch] = {
            "signalMean":        round(mean, 6),
            "signalMin":         round(float(np.min(valid)), 6),
            "signalMax":         round(float(np.max(valid)), 6),
            "signalStdDev":      round(std, 6),
            "signalStabilityIndex": round(signal_stability_index, 4),
            "dominantFrequency": round(dom_freq, 4),
            "trendSlope":        round(slope, 8),
            "signalEntropy":     round(_shannon_entropy(valid), 6),
            "anomalyCount":      anomaly_count,
            "samplingJitter":    round(jitter, 8),
        }

    return global_slices, per_ch


# date resolution
_ANON_DATE = (1985, 1, 1)  # EDF anonymisation placeholder per EDF+ spec


def _resolve_start_dt(meas_date, session_str: str) -> datetime:
    """
    Return the recording start as a UTC datetime.
    Falls back to the BIDS session date when meas_date is None or equals the
    1985-01-01 EDF anonymisation placeholder.
    """
    start_dt = None
    use_fallback = False

    if meas_date is not None:
        if isinstance(meas_date, datetime):
            start_dt = meas_date if meas_date.tzinfo else meas_date.replace(tzinfo=timezone.utc)
            start_dt = start_dt.astimezone(timezone.utc)
        else:
            start_dt = datetime.fromtimestamp(float(meas_date), tz=timezone.utc)

        if (start_dt.year, start_dt.month, start_dt.day) == _ANON_DATE:
            log.info("EDF meas_date is 1985-01-01 (anonymised); using BIDS session date.")
            use_fallback = True
    else:
        log.info("No meas_date in EDF header; using BIDS session date.")
        use_fallback = True

    if use_fallback:
        try:
            start_dt = datetime.strptime(session_str, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            log.warning("Cannot parse session string '%s'; keeping 1985-01-01.", session_str)
            start_dt = datetime(1985, 1, 1, tzinfo=timezone.utc)

    return start_dt


# FHIR resource builders
def get_or_create_patient(full_subject_id: str, patient_cache: dict):
    if full_subject_id in patient_cache:
        return patient_cache[full_subject_id]

    bundle = fhir_get("Patient", {"identifier": full_subject_id})
    if bundle and bundle.get("entry"):
        pid = bundle["entry"][0]["resource"]["id"]
        log.info("Reusing Patient/%s for %s", pid, full_subject_id)
        patient_cache[full_subject_id] = pid
        return pid

    patient = {
        "resourceType": "Patient",
        "identifier": [{"system": "urn:tide:bids:subject", "value": full_subject_id}],
    }
    pid = fhir_post("Patient", patient)
    if pid:
        patient_cache[full_subject_id] = pid
    return pid


def create_device(sidecar: dict):
    manufacturer = sidecar.get("Manufacturer", "Unknown Manufacturer")
    model = sidecar.get("ManufacturersModelName", "Unknown Model")
    device = {
        "resourceType": "Device",
        "manufacturer": manufacturer,
        "deviceName": [{"name": model, "type": "user-friendly-name"}],
        "type": {
            "coding": [{
                "system": "http://snomed.info/sct",
                "code": "468441005",
                "display": "Electroencephalograph",
            }]
        },
    }
    return fhir_post("Device", device)


def openneuro_url(edf_path: Path) -> str:
    relative = edf_path.resolve().relative_to(DATA_DIR.resolve())
    return f"{OPENNEURO_S3_BASE}/{relative.as_posix()}"


def create_rawdata_endpoint(edf_path: Path):
    endpoint = {
        "resourceType": "Endpoint",
        "meta": {"profile": [TIDE_EP_PROFILE]},
        "status": "active",
        "connectionType": {
            "system": "http://example.org/tide/CodeSystem/tide-connection-type-codes",
            "code": "direct-https",
        },
        "payloadType": [{
            "coding": [{
                "system": "http://example.org/tide/CodeSystem/tide-supplemental-codes",
                "code": "eegWaveform",
            }]
        }],
        "payloadMimeType": ["application/edf"],
        "address": openneuro_url(edf_path),
    }
    return fhir_post("Endpoint", endpoint)


def _qty_component(cs_code: str, display: str, value, ucum_code: str, unit_str: str, text: str = None):
    code = {"coding": [{"system": TIDE_CS, "code": cs_code, "display": display}]}
    if text:
        code["text"] = text
    return {
        "code": code,
        "valueQuantity": {
            "value": round(float(value), 6),
            "unit": unit_str,
            "system": UCUM,
            "code": ucum_code,
        },
    }


def _int_component(cs_code: str, display: str, value: int, text: str = None):
    code = {"coding": [{"system": TIDE_CS, "code": cs_code, "display": display}]}
    if text:
        code["text"] = text
    return {
        "code": code,
        "valueInteger": int(value),
    }


def build_observation(
    patient_id: str,
    device_id: str,
    endpoint_id: str,
    raw: mne.io.BaseRaw,
    eeg_channels: list,
    event_count: int,
    status: str,
    global_slices: dict,
    per_ch: dict,
    session_str: str = "",
):
    # effectivePeriod: use EDF header date unless it is None or the 1985-01-01
    # anonymisation placeholder, in which case fall back to the BIDS session date.
    start_dt = _resolve_start_dt(raw.info.get("meas_date"), session_str)
    duration_s = float(raw.times[-1]) if raw.times.size > 0 else 0.0
    end_dt = start_dt + timedelta(seconds=duration_s)
    start_str = start_dt.isoformat()
    end_str   = end_dt.isoformat()

    components = []

    # global slices (6)
    components.append(_qty_component("samplingFrequency", "Sampling Frequency",
                                     global_slices["samplingFrequency"], "Hz", "Hz"))
    components.append(_int_component("sampleCount", "Sample Count",
                                     global_slices["sampleCount"]))
    components.append(_int_component("channelCount", "Channel Count",
                                     global_slices["channelCount"]))
    components.append(_qty_component("dataCoverage", "Data Coverage",
                                     global_slices["dataCoverage"], "%", "%"))
    components.append(_int_component("dataGaps", "Data Gap Count",
                                     global_slices["dataGaps"]))
    components.append(_int_component("eventCount", "Physiological Event Count", event_count))

    # per-channel slices (10 × n_channels)
    # display = plain canonical CodeSystem text (matches TIDE.cs.fsh, required for
    # profile conformance); channel identity goes in code.text, not display.
    for ch, vals in per_ch.items():
        components.append(_qty_component("signalMean",    "Signal mean",
                                         vals["signalMean"],    "uV", "uV", text=ch))
        components.append(_qty_component("signalMin",     "Signal Minimum",
                                         vals["signalMin"],     "uV", "uV", text=ch))
        components.append(_qty_component("signalMax",     "Signal Maximum",
                                         vals["signalMax"],     "uV", "uV", text=ch))
        components.append(_qty_component("signalStdDev",  "Signal Standard Deviation",
                                         vals["signalStdDev"],  "uV", "uV", text=ch))
        components.append(_qty_component("signalStabilityIndex", "Signal Stability Index",
                                         vals["signalStabilityIndex"], "dB", "dB", text=ch))
        components.append(_qty_component("dominantFrequency", "Dominant Frequency",
                                         vals["dominantFrequency"], "Hz", "Hz", text=ch))
        components.append(_qty_component("trendSlope",    "Signal Trend Slope",
                                         vals["trendSlope"],    "uV/s", "uV/s", text=ch))
        components.append(_qty_component("signalEntropy", "Signal Entropy",
                                         vals["signalEntropy"], "bit", "bit", text=ch))
        components.append(_qty_component("samplingJitter", "Sampling Jitter",
                                         vals["samplingJitter"], "ms", "ms", text=ch))
        components.append(_int_component("anomalyCount",  "Technical Anomaly Count",
                                         vals["anomalyCount"], text=ch))

    return {
        "resourceType": "Observation",
        "meta": {"profile": [TIDE_OBS_PROFILE]},
        "status": status,
        "code": {
            "coding": [{
                "system": "http://loinc.org",
                "code": "11523-8",
                "display": "EEG study",
            }]
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "device":  {"reference": f"Device/{device_id}"},
        "effectivePeriod": {"start": start_str, "end": end_str},
        "extension": [{
            "url": TIDE_RAWDATA_EXT,
            "valueReference": {"reference": f"Endpoint/{endpoint_id}"},
        }],
        "component": components,
    }


# pipeline
def find_edf_files():
    return sorted((DATA_DIR / "ds007808").rglob("*.edf"))


def parse_bids(path: Path):
    m = BIDS_RE.match(path.name)
    return m.groupdict() if m else None


def determine_status_map(edf_files: list) -> dict:
    """Assign 'preliminary' to all runs in a session except the last (run number), which gets 'final'."""
    session_runs = defaultdict(list)
    for f in edf_files:
        p = parse_bids(f)
        if p:
            session_runs[(p["subject"], p["session"])].append((int(p["run"]), f))

    status_map = {}
    for runs in session_runs.values():
        runs_sorted = sorted(runs, key=lambda x: x[0])
        for idx, (_, path) in enumerate(runs_sorted):
            status_map[str(path)] = "final" if idx == len(runs_sorted) - 1 else "preliminary"
    return status_map


def process_edf(edf_path: Path, status: str, patient_cache: dict) -> bool:
    parsed = parse_bids(edf_path)
    if not parsed:
        log.warning("Skipping non-BIDS file: %s", edf_path.name)
        return False

    full_subject_id = f"sub-{parsed['subject']}"
    log.info("Processing %s  [status: %s]", edf_path.name, status)

    # sidecar JSON
    sidecar_path = edf_path.with_name(edf_path.name.replace("_eeg.edf", "_eeg.json"))
    sidecar = {}
    if sidecar_path.exists():
        try:
            sidecar = json.loads(sidecar_path.read_text())
        except Exception as exc:
            log.warning("Could not read sidecar %s: %s", sidecar_path.name, exc)

    # channels TSV to EEG-type channel names
    channels_path = edf_path.with_name(edf_path.name.replace("_eeg.edf", "_channels.tsv"))
    eeg_channel_names = None
    if channels_path.exists():
        try:
            ch_df = pd.read_csv(channels_path, sep="\t")
            eeg_channel_names = ch_df[ch_df["type"] == "EEG"]["name"].tolist()
        except Exception as exc:
            log.warning("Could not read channels TSV: %s", exc)

    # events TSV
    events_path = edf_path.with_name(edf_path.name.replace("_eeg.edf", "_events.tsv"))
    event_count = 0
    if events_path.exists():
        try:
            ev_df = pd.read_csv(events_path, sep="\t")
            event_count = len(ev_df)
            log.info("Found %d events in %s", event_count, events_path.name)
        except Exception as exc:
            log.warning("Could not read events TSV: %s", exc)

    # load EDF
    try:
        raw = mne.io.read_raw_edf(str(edf_path), preload=True, verbose=False)
        log.info("Loaded EDF: %d channels, %.1f Hz, %d samples",
                 len(raw.ch_names), raw.info["sfreq"], raw.n_times)
    except Exception as exc:
        log.error("Failed to load EDF %s: %s", edf_path.name, exc)
        return False

    # determine EEG channels to analyse
    raw_ch_set = set(raw.ch_names)
    if eeg_channel_names:
        eeg_channels = [c for c in eeg_channel_names if c in raw_ch_set]
    else:
        picks = mne.pick_types(raw.info, eeg=True, meg=False, misc=False, stim=False)
        eeg_channels = [raw.ch_names[i] for i in picks]
    if not eeg_channels:
        eeg_channels = list(raw.ch_names)
    log.info("Analysing %d EEG channels", len(eeg_channels))

    # compute all 16 TIDE slices
    try:
        global_slices, per_ch = compute_slices(raw, eeg_channels)
    except Exception as exc:
        log.error("Slice computation failed for %s: %s", edf_path.name, exc)
        return False

    # Patient (create once per subject, reuse across runs)
    patient_id = get_or_create_patient(full_subject_id, patient_cache)
    if not patient_id:
        log.error("Could not create/find Patient for %s", full_subject_id)
        return False

    # Device (one per file — device info may vary per acquisition)
    device_id = create_device(sidecar)
    if not device_id:
        log.error("Could not create Device for %s", edf_path.name)
        return False

    # RawData Endpoint
    endpoint_id = create_rawdata_endpoint(edf_path)
    if not endpoint_id:
        log.error("Could not create Endpoint for %s", edf_path.name)
        return False

    # TIDEObservation
    obs = build_observation(
        patient_id=patient_id,
        device_id=device_id,
        endpoint_id=endpoint_id,
        raw=raw,
        eeg_channels=eeg_channels,
        event_count=event_count,
        status=status,
        global_slices=global_slices,
        per_ch=per_ch,
        session_str=parsed["session"],
    )
    obs_id = fhir_post("Observation", obs)
    if not obs_id:
        log.error("Could not create Observation for %s", edf_path.name)
        return False

    log.info("Done: %s → Observation/%s", edf_path.name, obs_id)
    return True


def main():
    processed = load_processed()
    edf_files = find_edf_files()
    log.info("Discovered %d EDF file(s) under %s", len(edf_files), DATA_DIR)

    if not edf_files:
        log.warning("No EDF files found — nothing to process.")
        return

    status_map = determine_status_map(edf_files)
    patient_cache: dict = {}
    new_count = 0

    for edf_path in edf_files:
        path_str = str(edf_path)
        if path_str in processed:
            log.info("Already processed, skipping: %s", edf_path.name)
            continue

        status = status_map.get(path_str, "preliminary")
        success = process_edf(edf_path, status, patient_cache)
        if success:
            processed.append(path_str)
            save_processed(processed)
            new_count += 1

    log.info("Pipeline complete. Newly processed: %d, Total: %d.", new_count, len(processed))


if __name__ == "__main__":
    main()
