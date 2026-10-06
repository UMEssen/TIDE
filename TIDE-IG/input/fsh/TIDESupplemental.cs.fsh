CodeSystem: TIDESupplementalCodes
Id: tide-supplemental-codes
Title: "TIDE Supplemental Code System"
Description: "Supplemental modality codes for continuous high-resolution waveform time series where sufficiently specific concepts are not available 
            in standard terminologies (e.g., LOINC, SNOMED CT). This set is open to additions and not exhaustive."

* ^url = "http://example.org/tide/CodeSystem/tide-supplemental-codes" 
* ^status = #active
* ^experimental = true
* ^caseSensitive = true
* ^content = #complete
* ^version = "0.1.2"

* #airwayPressureWaveform "Airway pressure waveform"
  "Continuous airway pressure waveform (high-resolution)."

* #airwayFlowWaveform "Airway flow waveform"
  "Continuous airway flow waveform (high-resolution)."

* #intracranialPressureWaveform "Intracranial pressure waveform"
  "Continuous intracranial pressure waveform (high-resolution), e.g., invasive neuromonitoring signal."

* #arterialBloodPressureWaveform "Arterial blood pressure waveform"
  "Continuous arterial blood pressure waveform (high-resolution), e.g., invasive arterial line pressure signal."

* #eegWaveform "EEG waveform"
  "Continuous electroencephalogram waveform (high-resolution)."

// open to additions