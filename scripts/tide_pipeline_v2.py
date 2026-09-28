#!/usr/bin/env python3
"""
TIDE Pipeline v2 - Hierarchical Observation model (parent + per-channel children).

Dataset: OpenNeuro ds007823 (COVID-19 EEG, 3 subjects, 21-22 EEG channels, 200 Hz).

Two-dataset evaluation strategy
ds007808 (tide_pipeline.py):  1200 Hz, 128 channels — demonstrates high-frequency
                               scalability of the flat TIDE Observation model.
ds007823 (this file, "Version 2"):         200 Hz, 21-22 named 10-10 channels — demonstrates the
                               hierarchical parent/child model with clinically
                               meaningful electrode names (Fp1, Cz, T3, etc.).

Both pipelines target the same Blaze instance; subjects are distinct so resources
do not collide.

Structural model
Parent TIDEObservation (TIDE profile, 1 per EDF, client-assigned id via PUT):
  - 6 global components: samplingFrequency, sampleCount, channelCount,
    dataCoverage, dataGaps, eventCount
  - extension: tide-rawdata-endpoint -> Endpoint (absolute EDF path)
  - hasMember -> N x Reference(Observation), the child IDs

Child Observation (TIDEObservationChild profile, 1 per EEG channel):
  - code.text: plain canonical "EEG study" (matches code.coding[0].display);
    channel identity lives in bodySite, not in free text
  - bodySite: structured channel/electrode identity (International 10-20 System
    code from tide-channel-code-system, or non-standard-channel fallback), raw
    source label preserved in bodySite.text
  - method: free-text description of the analytical computation method
  - derivedFrom -> Reference(parent Observation), the raw-data linkage
  - 10 per-channel components: signalMean, signalMin, signalMax, signalStdDev,
    signalStabilityIndex, dominantFrequency, trendSlope, signalEntropy, anomalyCount,
    samplingJitter (plain canonical CodeSystem display text)

Note because of FHIR R4 constraint: Observation.partOf does not accept Observation as a
target type. But derivedFrom does accept Observation in R4, and is
used above for the child -> parent back-reference instead. Verified against
hl7.org/fhir/R4/observation.html.
"""
import json
import math
import re
import logging
import uuid
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
HEADERS   = {"Content-Type": "application/fhir+json"}

PROJECT_ROOT   = Path(__file__).parent.parent
DATA_DIR       = PROJECT_ROOT / "data" / "ds007823"
PROCESSED_FILE = PROJECT_ROOT / "processed_files_v2.json"

OPENNEURO_S3_BASE = "https://s3.amazonaws.com/openneuro.org"

TIDE_OBS_PROFILE       = "http://example.org/tide/StructureDefinition/tide-observation"
TIDE_OBS_CHILD_PROFILE = "http://example.org/tide/StructureDefinition/tide-observation-child"
TIDE_EP_PROFILE        = "http://example.org/tide/StructureDefinition/tide-endpoint"
TIDE_CS                = "http://example.org/tide/CodeSystem/tide-code-system"
TIDE_SUP_CS            = "http://example.org/tide/CodeSystem/tide-supplemental-codes"
TIDE_CHANNEL_CS        = "http://example.org/tide/CodeSystem/tide-channel-code-system"
TIDE_RAWDATA_EXT       = "http://example.org/tide/StructureDefinition/tide-rawdata-endpoint"
UCUM                   = "http://unitsofmeasure.org"

# International 10-20 System (standard 21 positions) + extended nasopharyngeal
# positions (Pg1/Pg2) actually observed in ds007823 — must match
# input/fsh/TIDEChannel.cs.fsh exactly. Lookup is case-insensitive because
# source channel labels vary in case (e.g. "FZ" vs "Fz").
KNOWN_CHANNEL_CODES = {
    "Fp1", "Fp2", "F7", "F3", "Fz", "F4", "F8", "T3", "C3", "Cz", "C4", "T4",
    "T5", "P3", "Pz", "P4", "T6", "O1", "O2", "A1", "A2", "Pg1", "Pg2",
}
_CHANNEL_CODE_LOOKUP = {c.upper(): c for c in KNOWN_CHANNEL_CODES}


