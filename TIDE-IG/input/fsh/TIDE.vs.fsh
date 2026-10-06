ValueSet: TIDEValueSet
Id: tide-value-set
Title: "TIDE Value Set"
Description: "Representative starter set of modality codes from LOINC, SNOMED CT, 
            and TIDE modality codes for time series measurements, with a focus on 
            continuous waveform recordings. The set is extensible and not exhaustive."

* ^url = "http://example.org/tide/ValueSet/tide-value-set" 
* ^status = #active
* ^experimental = true
* ^version = "0.1.2"

// Supplemental continuous waveform modalities (for gaps in standard terminologies)
* include codes from system http://example.org/tide/CodeSystem/tide-supplemental-codes

// Neurophysiology 
* include http://loinc.org#11523-8 "EEG study"
* include http://snomed.info/sct#278221001 "Continuous electroencephalogram measure"
* include http://loinc.org#60852-1 "Electrical potential Muscle on EMG"
* include http://snomed.info/sct#252754006 "Surface electromyography"

// Cardiology
* include http://loinc.org#11524-6 "ECG study"
* include http://snomed.info/sct#266706003 "Continuous electrocardiogram monitoring"
* include http://loinc.org#80404-7 "R-R interval; standard deviation (heart rate variability)" 

// Pressure/Flow 
* include http://loinc.org#20059-2 "Airway pressure"
* include http://snomed.info/sct#250852008 "Airway pressure"
* include http://loinc.org#60791-1 "Airway flow"
* include http://loinc.org#60956-0 "Intracranial pressure (ICP)"
* include http://snomed.info/sct#250844005 "Intracranial pressure"
* include http://loinc.org#75997-7 "Systolic blood pressure by Continuous non-invasive monitoring"
* include http://snomed.info/sct#271649006 "Systolic blood pressure" // Derived values; continuous waveform represented via tide-supplemental-codes
* include http://loinc.org#75995-1 "Diastolic blood pressure by Continuous non-invasive monitoring"
* include http://snomed.info/sct#271650006 "Diastolic pressure" // Derived values; continuous waveform represented via tide-supplemental-codes

// Vital Signs (often discrete/derived; included as examples of extensibility)
* include http://loinc.org#9279-1 "Respiratory rate"
* include http://snomed.info/sct#86290005 "Respiratory rate"
* include http://loinc.org#20564-1 "Oxygen saturation in Blood"
* include http://snomed.info/sct#103228002 "Hemoglobin saturation with oxygen"
* include http://loinc.org#55284-4 "Blood pressure systolic and diastolic"
* include http://snomed.info/sct#75367002 "Blood pressure" // Derived value; continuous waveform represented via tide-supplemental-codes
* include http://loinc.org#8310-5 "Body temperature"
* include http://snomed.info/sct#703421000 "Temperature"

// Metabolic 
* include http://loinc.org#14749-6 "Glucose [Moles/volume] in serum or plasma" 
* include http://snomed.info/sct#365811003 "Finding of glucose level"
* include http://loinc.org#106793-3 "Continuous glucose monitoring time in ranges panel"


// Kinematics and Wearables 
* include http://loinc.org#82611-5 "Wearable device external physiologic monitoring panel"


// open to additions


// https://termbrowser.nhs.uk/?perspective=full&conceptId1=86290005&edition=uk-edition&release=v20250924&server=https://termbrowser.nhs.uk/sct-browser-api/snomed&langRefset=999000681000001101,999001251000000103
// Cave: Supplemental codes are provided via tide-supplemental-codes where standard terminologies lack sufficiently specific waveform concepts. See: Description