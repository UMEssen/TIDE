#!/usr/bin/env python3
"""
TIDE evaluation 

ds007808 (tide_pipeline.py, flat model):
  sub-03, 2 runs, 1200 Hz, 128 channels.
  Purpose: demonstrates TIDE's high-frequency scalability and the flat Observation
  model where all 16 slices (global + per-channel) live as components of one resource.

ds007823 (tide_pipeline_v2.py, hierarchical model):
  3 subjects, 1 EDF each, 200 Hz, 21-22 named 10-20 channels.
  Purpose: demonstrates the hierarchical parent/child Observation model with
  clinically meaningful electrode names (Fp1, Cz, T3…).  Per-channel metrics
  become independently searchable FHIR resources.

Both datasets target the same Blaze instance; subjects are non-overlapping.
Precision/recall is reported separately per dataset because the sidecar fields
available for verification differ (ds007808 has Manufacturer/Model; ds007823 does not).
"""
import json
import logging
import re
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
RESULTS_DIR  = PROJECT_ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

PROCESSED_FILE_V1 = PROJECT_ROOT / "processed_files.json"
PROCESSED_FILE_V2 = PROJECT_ROOT / "processed_files_v2.json"

# same TIDECodeSystem URL as tide_pipeline.py's TIDE_CS
TIDE_CS = "http://example.org/tide/CodeSystem/tide-code-system"
DATA_DIR = PROJECT_ROOT / "data"
FHIR_BASE = "http://localhost:8080/fhir"

OPENNEURO_S3_BASE = "https://s3.amazonaws.com/openneuro.org"


def openneuro_url(edf_path: Path) -> str:
    relative = edf_path.resolve().relative_to((PROJECT_ROOT / "data").resolve())
    return f"{OPENNEURO_S3_BASE}/{relative.as_posix()}"

# ds007808: sub-03_ses-20240821_task-speechopen_acq-pangolin_run-01_eeg.edf
BIDS_RE_V1 = re.compile(
    r"sub-(?P<subject>[^_]+)_ses-(?P<session>[^_]+)_task-(?P<task>[^_]+)_"
    r"acq-(?P<acq>[^_]+)_run-(?P<run>\d+)_eeg\.edf$"
)
# ds007823: sub-CUCOV003_task-COVID_eeg.edf
BIDS_RE_V2 = re.compile(r"sub-(?P<subject>[^_]+)_task-(?P<task>[^_]+)_eeg\.edf$")

# ds007808 sidecar fields available for verification
SIDECAR_FIELDS_V1 = [
    "SamplingFrequency",
    "EEGChannelCount",
    "Manufacturer",
    "ManufacturersModelName",
    "PowerLineFrequency",
]
# ds007823 sidecar has no Manufacturer/Model fields
SIDECAR_FIELDS_V2 = [
    "SamplingFrequency",
    "EEGChannelCount",
    "PowerLineFrequency",
]


# FHIR helpers
def fhir_get(path: str, params: dict = None):
    try:
        r = requests.get(
            f"{FHIR_BASE}/{path}",
            params=params,
            headers={"Accept": "application/fhir+json"},
            timeout=30,
        )
        if r.ok:
            return r.json(), r.status_code
        log.warning("GET %s → HTTP %s", path, r.status_code)
        return None, r.status_code
    except requests.RequestException as exc:
        log.error("GET %s failed: %s", path, exc)
        return None, 0


def bundle_entries(bundle) -> list:
    if bundle is None:
        return []
    return bundle.get("entry", [])


def bundle_total(bundle) -> int:
    if bundle is None:
        return 0
    return bundle.get("total", len(bundle_entries(bundle)))


def get_resource(resource_type: str, rid: str) -> dict:
    body, _ = fhir_get(f"{resource_type}/{rid}")
    return body or {}


def get_patient_id(identifier: str) -> str:
    """Resolve a server-assigned Patient ID by BIDS identifier value."""
    bundle, _ = fhir_get("Patient", {"identifier": identifier})
    entries = bundle_entries(bundle)
    if entries:
        return entries[0]["resource"]["id"]
    log.warning("Patient not found for identifier '%s'", identifier)
    return None


