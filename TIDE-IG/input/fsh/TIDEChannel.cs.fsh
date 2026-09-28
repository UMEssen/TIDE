CodeSystem: TIDEChannelCodeSystem
Id: tide-channel-code-system
Title: "TIDE Channel Code System"
Description: "Codes for channel/electrode identity used in the bodySite element of
            TIDEObservationChild resources in the hierarchical parent/child model.
            Covers the standard International 10-20 System EEG electrode positions
            plus extended nasopharyngeal positions and a fallback code for
            non-standard channel labels. This set is open to additions and not
            exhaustive."

* ^url = "http://example.org/tide/CodeSystem/tide-channel-code-system"
* ^status = #active
* ^experimental = true
* ^caseSensitive = true
* ^content = #complete
* ^version = "0.1.0"

// Standard International 10-20 System positions (21)
// Legacy labels T3/T4/T5/T6 correspond to modern equivalents T7/T8/P7/P8.
* #Fp1 "Fp1" "International 10-20 System electrode position Fp1."
* #Fp2 "Fp2" "International 10-20 System electrode position Fp2."
* #F7 "F7" "International 10-20 System electrode position F7."
* #F3 "F3" "International 10-20 System electrode position F3."
* #Fz "Fz" "International 10-20 System electrode position Fz."
* #F4 "F4" "International 10-20 System electrode position F4."
* #F8 "F8" "International 10-20 System electrode position F8."
* #T3 "T3" "International 10-20 System electrode position T3 (modern equivalent: T7)."
* #C3 "C3" "International 10-20 System electrode position C3."
* #Cz "Cz" "International 10-20 System electrode position Cz."
* #C4 "C4" "International 10-20 System electrode position C4."
* #T4 "T4" "International 10-20 System electrode position T4 (modern equivalent: T8)."
* #T5 "T5" "International 10-20 System electrode position T5 (modern equivalent: P7)."
* #P3 "P3" "International 10-20 System electrode position P3."
* #Pz "Pz" "International 10-20 System electrode position Pz."
* #P4 "P4" "International 10-20 System electrode position P4."
* #T6 "T6" "International 10-20 System electrode position T6 (modern equivalent: P8)."
* #O1 "O1" "International 10-20 System electrode position O1."
* #O2 "O2" "International 10-20 System electrode position O2."
* #A1 "A1" "International 10-20 System reference electrode position A1 (left ear/mastoid)."
* #A2 "A2" "International 10-20 System reference electrode position A2 (right ear/mastoid)."

// Extended nasopharyngeal positions (2)
* #Pg1 "Pg1" "Left nasopharyngeal electrode position from the extended 10-20 nomenclature, used in some clinical epilepsy/sleep montages."
* #Pg2 "Pg2" "Right nasopharyngeal electrode position from the extended 10-20 nomenclature, used in some clinical epilepsy/sleep montages."

// Fallback (1)
* #non-standard-channel "Non-standard or unlabeled channel" "Used when a channel label does not map to a recognized electrode position (e.g., generic or anonymized labels such as EEG001); the original label is preserved in bodySite.text."
