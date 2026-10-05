Extension: TIDERawdataEndpointExtension
Id: tide-rawdata-endpoint
Title: "TIDE Rawdata Endpoint"
Description: "Reference to a FHIR Endpoint resource pointing to raw time-series data in a (dedicated) time-series database."

* ^url = "http://example.org/tide/StructureDefinition/tide-rawdata-endpoint"

* ^context.type = #element
* ^context.expression = "Observation"
* ^status = #active
* ^experimental = true

* value[x] only Reference(TIDEEndpoint) 