CodeSystem: TIDEConnectionTypeCodes
Id: tide-connection-type-codes
Title: "TIDE Connection Type Codes"
Description: "Supplemental Endpoint.connectionType codes for access methods not covered by
            the base FHIR CodeSystem http://terminology.hl7.org/CodeSystem/endpoint-connection-type . 
            This set is open to additions and not exhaustive."

* ^url = "http://example.org/tide/CodeSystem/tide-connection-type-codes"
* ^status = #active
* ^experimental = true
* ^caseSensitive = true
* ^content = #complete
* ^version = "0.1.0"

* #direct-https "Direct HTTPS file retrieval"
  "Direct retrieval of a static file via HTTPS GET, without a dedicated messaging, query,
  or REST protocol."

// open to additions
