Extension: TIDEPreviewEndpointExtension
Id: tide-preview-endpoint
Title: "TIDE Preview Endpoint"
Description: "Reference to an external Endpoint to show preview via a Middleware."

* ^url = "http://example.org/tide/StructureDefinition/tide-preview-endpoint" 

* ^context.type = #element
* ^context.expression = "Observation"

* value[x] only Reference(TIDEEndpoint)