def _channel_body_site(channel_name: str) -> dict:
    """Matches the raw source channel label case-insensitively against the
    International 10-20 System (+ extended positions); falls back to
    non-standard-channel for anything else (e.g. ds007808's generic
    "EEG047"-style labels, or ds007823's "25+")."""
    matched = _CHANNEL_CODE_LOOKUP.get(channel_name.strip().upper())
    if matched:
        return {
            "coding": [{"system": TIDE_CHANNEL_CS, "code": matched, "display": matched}],
            "text": channel_name,
        }
    return {
        "coding": [{"system": TIDE_CHANNEL_CS, "code": "non-standard-channel",
                     "display": "Non-standard or unlabeled channel"}],
        "text": channel_name,
    }

# ds007823 BIDS filenames have no session, acq, or run segments:
# sub-CUCOV003_task-COVID_eeg.edf
BIDS_RE = re.compile(r"sub-(?P<subject>[^_]+)_task-(?P<task>[^_]+)_eeg\.edf$")

_ANON_DATE = (1985, 1, 1)


# I/O helpers
def load_processed() -> list:
    if PROCESSED_FILE.exists():
        try:
            return json.loads(PROCESSED_FILE.read_text())
        except json.JSONDecodeError:
            log.warning("processed_files_v2.json was invalid, starting fresh.")
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


def fhir_put(resource_type: str, resource_id: str, body: dict):
    """Create/update with a client-assigned id ('update as create', standard FHIR
    behavior). Used for the parent Observation so its id is known before it's
    created, so children can carry a derivedFrom back-reference to it."""
    try:
        r = requests.put(
            f"{FHIR_BASE}/{resource_type}/{resource_id}", json=body, headers=HEADERS, timeout=30
        )
        if r.status_code in (200, 201):
            rid = r.json().get("id")
            log.info("Put %s/%s", resource_type, rid)
            return rid
        log.error("PUT %s/%s → HTTP %s: %s", resource_type, resource_id, r.status_code, r.text[:400])
    except requests.RequestException as exc:
        log.error("PUT %s/%s failed: %s", resource_type, resource_id, exc)
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