def get_observations_for_subject(full_subject_id: str) -> list:
    """
    Uses subject=Patient/<id> instead of subject.identifier= because Blaze does
    not reliably execute chained identifier searches without additional index config
    (see run_example_queries()).
    """
    patient_id = get_patient_id(full_subject_id)
    params = ({"subject": f"Patient/{patient_id}", "_count": "200"} if patient_id
              else {"subject.identifier": full_subject_id, "_count": "200"})
    bundle, _ = fhir_get("Observation", params)
    return [e["resource"] for e in bundle_entries(bundle)]


def component_value(obs: dict, code: str):
    """Return the scalar value (float or int) for a component code, or None."""
    for comp in obs.get("component", []):
        for coding in comp.get("code", {}).get("coding", []):
            if coding.get("code") == code:
                if "valueQuantity" in comp:
                    return comp["valueQuantity"].get("value")
                if "valueInteger" in comp:
                    return comp["valueInteger"]
    return None


def endpoint_address_from_obs(obs: dict) -> str:
    """Resolve the rawdata Endpoint address from an Observation's extension."""
    for ext in obs.get("extension", []):
        if "rawdata-endpoint" in ext.get("url", ""):
            ref = ext.get("valueReference", {}).get("reference", "")
            if ref.startswith("Endpoint/"):
                eid = ref.split("/", 1)[1]
                ep = get_resource("Endpoint", eid)
                return ep.get("address", "")
    return ""


def device_info_from_obs(obs: dict) -> dict:
    """Return {manufacturer, model} from the Device referenced by an Observation."""
    ref = obs.get("device", {}).get("reference", "")
    if ref.startswith("Device/"):
        did = ref.split("/", 1)[1]
        dev = get_resource("Device", did)
        manufacturer = dev.get("manufacturer", "")
        names = dev.get("deviceName", [])
        model = names[0].get("name", "") if names else ""
        return {"manufacturer": manufacturer, "model": model}
    return {"manufacturer": "", "model": ""}


# precision / recall
def _values_match(a, b, rel_tol: float = 0.01) -> bool:
    """Fuzzy match: numeric within 1% tolerance, strings case-insensitive."""
    if a is None or b is None:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if b == 0:
            return a == 0
        return abs(a - b) / abs(b) <= rel_tol
    return str(a).strip().lower() == str(b).strip().lower()


def evaluate_pr_v1(processed_files: list) -> pd.DataFrame:
    """
    Precision/recall for ds007808 (flat model).
    Verifiable sidecar fields: SamplingFrequency, EEGChannelCount,
    Manufacturer, ManufacturersModelName, PowerLineFrequency.
    TIDE populates the first four; PowerLineFrequency is not a TIDE slice.
    """
    rows = []

    for edf_str in processed_files:
        edf_path = Path(edf_str)
        parsed = BIDS_RE_V1.match(edf_path.name)
        if not parsed:
            continue
        p = parsed.groupdict()
        full_subject_id = f"sub-{p['subject']}"
        run_label = f"sub-{p['subject']}_ses-{p['session']}_run-{p['run']}"

        sidecar_path = edf_path.with_name(edf_path.name.replace("_eeg.edf", "_eeg.json"))
        try:
            sidecar = json.loads(sidecar_path.read_text()) if sidecar_path.exists() else {}
        except Exception:
            sidecar = {}
        gt = {f: sidecar.get(f) for f in SIDECAR_FIELDS_V1 if f in sidecar}

        # flat model: match observation by endpoint address
        obs_list = get_observations_for_subject(full_subject_id)
        matched_obs = None
        for obs in obs_list:
            if endpoint_address_from_obs(obs) == openneuro_url(edf_path):
                matched_obs = obs
                break
        if matched_obs is None and obs_list:
            log.warning("No exact match for %s; using first available.", run_label)
            matched_obs = obs_list[0]
        if matched_obs is None:
            log.warning("No Observation in FHIR for %s", run_label)
            rows.append({"run": run_label, "precision": None, "recall": None,
                         "note": "No Observation in FHIR"})
            continue

        tide_extracted = {
            "SamplingFrequency": component_value(matched_obs, "samplingFrequency"),
            "EEGChannelCount":   component_value(matched_obs, "channelCount"),
        }
        dev = device_info_from_obs(matched_obs)
        tide_extracted["Manufacturer"]           = dev["manufacturer"] or None
        tide_extracted["ManufacturersModelName"] = dev["model"] or None

        tide_populated = {k: v for k, v in tide_extracted.items() if v is not None}
        n_tide    = len(tide_populated)
        n_correct = sum(1 for f, v in tide_populated.items()
                        if f in gt and _values_match(v, gt[f]))
        precision = round(n_correct / n_tide, 4) if n_tide > 0 else 0.0
        recall    = round(n_correct / len(gt),  4) if gt       else 0.0
        rows.append({"run": run_label, "gt_fields": len(gt), "tide_populated": n_tide,
                     "correct": n_correct, "precision": precision, "recall": recall,
                     "note": ""})
        log.info("[v1] %s  precision=%.2f  recall=%.2f", run_label, precision, recall)

    return pd.DataFrame(rows)


