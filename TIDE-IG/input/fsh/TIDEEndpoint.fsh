Profile: TIDEEndpoint
Parent: Endpoint
Id: tide-endpoint
Title: "TIDE Endpoint"
Description: "Standardized Endpoint profile for the TIDE Observation 
            mandating the communication of the technical format via payloadMimeType to ensure technical interoperability."

* ^url = "http://example.org/tide/StructureDefinition/tide-endpoint"
* ^status = #active
* ^experimental = true
* ^version = "0.1.0"

* status 1..1 MS
* connectionType 1..1 MS
* connectionType from http://hl7.org/fhir/ValueSet/endpoint-connection-type (extensible)

* payloadMimeType 1..* MS
* payloadMimeType ^short = "Technical format (MIME type)"

* payloadType 1..* MS
* payloadType from http://hl7.org/fhir/ValueSet/endpoint-payload-type (extensible)
* payloadType ^short = "Semantic payload type"

* address 1..1 MS