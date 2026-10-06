ValueSet: TIDEChannelValueSet
Id: tide-channel-value-set
Title: "TIDE Channel Value Set"
Description: "Value set of channel/electrode identity codes, used to bind the
            bodySite element of TIDEObservationChild. Includes all codes from the
            TIDEChannelCodeSystem. The set is extensible and not exhaustive."

* ^url = "http://example.org/tide/ValueSet/tide-channel-value-set"
* ^status = #active
* ^experimental = true
* ^version = "0.1.2"

* include codes from system http://example.org/tide/CodeSystem/tide-channel-code-system