# date resolution
def _resolve_start_dt(meas_date) -> datetime:
    """
    Return recording start as UTC datetime.
    ds007823 has no session date in the filename, so if the EDF contains the
    1985-01-01 anonymisation placeholder (or None), it is kept as-is and logged
    clearly, rather than fabricating a fallback date.
    """
    if meas_date is None:
        log.warning("No meas_date in EDF header; using 1985-01-01 placeholder.")
        return datetime(1985, 1, 1, tzinfo=timezone.utc)

    if isinstance(meas_date, datetime):
        dt = meas_date if meas_date.tzinfo else meas_date.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
    else:
        dt = datetime.fromtimestamp(float(meas_date), tz=timezone.utc)

    if (dt.year, dt.month, dt.day) == _ANON_DATE:
        log.info("EDF meas_date is 1985-01-01 (EDF anonymisation placeholder); kept as-is.")

    return dt


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
    """Return (global_slices, per_ch) where values are in µV."""
    data, times = raw.get_data(picks=eeg_channels, return_times=True)
    data = data * 1e6  # V → µV

    fs = raw.info["sfreq"]
    n_ch, n_times = data.shape

    # global
    total   = data.size
    valid   = int(np.sum(~np.isnan(data)))
    coverage = round(valid / total * 100, 4) if total > 0 else 100.0
    gaps = sum(
        1 for ann in raw.annotations
        if "boundary" in ann["description"].lower()
        or "edge" in ann["description"].lower()
    )
    global_slices = {
        "samplingFrequency": float(fs),
        "sampleCount":       int(n_times),
        "channelCount":      int(n_ch),
        "dataCoverage":      coverage,
        "dataGaps":          gaps,
    }

    # samplingJitter: standard deviation of inter-sample intervals in ms (uniform for EDF)
    time_diffs = np.diff(times) * 1000.0
    jitter = float(np.std(time_diffs)) if time_diffs.size > 1 else 0.0

    # per-channel
    per_ch = {}
    for i, ch in enumerate(eeg_channels):
        sig   = data[i]
        valid_sig = sig[~np.isnan(sig)]
        if valid_sig.size == 0:
            per_ch[ch] = {k: 0.0 for k in [
                "signalMean", "signalMin", "signalMax", "signalStdDev",
                "signalStabilityIndex", "dominantFrequency", "trendSlope", "signalEntropy",
                "samplingJitter",
            ]}
            per_ch[ch]["anomalyCount"] = 0
            continue

        mean = float(np.mean(valid_sig))
        std  = float(np.std(valid_sig))
        signal_stability_index = 20.0 * math.log10(abs(mean) / std) if (std > 0 and mean != 0) else 0.0

        try:
            freqs, psd = welch(valid_sig, fs=fs, nperseg=min(valid_sig.size, 4096))
            dom_freq = float(freqs[np.argmax(psd)])
        except Exception:
            dom_freq = 0.0

        try:
            if valid_sig.size > 100_000:
                idx   = np.linspace(0, valid_sig.size - 1, 10_000, dtype=int)
                slope = float(np.polyfit(idx / fs, valid_sig[idx], 1)[0])
            else:
                slope = float(np.polyfit(np.arange(valid_sig.size) / fs, valid_sig, 1)[0])
        except Exception:
            slope = 0.0

        anomaly_count = int((np.abs((valid_sig - mean) / std) > 3).sum()) if std > 0 else 0

        per_ch[ch] = {
            "signalMean":        round(mean, 6),
            "signalMin":         round(float(np.min(valid_sig)), 6),
            "signalMax":         round(float(np.max(valid_sig)), 6),
            "signalStdDev":      round(std, 6),
            "signalStabilityIndex": round(signal_stability_index, 4),
            "dominantFrequency": round(dom_freq, 4),
            "trendSlope":        round(slope, 8),
            "signalEntropy":     round(_shannon_entropy(valid_sig), 6),
            "anomalyCount":      anomaly_count,
            "samplingJitter":    round(jitter, 8),
        }

    return global_slices, per_ch


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
    # ds007823 sidecars carry no Manufacturer/ManufacturersModelName fields;
    # defaults are used and documented in the paper accordingly.
    manufacturer = sidecar.get("Manufacturer", "Unknown Manufacturer")
    model        = sidecar.get("ManufacturersModelName", "Unknown Model")
    device = {
        "resourceType": "Device",
        "manufacturer": manufacturer,
        "deviceName":   [{"name": model, "type": "user-friendly-name"}],
        "type": {"coding": [{
            "system":  "http://snomed.info/sct",
            "code":    "468441005",
            "display": "Electroencephalograph",
        }]},
    }
    return fhir_post("Device", device)


def openneuro_url(edf_path: Path) -> str:
    relative = edf_path.resolve().relative_to((PROJECT_ROOT / "data").resolve())
    return f"{OPENNEURO_S3_BASE}/{relative.as_posix()}"


def create_rawdata_endpoint(edf_path: Path):
    endpoint = {
        "resourceType": "Endpoint",
        "meta":   {"profile": [TIDE_EP_PROFILE]},
        "status": "active",
        "connectionType": {
            "system": "http://example.org/tide/CodeSystem/tide-connection-type-codes",
            "code":   "direct-https",
        },
        "payloadType": [{"coding": [{"system": "http://example.org/tide/CodeSystem/tide-supplemental-codes", "code": "eegWaveform"}]}],
        "payloadMimeType": ["application/edf"],
        "address": openneuro_url(edf_path),
    }
    return fhir_post("Endpoint", endpoint)