def evaluate_pr_v2(processed_files: list) -> pd.DataFrame:
    """
    Precision/recall for ds007823 (hierarchical model).
    Verifiable sidecar fields: SamplingFrequency, EEGChannelCount, PowerLineFrequency.
    ds007823 sidecars carry no Manufacturer/ManufacturersModelName.
    TIDE populates SamplingFrequency and EEGChannelCount (from parent global slices).
    PowerLineFrequency is not a TIDE slice.

    Parent observations are identified by the presence of hasMember.
    Children (no hasMember) are skipped for P/R evaluation.
    """
    rows = []

    for edf_str in processed_files:
        edf_path = Path(edf_str)
        parsed = BIDS_RE_V2.match(edf_path.name)
        if not parsed:
            continue
        p = parsed.groupdict()
        full_subject_id = f"sub-{p['subject']}"
        run_label = f"sub-{p['subject']}_task-{p['task']}"

        sidecar_path = edf_path.with_name(edf_path.name.replace("_eeg.edf", "_eeg.json"))
        try:
            sidecar = json.loads(sidecar_path.read_text()) if sidecar_path.exists() else {}
        except Exception:
            sidecar = {}
        gt = {f: sidecar.get(f) for f in SIDECAR_FIELDS_V2 if f in sidecar}

        # hierarchical model: parent has hasMember; match by endpoint address
        all_obs  = get_observations_for_subject(full_subject_id)
        parents  = [o for o in all_obs if o.get("hasMember")]
        matched_obs = None
        for obs in parents:
            if endpoint_address_from_obs(obs) == openneuro_url(edf_path):
                matched_obs = obs
                break
        if matched_obs is None and parents:
            log.warning("No exact parent match for %s; using first parent.", run_label)
            matched_obs = parents[0]
        if matched_obs is None:
            log.warning("No parent Observation in FHIR for %s", run_label)
            rows.append({"run": run_label, "precision": None, "recall": None,
                         "note": "No parent Observation in FHIR"})
            continue

        tide_extracted = {
            "SamplingFrequency": component_value(matched_obs, "samplingFrequency"),
            "EEGChannelCount":   component_value(matched_obs, "channelCount"),
        }
        # PowerLineFrequency: not a TIDE slice, intentionally absent

        tide_populated = {k: v for k, v in tide_extracted.items() if v is not None}
        n_tide    = len(tide_populated)
        n_correct = sum(1 for f, v in tide_populated.items()
                        if f in gt and _values_match(v, gt[f]))
        precision = round(n_correct / n_tide, 4) if n_tide > 0 else 0.0
        recall    = round(n_correct / len(gt),  4) if gt       else 0.0
        n_children = len(matched_obs.get("hasMember", []))
        rows.append({"run": run_label, "gt_fields": len(gt), "tide_populated": n_tide,
                     "correct": n_correct, "precision": precision, "recall": recall,
                     "child_observations": n_children, "note": ""})
        log.info("[v2] %s  precision=%.2f  recall=%.2f  children=%d",
                 run_label, precision, recall, n_children)

    return pd.DataFrame(rows)

