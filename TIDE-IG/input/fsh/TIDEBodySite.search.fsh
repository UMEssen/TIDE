Instance: tide-observation-bodysite
InstanceOf: SearchParameter
Usage: #definition
Title: "TIDE Observation bodySite search parameter"
Description: "Enables searching TIDEObservationChild resources by channel/electrode
            identity via the bodySite element (e.g., Observation?bodysite=Fp1).
            bodySite is not a standard Observation search parameter in base FHIR R4;
            this custom SearchParameter registers it for the TIDE hierarchical
            model to support channel-specific queries."

* url = "http://example.org/tide/SearchParameter/tide-observation-bodysite"
* name = "TIDEObservationBodySiteSearchParameter"
* status = #active
* experimental = true
* version = "0.1.0"
* description = "Enables searching TIDEObservationChild resources by channel/electrode identity via the bodySite element (e.g., Observation?bodysite=Fp1). bodySite is not a standard Observation search parameter in base FHIR R4; this custom SearchParameter registers it for the TIDE hierarchical model to support channel-specific queries."

* base = #Observation
* code = #bodysite
* type = #token
* expression = "Observation.bodySite"
* xpath = "f:Observation/f:bodySite"
* xpathUsage = #normal
