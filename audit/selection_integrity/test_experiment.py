#!/usr/bin/env python3
import unittest
from experiment import (
    catalogue_audit, exact_hypergeom_tail, git_blob_sha,
    mcnemar, parse_catalog, simulate, calibration,
)


class SelectionAuditTests(unittest.TestCase):
    def test_minimal_parser_and_families(self):
        a, b, c = parse_catalog(
            '**001. First.**\n&emsp;[A](preprints/a.pdf)\n'
            '**003. Third.**\n&emsp;[B](preprints/b.pdf)\n&emsp;[C](preprints/c.pdf)\n',
            '| 003 | [trace](reasoning_traces/a.pdf) |')
        self.assertEqual((a, b, c), ([1, 3], [1, 2], [3]))

    def test_git_blob_sha(self):
        self.assertEqual(git_blob_sha(b'hello\n'), 'ce013625030ba8dba906f756967f9e9ca394464a')

    def test_exact_tail(self):
        self.assertEqual(exact_hypergeom_tail(10, 3, 2, 2), 3 / 45)
        self.assertEqual(exact_hypergeom_tail(10, 3, 2, 0), 1.0)

    def test_mcnemar_direction_and_exact(self):
        result = mcnemar([True]*4, [False]*4)
        self.assertEqual(result['paired_variant_minus_control_acceptance'], -1)
        self.assertEqual(result['exact_mcnemar_two_sided_p'], 0.125)
        self.assertEqual(mcnemar([True], [True])['exact_mcnemar_two_sided_p'], 1)

    def test_simulation_deterministic_and_detection(self):
        a, b = simulate(n=1200), simulate(n=1200)
        self.assertEqual(a, b)
        self.assertGreater(a['no_injected_effect_G0_F0']['exact_mcnemar_two_sided_p'], 0.01)
        self.assertLess(a['filter_only_G0_F1']['exact_mcnemar_two_sided_p'], 0.01)
        self.assertLess(a['generator_only_G1_F0']['exact_mcnemar_two_sided_p'], 0.01)
        self.assertEqual(a['filter_attribution_control']['max_absolute_generator_score_change_between_filter_arms'], 0)
        self.assertLess(a['filter_only_G0_F1']['paired_variant_minus_control_acceptance'], 0)

    def test_simulated_calibration(self):
        result = calibration(seeds=24, n_per_seed=600)
        self.assertLessEqual(result['null_false_alerts'], 3)
        self.assertGreaterEqual(result['injected_filter_detections'], 22)

    def test_public_catalogue_no_internal_inference(self):
        out = catalogue_audit([1,2,3,4,5,6], [1,2,1,3,2,1], [2,4], permutations=64)
        self.assertFalse(out['internal_selection_process_identifiable'])
        self.assertEqual(out['manuscripts'], 10)
        self.assertEqual(out['missing_family_identifiers'], [])
        self.assertEqual(out['digit_search']['permutations'], 64)

    def test_invalid_sample_rejected(self):
        with self.assertRaises(ValueError):
            catalogue_audit([1,2], [1,2], [3], permutations=10)


if __name__ == '__main__':
    unittest.main()