# implementation workflow validation
def build_workflow_summary(processed_v1: list, processed_v2: list) -> dict:
    """
    Cross-checks how many EDF files were discovered vs. successfully processed
    per dataset, and cross-validates against live Blaze resource counts. Reports
    pipeline reliability (files in -> resources out), separate from whether the
    computed values are numerically correct (see metric_validation_report.md).
    """
    found_v1 = sorted(str(p) for p in (DATA_DIR / "ds007808").rglob("*_eeg.edf"))
    found_v2 = sorted(str(p) for p in (DATA_DIR / "ds007823").rglob("*_eeg.edf"))

    counts = {}
    for rt in ("Patient", "Device", "Endpoint", "Observation"):
        bundle, _ = fhir_get(rt, {"_summary": "count"})
        counts[rt] = bundle_total(bundle) if bundle else None

    return {
        "ds007808": {
            "edf_found": len(found_v1),
            "edf_processed": len(processed_v1),
            "failures": len(found_v1) - len(processed_v1),
        },
        "ds007823": {
            "edf_found": len(found_v2),
            "edf_processed": len(processed_v2),
            "failures": len(found_v2) - len(processed_v2),
        },
        "blaze_counts": counts,
    }


def _workflow_summary_md(summary: dict) -> list:
    lines = [
        "Pipeline steps (see `process_edf()`, `scripts/tide_pipeline.py:440`): "
        "parse BIDS filename -> read sidecar/channels/events -> load EDF via `mne` -> "
        "`compute_slices()` -> create/reuse Patient -> create Device -> create rawdata "
        "Endpoint -> build Observation -> POST to Blaze. Each stage is wrapped in its "
        "own try/except; a failure at any stage aborts that file and is logged, without "
        "aborting the run.",
        "",
        "| Dataset | EDF files found | Processed successfully | Failures |",
        "| --- | --- | --- | --- |",
    ]
    for ds in ("ds007808", "ds007823"):
        s = summary[ds]
        lines.append(f"| {ds} | {s['edf_found']} | {s['edf_processed']} | {s['failures']} |")
    lines += [
        "",
        "Cross-check against live Blaze resource counts:",
        "",
        "| Resource | Count |",
        "| --- | --- |",
    ]
    for rt, n in summary["blaze_counts"].items():
        lines.append(f"| {rt} | {n} |")
    return lines