def _qty_comp(cs_code: str, display: str, value, ucum_code: str, unit_str: str) -> dict:
    return {
        "code": {"coding": [{"system": TIDE_CS, "code": cs_code, "display": display}]},
        "valueQuantity": {
            "value": round(float(value), 6),
            "unit":  unit_str,
            "system": UCUM,
            "code":  ucum_code,
        },
    }


def _int_comp(cs_code: str, display: str, value: int) -> dict:
    return {
        "code": {"coding": [{"system": TIDE_CS, "code": cs_code, "display": display}]},
        "valueInteger": int(value),
    }


def build_child_observation(
    channel_name: str,
    ch_metrics: dict,
    patient_id: str,
    device_id: str,
    parent_id: str,
    start_str: str,
    end_str: str,
) -> dict:
    """
    TIDEObservationChild - channel-specific child Observation for one EEG channel
    (hierarchical model). Structured channel identity lives in bodySite, not in
    free text; component displays use the plain canonical CodeSystem text;
    derivedFrom links back to the parent Observation, since Observation.partOf
    does not accept Observation as a target in R4.
    """
    components = [
        _qty_comp("signalMean",        "Signal mean",
                  ch_metrics["signalMean"],        "uV",   "uV"),
        _qty_comp("signalMin",         "Signal Minimum",
                  ch_metrics["signalMin"],         "uV",   "uV"),
        _qty_comp("signalMax",         "Signal Maximum",
                  ch_metrics["signalMax"],         "uV",   "uV"),
        _qty_comp("signalStdDev",      "Signal Standard Deviation",
                  ch_metrics["signalStdDev"],      "uV",   "uV"),
        _qty_comp("signalStabilityIndex", "Signal Stability Index",
                  ch_metrics["signalStabilityIndex"], "dB",   "dB"),
        _qty_comp("dominantFrequency", "Dominant Frequency",
                  ch_metrics["dominantFrequency"], "Hz",   "Hz"),
        _qty_comp("trendSlope",        "Signal Trend Slope",
                  ch_metrics["trendSlope"],        "uV/s", "uV/s"),
        _qty_comp("signalEntropy",     "Signal Entropy",
                  ch_metrics["signalEntropy"],     "bit",  "bit"),
        _qty_comp("samplingJitter",    "Sampling Jitter",
                  ch_metrics["samplingJitter"],    "ms",   "ms"),
        _int_comp("anomalyCount",      "Technical Anomaly Count",
                  ch_metrics["anomalyCount"]),
    ]
    return {
        "resourceType": "Observation",
        "meta": {"profile": [TIDE_OBS_CHILD_PROFILE]},
        "status": "final",
        "code": {"coding": [{
            "system":  "http://loinc.org",
            "code":    "11523-8",
            "display": "EEG study",
        }], "text": "EEG study"},
        "subject":         {"reference": f"Patient/{patient_id}"},
        "bodySite":        _channel_body_site(channel_name),
        "method":          {"text": "TIDE analytical metrics computed via compute_slices() "
                                     "(numpy/scipy Welch PSD, MNE-based EEG preprocessing)."},
        "derivedFrom":     [{"reference": f"Observation/{parent_id}"}],
        "device":          {"reference": f"Device/{device_id}"},
        "effectivePeriod": {"start": start_str, "end": end_str},
        "component":       components,
    }


