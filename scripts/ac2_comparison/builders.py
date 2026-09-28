#!/usr/bin/env python3
"""
Four resource builders - TIDE, SampledData, DocumentReference, UV PoCD
SampleArrayObservation - each consuming the SAME representative window of the
SAME source EDF file (see common.py) and returning FHIR transaction-bundle
entries.

TIDEs own per-channel metric computation (compute_slices) and component
builders (_qty_component / _int_component) are imported unchanged from
scripts/tide_pipeline.py so the TIDE arm of this benchmark runs the exact same
production analysis code as the paper's main pipeline - only the resource
IDs are bundle-local (urn:uuid) instead of already-posted server ids.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from tide_pipeline import (  # noqa: E402  (reused unmodified from the main pipeline)
    compute_slices, _qty_component, _int_component,
    TIDE_OBS_PROFILE, TIDE_EP_PROFILE, TIDE_RAWDATA_EXT,
)

from common import (
    UCUM, openneuro_url, load_sidecars, load_window, resolve_start_dt,
    sampled_data_string, bundle_entry,
)


def _device_resource(sidecar: dict):
    return {
        "resourceType": "Device",
        "manufacturer": sidecar.get("Manufacturer", "Unknown Manufacturer"),
        "deviceName": [{"name": sidecar.get("ManufacturersModelName", "Unknown Model"),
                         "type": "user-friendly-name"}],
        "type": {"coding": [{"system": "http://snomed.info/sct", "code": "38531001",
                              "display": "Electroencephalograph"}]},
    }


def _patient_entry_if_new(full_subject_id: str, patient_cache: dict, entries: list):
    if full_subject_id in patient_cache:
        return patient_cache[full_subject_id]
    uid = f"patient-{full_subject_id}"
    patient_cache[full_subject_id] = uid
    entries.append(bundle_entry(
        {"resourceType": "Patient",
         "identifier": [{"system": "urn:tide:bids:subject", "value": full_subject_id}]},
        uid))
    return uid


# 1) TIDE (imports the paper's own unmodified analysis code)
def build_tide_entries(file_meta: dict, patient_cache: dict) -> list:
    edf_path = file_meta["path"]
    sidecar, eeg_names = load_sidecars(edf_path)
    from common import window_seconds_for
    import mne
    probe = mne.io.read_raw_edf(str(edf_path), preload=False, verbose=False)
    n_eeg_for_sizing = len(eeg_names) if eeg_names else len(probe.ch_names)
    window_s = window_seconds_for(probe.info["sfreq"], n_eeg_for_sizing)
    raw, eeg_channels = load_window(edf_path, eeg_names, window_s)

    global_slices, per_ch = compute_slices(raw, eeg_channels)

    events_path = edf_path.with_name(edf_path.name.replace("_eeg.edf", "_events.tsv"))
    event_count = 0
    if events_path.exists():
        import pandas as pd
        try:
            event_count = len(pd.read_csv(events_path, sep="\t"))
        except Exception:
            pass

    entries = []
    patient_uid = _patient_entry_if_new(file_meta["subject"], patient_cache, entries)

    device_uid = f"device-tide-{edf_path.stem}"
    entries.append(bundle_entry(_device_resource(sidecar), device_uid))

    endpoint_uid = f"endpoint-tide-{edf_path.stem}"
    endpoint_resource = {
        "resourceType": "Endpoint",
        "meta": {"profile": [TIDE_EP_PROFILE]},
        "status": "active",
        "connectionType": {"system": "http://example.org/tide/CodeSystem/tide-connection-type-codes",
                            "code": "direct-https"},
        "payloadType": [{"coding": [{"system": "http://example.org/tide/CodeSystem/tide-supplemental-codes", "code": "eegWaveform"}]}],
        "payloadMimeType": ["application/edf"],
        "address": openneuro_url(edf_path),
    }
    entries.append(bundle_entry(endpoint_resource, endpoint_uid))

    start_dt = resolve_start_dt(raw.info.get("meas_date"), file_meta["session"])
    duration_s = float(raw.times[-1]) if raw.times.size > 0 else 0.0
    from datetime import timedelta
    end_dt = start_dt + timedelta(seconds=duration_s)

    components = []
    components.append(_qty_component("samplingFrequency", "Sampling Frequency", global_slices["samplingFrequency"], "Hz", "Hz"))
    components.append(_int_component("sampleCount", "Sample Count", global_slices["sampleCount"]))
    components.append(_int_component("channelCount", "Channel Count", global_slices["channelCount"]))
    components.append(_qty_component("dataCoverage", "Data Coverage", global_slices["dataCoverage"], "%", "%"))
    components.append(_int_component("dataGaps", "Data Gap Count", global_slices["dataGaps"]))
    components.append(_int_component("eventCount", "Physiological Event Count", event_count))
    for ch, vals in per_ch.items():
        components.append(_qty_component("signalMean", "Signal mean", vals["signalMean"], "uV", "uV", text=ch))
        components.append(_qty_component("signalMin", "Signal Minimum", vals["signalMin"], "uV", "uV", text=ch))
        components.append(_qty_component("signalMax", "Signal Maximum", vals["signalMax"], "uV", "uV", text=ch))
        components.append(_qty_component("signalStdDev", "Signal Standard Deviation", vals["signalStdDev"], "uV", "uV", text=ch))
        components.append(_qty_component("signalStabilityIndex", "Signal Stability Index", vals["signalStabilityIndex"], "dB", "dB", text=ch))
        components.append(_qty_component("dominantFrequency", "Dominant Frequency", vals["dominantFrequency"], "Hz", "Hz", text=ch))
        components.append(_qty_component("trendSlope", "Signal Trend Slope", vals["trendSlope"], "uV/s", "uV/s", text=ch))
        components.append(_qty_component("signalEntropy", "Signal Entropy", vals["signalEntropy"], "bit", "bit", text=ch))
        components.append(_qty_component("samplingJitter", "Sampling Jitter", vals["samplingJitter"], "ms", "ms", text=ch))
        components.append(_int_component("anomalyCount", "Technical Anomaly Count", vals["anomalyCount"], text=ch))

    obs = {
        "resourceType": "Observation",
        "meta": {"profile": [TIDE_OBS_PROFILE]},
        "status": file_meta["status"],
        "code": {"coding": [{"system": "http://loinc.org", "code": "11523-8", "display": "EEG study"}]},
        "subject": {"reference": f"urn:uuid:{patient_uid}"},
        "device": {"reference": f"urn:uuid:{device_uid}"},
        "effectivePeriod": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
        "extension": [{"url": TIDE_RAWDATA_EXT, "valueReference": {"reference": f"urn:uuid:{endpoint_uid}"}}],
        "component": components,
    }
    entries.append(bundle_entry(obs, f"obs-tide-{edf_path.stem}"))
    return entries, window_s


# 2) generic FHIR core SampledData
def build_sampleddata_entries(file_meta: dict, patient_cache: dict) -> list:
    edf_path = file_meta["path"]
    sidecar, eeg_names = load_sidecars(edf_path)
    from common import window_seconds_for
    import mne
    probe = mne.io.read_raw_edf(str(edf_path), preload=False, verbose=False)
    n_eeg_for_sizing = len(eeg_names) if eeg_names else len(probe.ch_names)
    window_s = window_seconds_for(probe.info["sfreq"], n_eeg_for_sizing)
    raw, eeg_channels = load_window(edf_path, eeg_names, window_s)

    data, _ = raw.get_data(picks=eeg_channels, return_times=True)
    data_uV = data * 1e6

    entries = []
    patient_uid = _patient_entry_if_new(file_meta["subject"], patient_cache, entries)
    device_uid = f"device-sd-{edf_path.stem}"
    entries.append(bundle_entry(_device_resource(sidecar), device_uid))

    start_dt = resolve_start_dt(raw.info.get("meas_date"), file_meta["session"])
    from datetime import timedelta
    end_dt = start_dt + timedelta(seconds=float(raw.times[-1]))

    obs = {
        "resourceType": "Observation",
        "status": file_meta["status"],
        "code": {"coding": [{"system": "http://loinc.org", "code": "11523-8", "display": "EEG study"}]},
        "subject": {"reference": f"urn:uuid:{patient_uid}"},
        "device": {"reference": f"urn:uuid:{device_uid}"},
        "effectivePeriod": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
        "valueSampledData": {
            "origin": {"value": 0, "unit": "uV", "system": UCUM, "code": "uV"},
            "period": 1000.0 / raw.info["sfreq"],
            "dimensions": len(eeg_channels),
            "data": sampled_data_string(data_uV),
        },
    }
    entries.append(bundle_entry(obs, f"obs-sd-{edf_path.stem}"))
    return entries, window_s


# 3) DocumentReference (external attachment, no decomposition at all)
def build_documentreference_entries(file_meta: dict, patient_cache: dict) -> list:
    edf_path = file_meta["path"]
    _, eeg_names = load_sidecars(edf_path)
    from common import window_seconds_for
    import mne
    probe = mne.io.read_raw_edf(str(edf_path), preload=False, verbose=False)
    n_eeg_for_sizing = len(eeg_names) if eeg_names else len(probe.ch_names)
    window_s = window_seconds_for(probe.info["sfreq"], n_eeg_for_sizing)

    entries = []
    patient_uid = _patient_entry_if_new(file_meta["subject"], patient_cache, entries)

    start_dt = resolve_start_dt(probe.info.get("meas_date"), file_meta["session"])

    docref = {
        "resourceType": "DocumentReference",
        "status": "current",
        "type": {"coding": [{"system": "http://loinc.org", "code": "11523-8", "display": "EEG study"}]},
        "subject": {"reference": f"urn:uuid:{patient_uid}"},
        "date": start_dt.isoformat(),
        "content": [{
            "attachment": {
                "contentType": "application/edf",
                "url": openneuro_url(edf_path),
                "title": edf_path.name,
                "creation": start_dt.isoformat(),
            }
        }],
    }
    entries.append(bundle_entry(docref, f"docref-{edf_path.stem}"))
    return entries, window_s


# 4) UV PoCD SampleArrayObservation
# Real profile: http://hl7.org/fhir/uv/pocd/StructureDefinition/SampleArrayObservation
# (per-channel component[], each carrying its own valueSampledData — matches the
# official ECG lead example structure). IEEE 11073-10101 defines EEG
# electrode-placement *sites* but no per-electrode MDC term codes comparable to
# the ECG lead codes (MDC_ECG_ELEC_POTL_*) in the official example, so
# component.code carries `text` only, without a coding.

POCD_PROFILE = "http://hl7.org/fhir/uv/pocd/StructureDefinition/SampleArrayObservation"


def build_pocd_entries(file_meta: dict, patient_cache: dict) -> list:
    edf_path = file_meta["path"]
    sidecar, eeg_names = load_sidecars(edf_path)
    from common import window_seconds_for
    import mne
    probe = mne.io.read_raw_edf(str(edf_path), preload=False, verbose=False)
    n_eeg_for_sizing = len(eeg_names) if eeg_names else len(probe.ch_names)
    window_s = window_seconds_for(probe.info["sfreq"], n_eeg_for_sizing)
    raw, eeg_channels = load_window(edf_path, eeg_names, window_s)

    data, _ = raw.get_data(picks=eeg_channels, return_times=True)
    data_uV = data * 1e6

    entries = []
    patient_uid = _patient_entry_if_new(file_meta["subject"], patient_cache, entries)
    device_uid = f"device-pocd-{edf_path.stem}"
    entries.append(bundle_entry(_device_resource(sidecar), device_uid))

    start_dt = resolve_start_dt(raw.info.get("meas_date"), file_meta["session"])
    from datetime import timedelta
    end_dt = start_dt + timedelta(seconds=float(raw.times[-1]))
    period_ms = 1000.0 / raw.info["sfreq"]

    components = []
    for i, ch in enumerate(eeg_channels):
        components.append({
            "code": {"text": ch},
            "valueSampledData": {
                "origin": {"value": 0, "unit": "uV", "system": UCUM, "code": "uV"},
                "period": period_ms,
                "dimensions": 1,
                "data": sampled_data_string(data_uV[i:i + 1]),
            },
        })

    obs = {
        "resourceType": "Observation",
        "meta": {"profile": [POCD_PROFILE]},
        "status": file_meta["status"],
        "code": {"coding": [{"system": "http://loinc.org", "code": "11523-8", "display": "EEG study"}]},
        "subject": {"reference": f"urn:uuid:{patient_uid}"},
        "device": {"reference": f"urn:uuid:{device_uid}"},
        "effectivePeriod": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
        "component": components,
    }
    entries.append(bundle_entry(obs, f"obs-pocd-{edf_path.stem}"))
    return entries, window_s
