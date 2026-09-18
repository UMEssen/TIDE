# TIDE — Time Series Integration and Data in Endpoints

TIDE is a FHIR R4 Implementation Guide for representing continuous high-resolution
time series data (e.g., EEG, ECG, waveform monitoring) using a Metadata-Proxy
pattern: structured analytical metadata is carried in FHIR Observation resources,
while the underlying raw signal data is referenced externally through TIDEEndpoint
resources.

This repository accompanies the manuscript *"Exchange of High Frequency Medical Monitoring Data Using Fast Healthcare 
Interoperability Resources for Interoperable Integration Into Clinical Practice and Research: Methodological Development Study."* 
(submitted to JMIR Medical Informatics) and contains the full source needed to reproduce the FHIR profiles, the evaluation pipeline and
the implementation guide referenced there.

## Repository structure

| Path | Contents |
|---|---|
| `TIDE-IG/` | Buildable FHIR Implementation Guide (SUSHI project: `sushi-config.yaml`, `input/fsh/`, `input/pagecontent/`) — sole source for all profiles, extensions, and terminology |
| `scripts/` | Evaluation pipeline: EDF/BIDS ingestion, FHIR resource construction, precision/recall evaluation against the two datasets below |
| `tide_evaluation_bundle.html` | FHIR transaction Bundle containing all resources produced during the proof-of-concept evaluation, for direct inspection or loading into an independent FHIR R4 server |

## TIDE artifacts

| Type | Name | Canonical URL |
|---|---|---|
| Profile | TIDEObservation | `http://example.org/tide/StructureDefinition/tide-observation` |
| Profile | TIDEObservationChild | `http://example.org/tide/StructureDefinition/tide-observation-child` |
| Profile | TIDEEndpoint | `http://example.org/tide/StructureDefinition/tide-endpoint` |
| Extension | RawDataEndpoint | `http://example.org/tide/StructureDefinition/tide-rawdata-endpoint` |
| Extension | PreviewEndpoint | `http://example.org/tide/StructureDefinition/tide-preview-endpoint` |
| CodeSystem | TIDECodeSystem | `http://example.org/tide/CodeSystem/tide-code-system` |
| CodeSystem | TIDESupplementalCodes | `http://example.org/tide/CodeSystem/tide-supplemental-codes` |
| CodeSystem | TIDEChannelCodeSystem | `http://example.org/tide/CodeSystem/tide-channel-code-system` |
| ValueSet | TIDEValueSet | `http://example.org/tide/ValueSet/tide-value-set` |
| ValueSet | TIDEChannelValueSet | `http://example.org/tide/ValueSet/tide-channel-value-set` |
| SearchParameter | tide-observation-bodysite | `http://example.org/tide/SearchParameter/tide-observation-bodysite` |

> **Note:** canonical URLs are currently placeholders (`http://example.org/tide/...`)
> and will be updated to their final published location upon acceptance of the
> associated manuscript.

## Building the Implementation Guide

```
cd TIDE-IG
sushi .
```

Requires [SUSHI](https://fshschool.org/docs/sushi/) and, for the full HTML rendering,
the [FHIR IG Publisher](https://confluence.hl7.org/display/FHIR/IG+Publisher+Documentation).

## Running the evaluation pipeline

```
# start any local FHIR R4 server (e.g. Blaze: https://github.com/samply/blaze) on :8080
pip install mne numpy scipy pandas requests
python scripts/tide_pipeline.py       # flat model (ds007808)
python scripts/tide_pipeline_v2.py    # hierarchical model (ds007823)
python scripts/evaluate.py            # precision/recall + coverage report
```

## Data

This repository does not include raw EEG data. The pipeline consumes two public,
CC0-licensed BIDS-EEG datasets directly from OpenNeuro:

| Dataset | Description | DOI |
|---|---|---|
| ds007808 | EEG-Speech Brain Decoding Dataset | [10.18112/openneuro.ds007808.v1.0.0](https://doi.org/10.18112/openneuro.ds007808.v1.0.0) |
| ds007823 | COVID-19 survivors and close contacts EEG dataset | [10.18112/openneuro.ds007823.v1.0.1](https://doi.org/10.18112/openneuro.ds007823.v1.0.1) |

Raw signal files themselves stay in place on OpenNeuro; TIDE's `TIDEEndpoint`
resources reference them there rather than duplicating them.


## Contact

Corresponding Author:
Dr. René Hosch
University Hospital Essen
Hufelandstraße 55, 45147 Essen
rene.hosch@uk-essen.de

