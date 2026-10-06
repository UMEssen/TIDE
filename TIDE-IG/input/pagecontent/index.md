### TIDE - Time Series Integration and Data in Endpoints

TIDE is a FHIR R4 Implementation Guide for representing continuous
high-resolution time series data (e.g., EEG, ECG, waveform monitoring) using a
Metadata-Proxy pattern: structured analytical metadata is carried in FHIR
Observation resources, while the underlying raw signal data is referenced
externally through TIDEEndpoint resources.

TIDE supports two representational models:

- **Flat model**: a single TIDEObservation carries all component slices of a recording: 
  global acquisition parameters once, and per-channel metrics repeated for each channel, with
  the source channel label in `component.code.text`.
- **Hierarchical parent/child model**: a parent TIDEObservation references one
  TIDEObservationChild per recording channel via `hasMember`, with each child
  carrying per-channel metrics and its channel identity in `bodySite`.

See the Artifacts page for the full set of profiles, extensions, and
terminology resources.