def build_parent_observation(
    parent_id: str,
    patient_id: str,
    device_id: str,
    endpoint_id: str,
    global_slices: dict,
    event_count: int,
    child_ids: list,
    start_str: str,
    end_str: str,
) -> dict:
    """
    TIDEObservation (TIDE profile) carrying the 6 global slices, the
    rawdata-endpoint extension, and hasMember references to all children.

    id is client-assigned (created via PUT) so children can be given a
    derivedFrom reference to this parent before the parent itself is created.
    """
    components = [
        _qty_comp("samplingFrequency", "Sampling Frequency",
                  global_slices["samplingFrequency"], "Hz", "Hz"),
        _int_comp("sampleCount",  "Sample Count",  global_slices["sampleCount"]),
        _int_comp("channelCount", "Channel Count", global_slices["channelCount"]),
        _qty_comp("dataCoverage", "Data Coverage",
                  global_slices["dataCoverage"], "%", "%"),
        _int_comp("dataGaps",   "Data Gap Count",             global_slices["dataGaps"]),
        _int_comp("eventCount", "Physiological Event Count",  event_count),
    ]
    has_member = [{"reference": f"Observation/{cid}"} for cid in child_ids]
    return {
        "resourceType": "Observation",
        "id": parent_id,
        "meta": {"profile": [TIDE_OBS_PROFILE]},
        "status": "final",
        "code": {"coding": [{
            "system":  "http://loinc.org",
            "code":    "11523-8",
            "display": "EEG study",
        }]},
        "subject":         {"reference": f"Patient/{patient_id}"},
        "device":          {"reference": f"Device/{device_id}"},
        "effectivePeriod": {"start": start_str, "end": end_str},
        "extension": [{"url": TIDE_RAWDATA_EXT,
                       "valueReference": {"reference": f"Endpoint/{endpoint_id}"}}],
        "component": components,
        "hasMember": has_member,
    }


# pipeline
def find_edf_files() -> list:
    return sorted(DATA_DIR.rglob("*.edf"))


