import OAI.RingTheory.DirectFiniteness.Main

#eval IO.println "AUDIT_TARGET_BEGIN|OAI.KaplanskyCounterexample.main_theorem"
set_option pp.all true in
#check OAI.KaplanskyCounterexample.main_theorem
#print axioms OAI.KaplanskyCounterexample.main_theorem
#eval IO.println "AUDIT_TARGET_END|OAI.KaplanskyCounterexample.main_theorem"

#eval IO.println "AUDIT_TARGET_BEGIN|OAI.KaplanskyCounterexample.Prescription.Output.prescribed_main"
set_option pp.all true in
#check OAI.KaplanskyCounterexample.Prescription.Output.prescribed_main
#print axioms OAI.KaplanskyCounterexample.Prescription.Output.prescribed_main
#eval IO.println "AUDIT_TARGET_END|OAI.KaplanskyCounterexample.Prescription.Output.prescribed_main"

#eval IO.println "AUDIT_TARGET_BEGIN|OAI.KaplanskyCounterexample.Prescription.Output.prescribed_products"
set_option pp.all true in
#check OAI.KaplanskyCounterexample.Prescription.Output.prescribed_products
#print axioms OAI.KaplanskyCounterexample.Prescription.Output.prescribed_products
#eval IO.println "AUDIT_TARGET_END|OAI.KaplanskyCounterexample.Prescription.Output.prescribed_products"

#eval IO.println "AUDIT_TARGET_BEGIN|OAI.KaplanskyCounterexample.Prescription.finite_search_terminates"
set_option pp.all true in
#check OAI.KaplanskyCounterexample.Prescription.finite_search_terminates
#print axioms OAI.KaplanskyCounterexample.Prescription.finite_search_terminates
#eval IO.println "AUDIT_TARGET_END|OAI.KaplanskyCounterexample.Prescription.finite_search_terminates"

#eval IO.println "AUDIT_TARGET_BEGIN|OAI.mersenne_21701_prime"
set_option pp.all true in
#check OAI.mersenne_21701_prime
#print axioms OAI.mersenne_21701_prime
#eval IO.println "AUDIT_TARGET_END|OAI.mersenne_21701_prime"

#eval IO.println "AUDIT_TARGET_BEGIN|OAI.KaplanskyCounterexample.Prescription.Output.X_global"
set_option pp.all true in
#check OAI.KaplanskyCounterexample.Prescription.Output.X_global
#print axioms OAI.KaplanskyCounterexample.Prescription.Output.X_global
#eval IO.println "AUDIT_TARGET_END|OAI.KaplanskyCounterexample.Prescription.Output.X_global"

#eval IO.println "AUDIT_TARGET_BEGIN|OAI.KaplanskyCounterexample.Prescription.Output.X_local"
set_option pp.all true in
#check OAI.KaplanskyCounterexample.Prescription.Output.X_local
#print axioms OAI.KaplanskyCounterexample.Prescription.Output.X_local
#eval IO.println "AUDIT_TARGET_END|OAI.KaplanskyCounterexample.Prescription.Output.X_local"

#eval IO.println "AUDIT_TARGET_BEGIN|OAI.KaplanskyCounterexample.Prescription.Output.forms_distinct"
set_option pp.all true in
#check OAI.KaplanskyCounterexample.Prescription.Output.forms_distinct
#print axioms OAI.KaplanskyCounterexample.Prescription.Output.forms_distinct
#eval IO.println "AUDIT_TARGET_END|OAI.KaplanskyCounterexample.Prescription.Output.forms_distinct"

#eval IO.println "AUDIT_WITNESS_BEGIN|source-parameters"
set_option pp.all true in
#check OAI.KaplanskyCounterexample.FiniteGeometry.sourceQ
set_option pp.all true in
#check OAI.KaplanskyCounterexample.FiniteGeometry.sourcePrime
set_option pp.all true in
#check OAI.KaplanskyCounterexample.Prescription.selectedH
set_option pp.all true in
#check OAI.KaplanskyCounterexample.Prescription.selectedPair
set_option pp.all true in
#check OAI.KaplanskyCounterexample.Prescription.Output.Coeff
set_option pp.all true in
#check OAI.KaplanskyCounterexample.Prescription.Output.G
set_option pp.all true in
#check OAI.KaplanskyCounterexample.Prescription.Output.a
set_option pp.all true in
#check OAI.KaplanskyCounterexample.Prescription.Output.b
#eval IO.println "AUDIT_WITNESS_END|source-parameters"
