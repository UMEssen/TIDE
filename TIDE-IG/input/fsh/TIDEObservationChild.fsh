Profile: TIDEObservationChild
Parent: Observation
Id: tide-observation-child
Title: "TIDE Observation Child"
Description: "Per-channel child Observation in the TIDE hierarchical parent/child
            model. Each child Observation encodes channel-specific analytical
            metrics for one recording channel and identifies that channel via the
            structured bodySite element. Referenced by a parent TIDEObservation
            through the standard FHIR hasMember element."

* ^url = "http://example.org/tide/StructureDefinition/tide-observation-child"
* ^status = #active
* ^experimental = true
* ^version = "0.1.0"

* status 1..1 MS
* status from http://hl7.org/fhir/ValueSet/observation-status (required)

* code 1..1 MS
* code = http://loinc.org#11523-8 "EEG study"
* code ^short = "Fixed canonical modality text (LOINC 11523-8 'EEG study'), unrelated to channel identity. Channel identity is carried in bodySite."

* subject 1..1 MS
* subject only Reference(Patient or Group or Device or Location)
* subject ^short = "Same subject reference as the parent TIDEObservation, enabling a single subject-scoped query to retrieve the complete parent-child set."

* effective[x] only Period
* effectivePeriod 1..1 MS
* effectivePeriod.start 1..1 MS
* effectivePeriod.end 1..1 MS

* bodySite 1..1 MS
* bodySite from tide-channel-value-set (extensible)
* bodySite ^short = "Channel/electrode identity (e.g., Fp1), bound to TIDEChannelValueSet. The original source channel label is preserved in bodySite.text, including for non-standard labels mapped to the fallback code non-standard-channel."

* method 0..1
* method ^short = "Free-text description of the analytical computation method (e.g., compute_slices() implementation used)."

* device 1..1 MS
* device only Reference(Device)
* device ^short = "Acquisition device used to record the channel."

* derivedFrom 1..1 MS
* derivedFrom only Reference(Observation)
* derivedFrom ^short = "Back-reference to the parent TIDEObservation for this recording."

* value[x] 0..0
* value[x] ^short = "Not used. Per-channel results are stored in components."

// Components: open slicing, channel-specific subset of TIDECodeSystem
* component 0..* MS
* component ^slicing.discriminator[0].type = #pattern
* component ^slicing.discriminator[0].path = "code"
* component ^slicing.rules = #open
* component ^slicing.description = "Per-channel statistical summaries and data quality metrics, drawn from TIDECodeSystem."

* component contains
    signalMean 0..1 and
    signalMin 0..1 and
    signalMax 0..1 and
    signalStdDev 0..1 and
    snr 0..1 and
    dominantFrequency 0..1 and
    trendSlope 0..1 and
    signalEntropy 0..1 and
    samplingJitter 0..1 and
    anomalyCount 0..1

* component[signalMean].code = http://example.org/tide/CodeSystem/tide-code-system#signalMean
* component[signalMin].code = http://example.org/tide/CodeSystem/tide-code-system#signalMin
* component[signalMax].code = http://example.org/tide/CodeSystem/tide-code-system#signalMax
* component[signalStdDev].code = http://example.org/tide/CodeSystem/tide-code-system#signalStdDev
* component[snr].code = http://example.org/tide/CodeSystem/tide-code-system#snr
* component[dominantFrequency].code = http://example.org/tide/CodeSystem/tide-code-system#dominantFrequency
* component[trendSlope].code = http://example.org/tide/CodeSystem/tide-code-system#trendSlope
* component[signalEntropy].code = http://example.org/tide/CodeSystem/tide-code-system#signalEntropy
* component[samplingJitter].code = http://example.org/tide/CodeSystem/tide-code-system#samplingJitter
* component[anomalyCount].code = http://example.org/tide/CodeSystem/tide-code-system#anomalyCount

* component[signalMean].value[x] only Quantity
* component[signalMin].value[x] only Quantity
* component[signalMax].value[x] only Quantity
* component[signalStdDev].value[x] only Quantity
* component[snr].value[x] only Quantity
* component[dominantFrequency].value[x] only Quantity
* component[trendSlope].value[x] only Quantity
* component[signalEntropy].value[x] only Quantity
* component[samplingJitter].value[x] only Quantity
* component[samplingJitter].valueQuantity = http://unitsofmeasure.org#ms "ms"
* component[samplingJitter] ^short = "Standard deviation of sampling intervals (ms)."
* component[anomalyCount].value[x] only integer
