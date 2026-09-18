Profile: TIDEObservation
Parent: Observation
Id: tide-observation
Title: "TIDE Observation"
Description: "Modality-agnostic TIDE (Time Series Integration and Data in Endpoints) Observation for 
            high frequency medical monitoring data."

* ^url = "http://example.org/tide/StructureDefinition/tide-observation"
* ^status = #active
* ^experimental = true
* ^version = "0.1.0"

* status 1..1 MS
* status from http://hl7.org/fhir/ValueSet/observation-status (required)
* status ^short = "preliminary (processing) | final (recording completed)"

* code 1..1 MS 
* code from tide-value-set (extensible)
* code ^short = "Type of the time series measurement, using standard terminologies (LOINC, SNOMED CT) or TIDE modality codes when no sufficiently specific standard code exists." 

* subject 1..1 MS
* subject only Reference(Patient or Group or Device or Location)
* subject ^short = "The subject that the time series refers to."

* effective[x] only Period 
* effectivePeriod 1..1 MS
* effectivePeriod.start 1..1 MS
* effectivePeriod.end 1..1 MS
* effectivePeriod ^short = "The exact time window covered by the recording."

* issued 0..1 // report time 
* issued ^short = "When was this observation result issued (reported/available)."

* value[x] 0..0 
* value[x] ^short = "Not used. Detailed results are stored in components or external raw data."

// Extension 
* extension contains tide-preview-endpoint named tide-preview-endpoint 0..1
* extension[tide-preview-endpoint] ^short = "Optional preview endpoint for the time series."

* extension contains tide-rawdata-endpoint named tide-rawdata-endpoint 1..1 MS
* extension[tide-rawdata-endpoint] ^short = "Endpoint to the raw time series in a database."

// Device 
* device 0..1 
* device only Reference(Device)
* device ^short = "Acquisition device used to record time series."

// Components: open slicing to allow generic + modality-specific analytics + searchable
* component 0..* MS
* component ^slicing.discriminator[0].type = #pattern
* component ^slicing.discriminator[0].path = "code"
* component ^slicing.rules = #open
* component ^slicing.description = "Slices for technical metadata, statistics and analysis results."

* component contains
    samplingFrequency 0..1 MS and
    sampleCount 0..1 and
    channelCount 0..1 and
    
    signalMean 0..* and
    signalMin 0..* and
    signalMax 0..* and
    signalStdDev 0..* and
    
    anomalyCount 0..* and
    eventCount 0..* and
    dataCoverage 0..1 and
    dataGaps 0..* and
    samplingJitter 0..* and
    snr 0..* and
    dominantFrequency 0..* and
    trendSlope 0..* and
    signalEntropy 0..*

// Canonical CodeSystem URLs are placeholders pending IG publication; will be
// updated to the final published URLs upon acceptance.
* component[samplingFrequency].code = http://example.org/tide/CodeSystem/tide-code-system#samplingFrequency
* component[sampleCount].code       = http://example.org/tide/CodeSystem/tide-code-system#sampleCount
* component[channelCount].code      = http://example.org/tide/CodeSystem/tide-code-system#channelCount

* component[signalMean].code        = http://example.org/tide/CodeSystem/tide-code-system#signalMean
* component[signalMin].code         = http://example.org/tide/CodeSystem/tide-code-system#signalMin
* component[signalMax].code         = http://example.org/tide/CodeSystem/tide-code-system#signalMax
* component[signalStdDev].code      = http://example.org/tide/CodeSystem/tide-code-system#signalStdDev

* component[anomalyCount].code      = http://example.org/tide/CodeSystem/tide-code-system#anomalyCount
* component[eventCount].code        = http://example.org/tide/CodeSystem/tide-code-system#eventCount
* component[dataCoverage].code      = http://example.org/tide/CodeSystem/tide-code-system#dataCoverage
* component[dataGaps].code          = http://example.org/tide/CodeSystem/tide-code-system#dataGaps
* component[samplingJitter].code    = http://example.org/tide/CodeSystem/tide-code-system#samplingJitter
* component[snr].code               = http://example.org/tide/CodeSystem/tide-code-system#snr
* component[dominantFrequency].code = http://example.org/tide/CodeSystem/tide-code-system#dominantFrequency
* component[trendSlope].code        = http://example.org/tide/CodeSystem/tide-code-system#trendSlope
* component[signalEntropy].code     = http://example.org/tide/CodeSystem/tide-code-system#signalEntropy

// Value types
* component[samplingFrequency].value[x] only Quantity
* component[samplingFrequency].valueQuantity = http://unitsofmeasure.org#Hz "Hz"
* component[samplingFrequency] ^short = "Sampling rate of the time series (Hz)."

* component[sampleCount].value[x] only integer
* component[sampleCount] ^short = "Total number of samples contained in the referenced time series segment."

* component[channelCount].value[x] only integer
* component[channelCount] ^short = "Number of simultaneously recorded channels."

* component[signalMean].value[x] only Quantity
* component[signalMean] ^short = "Arithmetic mean of the signal values."

* component[signalMin].value[x] only Quantity
* component[signalMin] ^short = "Lowest value recorded."

* component[signalMax].value[x] only Quantity
* component[signalMax] ^short = "Highest value recorded."

* component[signalStdDev].value[x] only Quantity
* component[signalStdDev] ^short = "Standard deviation of the signal values."

* component[anomalyCount].value[x] only integer
* component[anomalyCount] ^short = "Number of detected technical artifacts."

* component[eventCount].value[x] only integer
* component[eventCount] ^short = "Number of detected clinical events."

* component[dataCoverage].value[x] only Quantity
* component[dataCoverage].valueQuantity = http://unitsofmeasure.org#% "%"
* component[dataCoverage] ^short = "Percentage of valid data availability (0-100%)."

* component[dataGaps].value[x] only integer
* component[dataGaps] ^short = "Number of discontinuities/gaps in the stream."

* component[samplingJitter].value[x] only Quantity
* component[samplingJitter].valueQuantity = http://unitsofmeasure.org#ms "ms"
* component[samplingJitter] ^short = "Standard deviation of sampling intervals (ms)."

* component[snr].value[x] only Quantity
* component[snr].valueQuantity = http://unitsofmeasure.org#dB "dB"
* component[snr] ^short = "Signal-to-Noise Ratio (dB)."

* component[dominantFrequency].value[x] only Quantity
* component[dominantFrequency].valueQuantity = http://unitsofmeasure.org#Hz "Hz"
* component[dominantFrequency] ^short = "Frequency with the highest power spectral density,
                                        typically computed using Fourier-based spectral analysis over the effectivePeriod."

* component[trendSlope].value[x] only Quantity
* component[trendSlope] ^short = "Slope of signal baseline drift."

* component[signalEntropy].value[x] only Quantity
* component[signalEntropy] ^short = "Measure of signal complexity derived from the amplitude distribution 
                                    (e.g., Shannon entropy)."

// Hierarchical model: per-channel child Observations
* hasMember 0..*
* hasMember only Reference(Observation)
* hasMember ^short = "Per-channel child Observations (hierarchical model), conforming to the TIDEObservationChild profile. Each child encodes per-channel analytical metrics for one recording channel via the TIDECodeSystem component slices, with channel identity carried in bodySite."

// FHIR version R4 