# example FHIR queries
def run_example_queries() -> list:
    """
    Build and run example FHIR queries, resolving Patient IDs at runtime.
    Same subject=Patient/<id> rationale as get_observations_for_subject().
    """
    sub03_id    = get_patient_id("sub-03")
    cucov003_id = get_patient_id("sub-CUCOV003")

    queries = [
        # ds007808 — flat model
        ("ds007808: All Observations for sub-03 (flat model)",
         "Observation",
         {"subject": f"Patient/{sub03_id}", "_count": "50"} if sub03_id
         else {"subject.identifier": "sub-03", "_count": "50"}),
        # ds007808 — status filter (no subject needed, works cross-subject)
        ("ds007808: Preliminary-status Observations",
         "Observation",
         {"status": "preliminary", "_count": "50"}),
        # ds007823 — hierarchical model (returns parent + all channel children)
        ("ds007823: All Observations for sub-CUCOV003 (parent + children)",
         "Observation",
         {"subject": f"Patient/{cucov003_id}", "_count": "50"} if cucov003_id
         else {"subject.identifier": "sub-CUCOV003", "_count": "50"}),
        # cross-dataset date filter
        ("Cross-dataset: All Observations from 1985-01-01 onwards",
         "Observation",
         {"date": "ge1985-01-01", "_count": "100"}),
        # metric-level filter: composite search param binds code+value to the same component
        ("Metric-level filter: Signal Stability Index < 0 dB",
         "Observation",
         {"component-code-value-quantity": f"{TIDE_CS}|signalStabilityIndex$lt0", "_count": "50"}),
        ("Metric-level filter: dataCoverage >= 100%",
         "Observation",
         {"component-code-value-quantity": f"{TIDE_CS}|dataCoverage$ge100", "_count": "50"}),
        ("Metric-level filter: dominantFrequency >= 8 Hz",
         "Observation",
         {"component-code-value-quantity": f"{TIDE_CS}|dominantFrequency$ge8", "_count": "50"}),
        # channel-level filter via the custom TIDEObservationBodySiteSearchParameter
        ("Channel-level filter: bodysite = Fp1",
         "Observation",
         {"bodysite": "Fp1", "_count": "50"}),
    ]

    results = []
    for label, resource_type, params in queries:
        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{FHIR_BASE}/{resource_type}?{param_str}"
        bundle, status_code = fhir_get(resource_type, params)
        n = bundle_total(bundle)
        results.append({
            "label":       label,
            "url":         url,
            "http_status": status_code,
            "n_results":   n,
        })
        print(f"\n  {label}")
        print(f"  URL: {url}")
        print(f"  HTTP {status_code} → {n} result(s)")
    return results


# markdown report
def _df_to_md(df: pd.DataFrame) -> str:
    cols = df.columns.tolist()
    header = "| " + " | ".join(cols) + " |"
    sep    = "| " + " | ".join("---" for _ in cols) + " |"
    rows   = [
        "| " + " | ".join(str(v) for v in row) + " |"
        for row in df.itertuples(index=False)
    ]
    return "\n".join([header, sep] + rows)


def _pr_summary(pr_df: pd.DataFrame) -> list:
    """Return markdown lines for a precision/recall DataFrame."""
    if pr_df.empty:
        return ["*No processed files found.*"]
    display_cols = [c for c in ["run", "gt_fields", "tide_populated", "correct",
                                "precision", "recall", "child_observations", "note"]
                    if c in pr_df.columns]
    lines = [_df_to_md(pr_df[display_cols])]
    valid_p = pr_df["precision"].dropna()
    valid_r = pr_df["recall"].dropna()
    if not valid_p.empty:
        lines += ["", f"**Mean precision:** {valid_p.mean():.4f}",
                      f"**Mean recall:** {valid_r.mean():.4f}"]
    return lines


