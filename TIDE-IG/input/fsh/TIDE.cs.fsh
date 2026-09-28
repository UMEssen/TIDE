CodeSystem: TIDECodeSystem
Id: tide-code-system
Title: "TIDE Metadata and Quality Metrics Code System"
Description: "A comprehensive vocabulary for describing technical characteristics, 
            signal summaries, and data quality metrics of continuous medical time series data, 
            complementing standard terminologies like LOINC and SNOMED CT. Metrics may be 
            reported globally for an entire recording segment or separately for individual 
            channels in multi-channel recordings. Repeatable elements enable representation 
            of channel-specific analytical descriptors. This set is open to additions and not exhaustive."

* ^url = "http://example.org/tide/CodeSystem/tide-code-system" 
* ^status = #active
* ^experimental = true
* ^caseSensitive = true
* ^content = #complete
* ^version = "0.1.0"


* #samplingFrequency "Sampling frequency" 
    "The rate at which the signal is sampled per second (Hz). Important for reconstructing the time axis from raw data. Reported as a global property of the recording segment."
* #sampleCount "Sample count" 
    "Total number of samples contained in the referenced time series segment. Reported as a global count (for multi-channel recordings, this refers to the per-channel sample count when channels are aligned)."
* #channelCount "Channel count" 
    "Number of simultaneous recording channels included in the dataset. Reported as a global property of the recording."

// Statistics
* #signalMean "Signal mean" 
    "The arithmetic mean of the signal values. Can represent a global mean or the mean of a specific channel defined in the component. Repeatable to support per-channel metrics."
* #signalMin "Signal Minimum" 
    "The lowest value recorded. Can apply globally or to a specific channel. Repeatable for multi-channel recordings."
* #signalMax "Signal Maximum" 
    "The highest value recorded. Can apply globally or to a specific channel. Repeatable for multi-channel recordings."
* #signalStdDev "Signal Standard Deviation" 
    "Standard deviation of the signal values. Can apply globally or to a specific channel. Repeatable for multi-channel recordings."

// Data Quality and Further Analytics

* #anomalyCount "Technical Anomaly Count"
    "The number of detected technical artifacts or invalid data points (e.g., detached electrode, clipping). May be specified globally or per channel. Repeatable."

* #eventCount "Physiological Event Count"
    "The number of detected clinically relevant events (e.g., extrasystoles in ECG, spikes in EEG), distinct from technical anomalies. May be specified globally or per channel. Repeatable."

* #dataCoverage "Data Coverage"
    "The percentage of the total recording duration for which valid sample data is available (0-100%). Reported as a global metric for the recording/segment."

* #dataGaps "Data Gap Count"
    "The number of detected discontinuities or missing segments in the time series stream. May be specified globally or per channel. Repeatable."

* #samplingJitter "Sampling Jitter"
    "The standard deviation of the time intervals between successive samples. High jitter indicates timing instability in the acquisition device. May be specified globally or per channel. Repeatable."

* #signalStabilityIndex "Signal Stability Index"
    "A coefficient-of-variation-style measure of amplitude stability, computed as 20*log10(|mean|/standard deviation) and expressed in decibels (dB). Not a classical signal-power/noise-floor SNR. May be specified globally or per channel. Repeatable."

* #dominantFrequency "Dominant Frequency"
    "The frequency component with the highest power spectral density in the signal (e.g., Alpha peak in EEG). May be specified globally or per channel. Repeatable."

* #trendSlope "Signal Trend Slope"
    "The rate of change of the signal baseline over time, indicating a drift. May be specified globally or per channel. Repeatable."

* #signalEntropy "Signal Entropy"
    "A measure of the complexity, randomness, or unpredictability of the signal. May be specified globally or per channel. Repeatable."
