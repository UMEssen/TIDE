#!/usr/bin/env python3
"""
For each of the four approaches (TIDE, SampledData,
DocumentReference, UV PoCD SampleArrayObservation): wipes the isolated Blaze
instance (port 8081), builds one transaction Bundle covering all 5 source EDF
files (same representative window per file across all four approaches),
POSTs it once (timed = ingestion time), measures serialized bundle size and
resource count, then times 3 representative queries.

Output: results/ac2_comparison/quantitative_comparison.csv +
        results/ac2_comparison/report.md
"""
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    FILES, RESULTS_DIR, FHIR_BASE, wipe_all_resources, post_transaction_bundle,
    timed_get, probe_full_recording, load_sidecars, log,
)
from builders import (
    build_tide_entries, build_sampleddata_entries, build_documentreference_entries,
    build_pocd_entries,
)

# main TIDE deployment (separate from the isolated benchmark instance above)
MAIN_FHIR_BASE = "http://localhost:8080/fhir"


def count_main_deployment_resources() -> int:
    """Live resource count on the main (port 8080) TIDE Blaze instance."""
    import requests
    total = 0
    for rtype in ["Patient", "Device", "Endpoint", "Observation"]:
        r = requests.get(f"{MAIN_FHIR_BASE}/{rtype}", params={"_summary": "count"}, timeout=10)
        r.raise_for_status()
        total += r.json().get("total", 0)
    return total


APPROACHES = {
    "TIDE": {"builder": build_tide_entries, "resource_type": "Observation"},
    "SampledData": {"builder": build_sampleddata_entries, "resource_type": "Observation"},
    "DocumentReference": {"builder": build_documentreference_entries, "resource_type": "DocumentReference"},
    "PoCD_SampleArrayObservation": {"builder": build_pocd_entries, "resource_type": "Observation"},
}

QUERY_REPEATS = 5


def build_full_bundle(builder_fn):
    all_entries = []
    patient_cache = {}
    window_info = []
    for file_meta in FILES:
        entries, window_s = builder_fn(file_meta, patient_cache)
        all_entries.extend(entries)
        # per-file byte share, needed later for the linear full-duration extrapolation
        file_bytes = len(json.dumps(entries).encode("utf-8"))
        window_info.append({"file": file_meta["path"].name, "window_s": window_s,
                             "window_bytes": file_bytes})
    bundle = {"resourceType": "Bundle", "type": "transaction", "entry": all_entries}
    return bundle, window_info


def run_queries(resource_type: str, approach: str, sub03_patient_id: str, run01_period: dict):
    results = []

    # Q1: subject-scoped retrieval
    times = []
    n = None
    for _ in range(QUERY_REPEATS):
        t, n = timed_get(resource_type, {"subject": f"Patient/{sub03_patient_id}"})
        times.append(t)
    results.append({"query": "subject-scoped retrieval", "median_s": statistics.median(times),
                     "result_count": n, "supported": True})

    # Q2: time-window (date) retrieval
    times = []
    n = None
    for _ in range(QUERY_REPEATS):
        t, n = timed_get(resource_type, {"date": [f"ge{run01_period['start']}", f"le{run01_period['end']}"]})
        times.append(t)
    results.append({"query": "date-window retrieval", "median_s": statistics.median(times),
                     "result_count": n, "supported": True})

    # Q3: metric-level filter, Signal Stability Index < 0 dB. Only TIDE's decomposed component
    # structure supports this; uses the composite component-code-value-quantity
    # param so code+value bind to the same component (separate component-code /
    # component-value-quantity params would not guarantee that).
    if approach == "TIDE":
        times = []
        n = None
        for _ in range(QUERY_REPEATS):
            t, n = timed_get("Observation", {
                "component-code-value-quantity":
                    "http://example.org/tide/CodeSystem/tide-code-system|signalStabilityIndex$lt0",
            })
            times.append(t)
        results.append({"query": "metric-level filter (signalStabilityIndex<0dB)",
                         "median_s": statistics.median(times), "result_count": n, "supported": True})
    else:
        results.append({"query": "metric-level filter (signalStabilityIndex<0dB)",
                         "median_s": None, "result_count": None, "supported": False,
                         "note": "no per-metric FHIR search parameter exists for this data model "
                                 "(raw signal only, not queryable without decoding the payload)"})

    return results


