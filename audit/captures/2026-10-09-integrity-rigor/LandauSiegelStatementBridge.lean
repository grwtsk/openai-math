import OAI.NumberTheory.SiegelZeros.Conclusions.Theorem
import OAI.NumberTheory.SiegelZeros.Characters.DirichletRealZeroBoundProof

namespace OAI
namespace SiegelZeros
namespace WeightedTorusJets

/-- The hypothesis-curried form used by the geometric/Bezout route. -/
def CurriedUniformRealZeroGap : Prop :=
  ∃ c : ℝ, 0 < c ∧
    ∀ (q : ℕ) [NeZero q], 3 ≤ q →
    ∀ χ : DirichletCharacter ℂ q,
      χ.IsPrimitive → χ ≠ 1 → (∀ a : ZMod q, (χ a).im = 0) →
      ∀ β : ℝ, 0 < β → β < 1 → χ.LFunction (β : ℂ) = 0 →
        c ≤ (1 - β) * Real.log (q : ℝ)

/-- The bundled-hypothesis form used by the analytic/contrary-sequence route. -/
def BundledUniformRealZeroGap : Prop :=
  ∃ c : ℝ, 0 < c ∧
    ∀ (q : ℕ) [NeZero q], 3 ≤ q →
    ∀ χ : DirichletCharacter ℂ q,
      χ.IsPrimitive → χ ≠ 1 → (∀ a : ZMod q, (χ a).im = 0) →
      ∀ β : ℝ,
        (0 < β ∧ β < 1 ∧ χ.LFunction (β : ℂ) = 0) →
          c ≤ (1 - β) * Real.log (q : ℝ)

/-- The two published Lean statement shapes are logically equivalent, preserving the same witness `c`. -/
theorem curriedUniformRealZeroGap_iff_bundledUniformRealZeroGap :
    CurriedUniformRealZeroGap ↔ BundledUniformRealZeroGap := by
  constructor
  · rintro ⟨c, hc, h⟩
    refine ⟨c, hc, ?_⟩
    intro q _ hq χ hprimitive hnonprincipal hreal β hβ
    exact h q hq χ hprimitive hnonprincipal hreal β hβ.1 hβ.2.1 hβ.2.2
  · rintro ⟨c, hc, h⟩
    refine ⟨c, hc, ?_⟩
    intro q _ hq χ hprimitive hnonprincipal hreal β hβ0 hβ1 hzero
    exact h q hq χ hprimitive hnonprincipal hreal β ⟨hβ0, hβ1, hzero⟩

/-- The geometric theorem inhabits the explicit curried contract. -/
theorem curriedUniformRealZeroGap_of_geometric : CurriedUniformRealZeroGap := by
  exact exists_absolute_real_zero_gap

/-- The analytic theorem inhabits the explicit bundled contract. -/
theorem bundledUniformRealZeroGap_of_analytic : BundledUniformRealZeroGap := by
  exact dirichletRealZeroBound_proof

/-- Transport the geometric result to the analytic statement shape. -/
theorem bundledUniformRealZeroGap_of_geometric : BundledUniformRealZeroGap :=
  curriedUniformRealZeroGap_iff_bundledUniformRealZeroGap.mp
    curriedUniformRealZeroGap_of_geometric

/-- Transport the analytic result to the geometric statement shape. -/
theorem curriedUniformRealZeroGap_of_analytic : CurriedUniformRealZeroGap :=
  curriedUniformRealZeroGap_iff_bundledUniformRealZeroGap.mpr
    bundledUniformRealZeroGap_of_analytic

#print axioms curriedUniformRealZeroGap_iff_bundledUniformRealZeroGap
#print axioms bundledUniformRealZeroGap_of_geometric
#print axioms curriedUniformRealZeroGap_of_analytic

end WeightedTorusJets
end SiegelZeros
end OAI
