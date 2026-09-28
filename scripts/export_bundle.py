#!/usr/bin/env python3
"""
Export all TIDE evaluation resources from Blaze as a single FHIR R4 transaction Bundle.
Covers both pipelines:
  ds007808  - flat Observation model   (tide_pipeline.py)
  ds007823  - hierarchical model       (tide_pipeline_v2.py)

Output: results/tide_evaluation_bundle.json (submitted as .docx)
"""
import json
import logging
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

FHIR_BASE   = "http://localhost:8080/fhir"
RESULTS_DIR = Path(__file__).parent.parent / "results"
OUTPUT_PATH = RESULTS_DIR / "tide_evaluation_bundle.json"

RESOURCE_TYPES = ["Patient", "Device", "Endpoint", "Observation"]

TIDE_OBS_PROFILE = "http://example.org/tide/StructureDefinition/tide-observation"
TIDE_OBS_CHILD_PROFILE = "http://example.org/tide/StructureDefinition/tide-observation-child"

BUNDLE_TAG_DISPLAY = (
    "TIDE evaluation bundle — "
    "ds007808 (flat model, 1200 Hz, 128 ch) + "
    "ds007823 (hierarchical model, 200 Hz, 21-22 ch)"
)


# fetch
def fetch_all(resource_type: str) -> list:
    """Fetch every resource of a type, following FHIR pagination links."""
    resources = []
    url = f"{FHIR_BASE}/{resource_type}?_count=200"
    page = 0
    while url:
        page += 1
        try:
            r = requests.get(
                url,
                headers={"Accept": "application/fhir+json"},
                timeout=30,
            )
            if not r.ok:
                log.error("GET %s → HTTP %s", url, r.status_code)
                break
            bundle = r.json()
            entries = bundle.get("entry", [])
            resources.extend(e["resource"] for e in entries)
            log.info("  %s page %d: %d resource(s)", resource_type, page, len(entries))
            # follow next link if present
            url = next(
                (lnk["url"] for lnk in bundle.get("link", [])
                 if lnk.get("relation") == "next"),
                None,
            )
        except requests.RequestException as exc:
            log.error("Request failed for %s: %s", resource_type, exc)
            break
    return resources


# classify
def classify_observations(observations: list) -> dict:
    """
    Three-way split:
      flat     - TIDEObservation profile, no hasMember  (ds007808 single-resource model)
      parent   - TIDEObservation profile, has hasMember (ds007823 parent observations)
      child    - TIDEObservationChild profile           (ds007823 per-channel observations)
    """
    flat, parents, children = [], [], []
    for obs in observations:
        profiles  = obs.get("meta", {}).get("profile", [])
        has_tide  = TIDE_OBS_PROFILE in profiles
        has_child_profile = TIDE_OBS_CHILD_PROFILE in profiles
        has_member = bool(obs.get("hasMember"))
        if has_member:
            parents.append(obs)
        elif has_tide:
            flat.append(obs)
        elif has_child_profile:
            children.append(obs)
    return {"flat": flat, "parents": parents, "children": children}


# bundle
def build_bundle(all_resources: dict) -> dict:
    """
    Assemble a FHIR R4 Bundle of type 'transaction'.
    Entry order: Patient → Device → Endpoint → Observation (flat, parents, children).
    Each entry carries a fullUrl and a PUT request against its own resource id,
    so the bundle can be POSTed to any FHIR R4 server's base endpoint to recreate
    all resources under their original ids (preserving internal references).
    """
    entries = []
    for resource in (
        all_resources["patients"]
        + all_resources["devices"]
        + all_resources["endpoints"]
        + all_resources["obs_flat"]
        + all_resources["obs_parents"]
        + all_resources["obs_children"]
    ):
        rt  = resource["resourceType"]
        rid = resource["id"]
        entries.append({
            "fullUrl":  f"{FHIR_BASE}/{rt}/{rid}",
            "resource": resource,
            "request": {
                "method": "PUT",
                "url": f"{rt}/{rid}",
            },
        })

    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "meta": {
            "tag": [{
                "system":  "urn:tide:bundle:tag",
                "display": BUNDLE_TAG_DISPLAY,
            }]
        },
        "total": len(entries),
        "entry": entries,
    }


# summary
def print_summary(all_resources: dict):
    n_pat  = len(all_resources["patients"])
    n_dev  = len(all_resources["devices"])
    n_ep   = len(all_resources["endpoints"])
    n_flat = len(all_resources["obs_flat"])
    n_par  = len(all_resources["obs_parents"])
    n_ch   = len(all_resources["obs_children"])
    n_obs  = n_flat + n_par + n_ch
    total  = n_pat + n_dev + n_ep + n_obs

    print("\nBundle Summary")
    print(f"  Patients      {n_pat:>4}")
    print(f"  Devices       {n_dev:>4}")
    print(f"  Endpoints     {n_ep:>4}")
    print(f"  Observations  {n_obs:>4}")
    print(f"    flat (ds007808, TIDEObservation, no hasMember)       {n_flat:>3}")
    print(f"    parents  (ds007823, TIDEObservation, hasMember)      {n_par:>3}")
    print(f"    children (ds007823, TIDEObservationChild, per-channel) {n_ch:>3}")
    print(f"  Total resources in bundle                         {total:>4}")
    print(f"  Output: {OUTPUT_PATH}")
    print()


# main
def main():
    RESULTS_DIR.mkdir(exist_ok=True)

    log.info("Fetching resources from %s", FHIR_BASE)
    patients  = fetch_all("Patient")
    devices   = fetch_all("Device")
    endpoints = fetch_all("Endpoint")
    observations = fetch_all("Observation")

    obs_classes = classify_observations(observations)

    all_resources = {
        "patients":     patients,
        "devices":      devices,
        "endpoints":    endpoints,
        "obs_flat":     obs_classes["flat"],
        "obs_parents":  obs_classes["parents"],
        "obs_children": obs_classes["children"],
    }

    bundle = build_bundle(all_resources)

    OUTPUT_PATH.write_text(json.dumps(bundle, indent=2, ensure_ascii=False))
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    log.info("Written: %s (%.1f KB)", OUTPUT_PATH.name, size_kb)

    print_summary(all_resources)


if __name__ == "__main__":
    main()