def main():
    # sanity check: isolated instance reachable
    import requests
    try:
        requests.get(f"{FHIR_BASE}/metadata", timeout=10).raise_for_status()
    except Exception as exc:
        log.error("Isolated Blaze instance (port 8081) not reachable: %s", exc)
        log.error("Start it with: docker compose -f scripts/ac2_comparison/docker-compose.ac2.yml up -d")
        sys.exit(1)

    full_recording_info = {}
    for f in FILES:
        _, eeg_names = load_sidecars(f["path"])
        full_recording_info[f["path"].name] = probe_full_recording(f["path"], eeg_names)

    all_results = {}
    for approach, cfg in APPROACHES.items():
        log.info("Approach: %s", approach)
        wipe_all_resources()

        bundle, window_info = build_full_bundle(cfg["builder"])
        bundle_json = json.dumps(bundle)
        bundle_size_bytes = len(bundle_json.encode("utf-8"))
        resource_count = len(bundle["entry"])

        elapsed, response = post_transaction_bundle(bundle)
        if response is None:
            log.error("Ingestion failed for %s — skipping queries.", approach)
            continue

        # find sub-03's real Patient id + run-01 Observation/DocRef period for queries
        entries_resp = response["entry"]
        patient_ids = []
        run01_start = run01_end = None
        for i, e in enumerate(bundle["entry"]):
            loc = entries_resp[i].get("response", {}).get("location", "")
            # location is a full URL like http://localhost:8081/fhir/Patient/XYZ/_history/1
            after_fhir = loc.split("/fhir/", 1)[1] if "/fhir/" in loc else loc
            id_parts = after_fhir.split("/")  # [ResourceType, id, "_history", version]
            res = e["resource"]
            if res["resourceType"] == "Patient" and res["identifier"][0]["value"] == "sub-03":
                patient_ids.append(id_parts[1])
            if e["fullUrl"].endswith("sub-03_ses-20240821_task-speechopen_acq-pangolin_run-01_eeg"):
                period = res.get("effectivePeriod") or {"start": res.get("date"), "end": res.get("date")}
                run01_start, run01_end = period["start"], period["end"]

        sub03_id = patient_ids[0] if patient_ids else None
        query_results = run_queries(cfg["resource_type"], approach, sub03_id,
                                     {"start": run01_start, "end": run01_end})

        # Linear full-duration extrapolation. TIDE stores fixed-cardinality computed
        # metrics per channel (independent of recording duration) and DocumentReference
        # stores only a pointer — neither payload grows with duration, so their
        # FHIR-server bundle size at full duration equals the window figure above.
        # SampledData/PoCD embed the raw samples directly, so their payload scales
        # linearly with sample count; extrapolate per file and sum.
        scales_with_duration = approach in ("SampledData", "PoCD_SampleArrayObservation")
        bundle_size_mb = round(bundle_size_bytes / 1e6, 3)
        if scales_with_duration:
            extrapolated_bytes = sum(
                wi["window_bytes"] * (full_recording_info[wi["file"]]["full_duration_s"] / wi["window_s"])
                for wi in window_info
            )
            extrapolated_mb = round(extrapolated_bytes / 1e6, 2)
        else:
            # payload is duration-independent, so the full-duration figure IS the
            # measured window figure - reuse it directly rather than re-rounding
            # bundle_size_bytes at a different precision, which could otherwise
            # print a different number for the same underlying byte count.
            extrapolated_mb = bundle_size_mb

        all_results[approach] = {
            "resource_count": resource_count,
            "bundle_size_bytes": bundle_size_bytes,
            "bundle_size_mb": bundle_size_mb,
            "ingestion_time_s": round(elapsed, 4),
            "window_info": window_info,
            "queries": query_results,
            "scales_with_duration": scales_with_duration,
            "extrapolated_full_duration_mb": extrapolated_mb,
        }
        log.info("%s: %d resources, %.3f MB, %.3fs ingestion",
                  approach, resource_count, bundle_size_bytes / 1e6, elapsed)

    (RESULTS_DIR / "quantitative_comparison.json").write_text(json.dumps(all_results, indent=2))
    write_csv(all_results)
    try:
        main_deployment_count = count_main_deployment_resources()
    except Exception as exc:
        log.warning("Could not query main deployment (port 8080) resource count: %s", exc)
        main_deployment_count = None
    write_report(all_results, full_recording_info, main_deployment_count)
    log.info("Done. Results in %s", RESULTS_DIR)