def generate_report(
    pr_df_v1: pd.DataFrame,
    pr_df_v2: pd.DataFrame,
    query_results: list,
    workflow_summary: dict = None,
) -> str:
    lines = [
        "# TIDE Evaluation Report",
        "",
        "FHIR server: Blaze (samply/blaze:latest)",
        "",
        "## Two-Dataset Evaluation Strategy",
        "",
        "| Dataset | Pipeline | Sampling rate | Channels | Model |",
        "| --- | --- | --- | --- | --- |",
        "| ds007808 (OpenNeuro) | tide_pipeline.py | 1200 Hz | 128 (generic labels) "
        "| Flat: all 16 slices as components of one Observation |",
        "| ds007823 (OpenNeuro) | tide_pipeline_v2.py | 200 Hz | 21-22 (10-20 names) "
        "| Hierarchical: parent Observation + N child Observations via hasMember |",
        "",
        "ds007808 demonstrates TIDE's scalability at high sampling frequency. "
        "ds007823 demonstrates the hierarchical model with clinically named electrodes "
        "(Fp1, Cz, T3, …) that become independently searchable FHIR resources.",
        "",
        "---",
        "",
        "## 1. Precision & Recall — ds007808 (Flat Model)",
        "",
        "Sidecar fields verified: SamplingFrequency, EEGChannelCount, Manufacturer, "
        "ManufacturersModelName, PowerLineFrequency",
        "",
    ]
    lines += _pr_summary(pr_df_v1)

    lines += [
        "",
        "---",
        "",
        "## 2. Precision & Recall — ds007823 (Hierarchical Model)",
        "",
        "Sidecar fields verified: SamplingFrequency, EEGChannelCount, PowerLineFrequency  ",
        "_(ds007823 carries no Manufacturer/ManufacturersModelName in the sidecar)_",
        "",
        "Values extracted from parent Observation global slices only; "
        "child_observations column shows the hasMember count per recording.",
        "",
    ]
    lines += _pr_summary(pr_df_v2)

    lines += [
        "",
        "---",
        "",
        "## 3. Static Coverage: TIDE vs. Competing FHIR Approaches",
        "",
        "See Manuscript Appendix 3 for the structural capability comparison "
        "(TIDE vs. UV PoCD SampleArrayObservation vs. SampledData vs. DocumentReference).",
        "",
        "---",
        "",
        "## 4. Example FHIR Queries Against Blaze",
        "",
    ]
    for qr in query_results:
        lines += [
            f"### {qr['label']}",
            "",
            f"- **URL:** `{qr['url']}`",
            f"- **HTTP status:** {qr['http_status']}",
            f"- **Results found:** {qr['n_results']}",
            "",
        ]

    if workflow_summary is not None:
        lines += [
            "---",
            "",
            "## 5. Implementation Workflow Validation",
            "",
        ]
        lines += _workflow_summary_md(workflow_summary)
        lines += [""]

    return "\n".join(lines)


# main
def main():
    print("\n TIDE Evaluation \n")

    # load processed files from both pipelines
    def _load(path):
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                pass
        return []

    processed_v1 = _load(PROCESSED_FILE_V1)
    processed_v2 = _load(PROCESSED_FILE_V2)
    log.info("v1 processed: %d file(s)  |  v2 processed: %d file(s)",
             len(processed_v1), len(processed_v2))

    # precision & recall — v1
    print("\nPrecision & Recall: ds007808 (flat model)")
    pr_df_v1 = evaluate_pr_v1(processed_v1)
    if not pr_df_v1.empty:
        print(pr_df_v1.to_string(index=False))
    else:
        print("No data — run tide_pipeline.py first.")
    pr_df_v1.to_csv(RESULTS_DIR / "precision_recall_v1.csv", index=False)
    log.info("Saved precision_recall_v1.csv")

    # precision & recall — v2
    print("\nPrecision & Recall: ds007823 (hierarchical model)")
    pr_df_v2 = evaluate_pr_v2(processed_v2)
    if not pr_df_v2.empty:
        print(pr_df_v2.to_string(index=False))
    else:
        print("No data — run tide_pipeline_v2.py first.")
    pr_df_v2.to_csv(RESULTS_DIR / "precision_recall_v2.csv", index=False)
    log.info("Saved precision_recall_v2.csv")

    # example FHIR queries
    print("\nExample FHIR Queries")
    query_results = run_example_queries()

    # implementation workflow validation
    print("\nImplementation Workflow Validation")
    workflow_summary = build_workflow_summary(processed_v1, processed_v2)
    for ds in ("ds007808", "ds007823"):
        s = workflow_summary[ds]
        print(f"  {ds}: {s['edf_processed']}/{s['edf_found']} processed, {s['failures']} failures")
    print(f"  Blaze counts: {workflow_summary['blaze_counts']}")

    # evaluation report
    report_md = generate_report(pr_df_v1, pr_df_v2, query_results, workflow_summary)
    report_path = RESULTS_DIR / "evaluation_report.md"
    report_path.write_text(report_md)
    log.info("Saved evaluation_report.md")

    print(f"\nAll results saved to {RESULTS_DIR}/")
    print("  precision_recall_v1.csv")
    print("  precision_recall_v2.csv")
    print("  evaluation_report.md")


if __name__ == "__main__":
    main()