def process_edf(edf_path: Path, patient_cache: dict) -> bool:
    m = BIDS_RE.match(edf_path.name)
    if not m:
        log.warning("Skipping non-BIDS file: %s", edf_path.name)
        return False

    parsed           = m.groupdict()
    full_subject_id  = f"sub-{parsed['subject']}"
    log.info("Processing %s", edf_path.name)

    # sidecar JSON
    sidecar_path = edf_path.with_name(edf_path.name.replace("_eeg.edf", "_eeg.json"))
    sidecar = {}
    if sidecar_path.exists():
        try:
            sidecar = json.loads(sidecar_path.read_text())
        except Exception as exc:
            log.warning("Could not read sidecar: %s", exc)

    # channels TSV - filter to EEG type only, respect status column if present
    channels_path = edf_path.with_name(edf_path.name.replace("_eeg.edf", "_channels.tsv"))
    eeg_channel_names = None
    if channels_path.exists():
        try:
            ch_df = pd.read_csv(channels_path, sep="\t")
            mask  = ch_df["type"] == "EEG"
            if "status" in ch_df.columns:
                mask = mask & (ch_df["status"].str.lower() != "bad")
            eeg_channel_names = ch_df[mask]["name"].tolist()
        except Exception as exc:
            log.warning("Could not read channels TSV: %s", exc)

    # events TSV
    events_path = edf_path.with_name(edf_path.name.replace("_eeg.edf", "_events.tsv"))
    event_count = 0
    if events_path.exists():
        try:
            event_count = len(pd.read_csv(events_path, sep="\t"))
            log.info("Found %d events", event_count)
        except Exception as exc:
            log.warning("Could not read events TSV: %s", exc)

    # load EDF
    try:
        raw = mne.io.read_raw_edf(str(edf_path), preload=True, verbose=False)
        log.info("Loaded: %d channels, %.0f Hz, %d samples",
                 len(raw.ch_names), raw.info["sfreq"], raw.n_times)
    except Exception as exc:
        log.error("Failed to load EDF %s: %s", edf_path.name, exc)
        return False

    # resolve EEG channels
    raw_ch_set = set(raw.ch_names)
    if eeg_channel_names:
        eeg_channels = [c for c in eeg_channel_names if c in raw_ch_set]
    else:
        picks = mne.pick_types(raw.info, eeg=True, meg=False)
        eeg_channels = [raw.ch_names[i] for i in picks]
    if not eeg_channels:
        eeg_channels = list(raw.ch_names)
    log.info("Analysing %d EEG channels: %s", len(eeg_channels), eeg_channels)

    # compute slices
    try:
        global_slices, per_ch = compute_slices(raw, eeg_channels)
    except Exception as exc:
        log.error("Slice computation failed: %s", exc)
        return False

    # effectivePeriod
    start_dt  = _resolve_start_dt(raw.info.get("meas_date"))
    duration  = float(raw.times[-1]) if raw.times.size > 0 else 0.0
    end_dt    = start_dt + timedelta(seconds=duration)
    start_str = start_dt.isoformat()
    end_str   = end_dt.isoformat()

    # Patient
    patient_id = get_or_create_patient(full_subject_id, patient_cache)
    if not patient_id:
        log.error("Could not create/find Patient for %s", full_subject_id)
        return False

    # Device
    device_id = create_device(sidecar)
    if not device_id:
        log.error("Could not create Device for %s", edf_path.name)
        return False

    # RawData Endpoint
    endpoint_id = create_rawdata_endpoint(edf_path)
    if not endpoint_id:
        log.error("Could not create Endpoint for %s", edf_path.name)
        return False

    # Parent id is generated up front (client-assigned) so children can carry a
    # derivedFrom back-reference to it. Blaze enforces referential integrity on
    # write, so the parent must actually exist in the store before any child
    # can be POSTed with a derivedFrom pointing at it. We therefore PUT the
    # parent first with an empty hasMember, create the children against the
    # now-existing parent, then PUT the parent again with the final hasMember
    # list once all child ids are known
    parent_id = str(uuid.uuid4())

    placeholder_parent_body = build_parent_observation(
        parent_id=parent_id,
        patient_id=patient_id,
        device_id=device_id,
        endpoint_id=endpoint_id,
        global_slices=global_slices,
        event_count=event_count,
        child_ids=[],
        start_str=start_str,
        end_str=end_str,
    )
    if not fhir_put("Observation", parent_id, placeholder_parent_body):
        log.error("Could not create placeholder parent Observation for %s", edf_path.name)
        return False

    # Children - collect IDs
    child_ids = []
    for ch_name in eeg_channels:
        if ch_name not in per_ch:
            log.warning("No metrics for channel %s, skipping child.", ch_name)
            continue
        child_body = build_child_observation(
            channel_name=ch_name,
            ch_metrics=per_ch[ch_name],
            patient_id=patient_id,
            device_id=device_id,
            parent_id=parent_id,
            start_str=start_str,
            end_str=end_str,
        )
        cid = fhir_post("Observation", child_body)
        if cid:
            child_ids.append(cid)
        else:
            log.warning("Child Observation for channel %s failed; continuing.", ch_name)

    log.info("Created %d/%d child Observations", len(child_ids), len(eeg_channels))

    # Parent update - fill in hasMember now that all child ids are known
    parent_body = build_parent_observation(
        parent_id=parent_id,
        patient_id=patient_id,
        device_id=device_id,
        endpoint_id=endpoint_id,
        global_slices=global_slices,
        event_count=event_count,
        child_ids=child_ids,
        start_str=start_str,
        end_str=end_str,
    )
    created_parent_id = fhir_put("Observation", parent_id, parent_body)
    if not created_parent_id:
        log.error("Could not update parent Observation for %s", edf_path.name)
        return False

    log.info("Done: %s → parent Observation/%s (+%d children)",
             edf_path.name, parent_id, len(child_ids))
    return True


def main():
    processed = load_processed()
    edf_files = find_edf_files()
    log.info("Discovered %d EDF file(s) under %s", len(edf_files), DATA_DIR)

    if not edf_files:
        log.warning("No EDF files found - nothing to process.")
        return

    patient_cache: dict = {}
    new_count = 0

    for edf_path in edf_files:
        path_str = str(edf_path)
        if path_str in processed:
            log.info("Already processed, skipping: %s", edf_path.name)
            continue
        success = process_edf(edf_path, patient_cache)
        if success:
            processed.append(path_str)
            save_processed(processed)
            new_count += 1

    log.info("Pipeline v2 complete. Newly processed: %d, Total: %d.", new_count, len(processed))


if __name__ == "__main__":
    main()