def write_csv(all_results: dict):
    import csv
    path = RESULTS_DIR / "quantitative_comparison.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["approach", "resource_count", "bundle_size_mb", "extrapolated_full_duration_mb",
                    "scales_with_duration", "ingestion_time_s",
                    "q1_subject_median_s", "q2_datewindow_median_s",
                    "q3_metric_filter_median_s", "q3_metric_filter_supported"])
        for approach, r in all_results.items():
            q = {qr["query"]: qr for qr in r["queries"]}
            w.writerow([
                approach, r["resource_count"], r["bundle_size_mb"],
                r["extrapolated_full_duration_mb"], r["scales_with_duration"],
                r["ingestion_time_s"],
                round(q["subject-scoped retrieval"]["median_s"], 4),
                round(q["date-window retrieval"]["median_s"], 4),
                round(q["metric-level filter (signalStabilityIndex<0dB)"]["median_s"], 4)
                    if q["metric-level filter (signalStabilityIndex<0dB)"]["supported"] else "N/A",
                q["metric-level filter (signalStabilityIndex<0dB)"]["supported"],
            ])
    log.info("Wrote %s", path)


def write_report(all_results: dict, full_recording_info: dict, main_deployment_count: int = None):
    main_deployment_note = (f"{main_deployment_count}-resource" if main_deployment_count is not None
                             else "separately-deployed")
    lines = ["# AC2 Quantitative Comparison — TIDE vs. SampledData vs. DocumentReference vs. UV PoCD\n",
              "Same 5 source EDF files, same representative time window per file, isolated Blaze instance "
              f"(port 8081, separate from the main {main_deployment_note} TIDE deployment).\n",
              "## Representative window per file\n"]
    for approach, r in list(all_results.items())[:1]:
        for wi in r["window_info"]:
            full = full_recording_info[wi["file"]]
            lines.append(f"- `{wi['file']}`: {wi['window_s']:.1f}s window "
                         f"(full recording: {full['full_duration_s']:.0f}s, "
                         f"{full['n_channels']} channels, {full['sfreq']:.0f} Hz)")
    lines.append("\n## Results (measured, representative window)\n")
    lines.append("| Approach | Resources | Bundle size (MB) | Ingestion time (s) | "
                  "Q1 subject (s) | Q2 date-window (s) | Q3 metric-filter (s) |")
    lines.append("|---|---|---|---|---|---|---|")
    for approach, r in all_results.items():
        q = {qr["query"]: qr for qr in r["queries"]}
        q3 = q["metric-level filter (signalStabilityIndex<0dB)"]
        q3_str = f"{q3['median_s']:.4f}" if q3["supported"] else "not supported"
        lines.append(f"| {approach} | {r['resource_count']} | {r['bundle_size_mb']} | "
                      f"{r['ingestion_time_s']} | {q['subject-scoped retrieval']['median_s']:.4f} | "
                      f"{q['date-window retrieval']['median_s']:.4f} | {q3_str} |")
    lines.append("\nQ3 (metric-level filter, e.g. `signalStabilityIndex<0dB`) is only expressible against "
                 "TIDE's component-level structure; SampledData, DocumentReference and PoCD store raw "
                 "signal only and have no FHIR search parameter that can answer this without decoding "
                 "the payload client-side.\n")

    lines.append("\n## Full-recording-duration extrapolation (linear, clearly labeled)\n")
    lines.append("| Approach | Scales with duration? | Bundle size at full recording duration (MB) |")
    lines.append("|---|---|---|")
    for approach, r in all_results.items():
        scales = "yes — embeds raw samples" if r["scales_with_duration"] else "no — fixed-cardinality/pointer payload"
        lines.append(f"| {approach} | {scales} | {r['extrapolated_full_duration_mb']} |")
    duration_parts = " + ".join(f"{fi['full_duration_s']:.0f}s" for fi in full_recording_info.values())
    total_duration_h = sum(fi["full_duration_s"] for fi in full_recording_info.values()) / 3600
    lines.append("\nTIDE stores a fixed number of computed metrics per channel regardless of recording "
                 "duration, and DocumentReference stores only a pointer to the external file — neither "
                 "payload grows with duration, so their full-duration bundle size equals the measured "
                 "window figure. SampledData and PoCD embed the raw samples directly in the resource, so "
                 "their payload size scales linearly with sample count; the full-duration figure here is "
                 "`window_bundle_bytes × (full_duration_s / window_s)`, summed per file across all 5 "
                 f"recordings (full durations: {duration_parts} ≈ {total_duration_h:.1f} hours total).\n")
    (RESULTS_DIR / "report.md").write_text("\n".join(lines))
    log.info("Wrote %s", RESULTS_DIR / "report.md")


if __name__ == "__main__":
    main()
