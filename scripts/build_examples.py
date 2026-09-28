#!/usr/bin/env python3
"""
Splits the live Blaze export bundle (results/tide_evaluation_bundle.json, produced by
export_bundle.py) into individual resource files under input/examples/, so the HL7
FHIR IG Publisher validates real instance data against declared profiles as part of
its normal QA run.

Resource scope (per tide_pipeline.py / tide_pipeline_v2.py):
  - Observation: flat ds007808 Observations and parent ds007823 Observations declare
    TIDEObservation; ds007823 per-channel children declare TIDEObservationChild.
  - Endpoint: declares the TIDE endpoint profile.
  - Patient, Device: no custom TIDE profile in either pipeline (base FHIR R4 only).
Every resource currently in the exported bundle is written as an example and
validated against its declared profile (Patient/Device examples are validated as
generic base-FHIR-R4-conformant). Per-type counts are computed from the live
bundle at runtime (see the profiled/unprofiled Counters below).
"""
import json
import logging
from collections import Counter
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
BUNDLE_PATH = PROJECT_ROOT / "results" / "tide_evaluation_bundle.json"
EXAMPLES_DIR = PROJECT_ROOT / "TIDE-IG" / "input" / "examples"


def main():
    bundle = json.loads(BUNDLE_PATH.read_text())
    entries = bundle.get("entry", [])

    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    for f in EXAMPLES_DIR.glob("*.json"):
        f.unlink()

    written = 0
    profiled = Counter()
    unprofiled = Counter()
    for entry in entries:
        res = entry["resource"]
        rtype, rid = res["resourceType"], res["id"]
        out_path = EXAMPLES_DIR / f"{rtype}-{rid}.json"
        out_path.write_text(json.dumps(res, indent=2))
        written += 1
        if res.get("meta", {}).get("profile"):
            profiled[rtype] += 1
        else:
            unprofiled[rtype] += 1

    log.info("Wrote %d example files to %s", written, EXAMPLES_DIR)
    log.info("With declared TIDE profile: %s", dict(profiled))
    log.info("No declared profile (base FHIR R4 only): %s", dict(unprofiled))


if __name__ == "__main__":
    main()
