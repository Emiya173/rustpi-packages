import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('retry', Path(__file__).resolve().parents[1] / 'ci/verify-build-run.py')
retry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retry)


class PublicationRetryTests(unittest.TestCase):
    def setUp(self):
        self.run = {'head_repository': {'full_name': retry.REPO}, 'head_branch': 'main',
                    'path': '.github/workflows/repository.yml', 'event': 'push',
                    'status': 'completed', 'head_sha': 'a' * 40, 'conclusion': 'failure'}
        self.jobs = [{'name': 'plan', 'conclusion': 'success'},
                     {'name': 'build (kernel)', 'conclusion': 'success'},
                     {'name': 'publish', 'conclusion': 'failure'}]

    def test_publication_failure_can_retry_validated_build(self):
        self.assertEqual(retry.validate(self.run, self.jobs), 'a' * 40)

    def test_failed_build_cannot_be_published(self):
        self.jobs[1]['conclusion'] = 'failure'
        with self.assertRaises(AssertionError):
            retry.validate(self.run, self.jobs)

    def test_untrusted_or_incomplete_runs_are_rejected(self):
        for field, value in [('head_branch', 'feature'), ('event', 'pull_request'),
                             ('status', 'in_progress'), ('path', 'another-workflow.yml')]:
            with self.subTest(field=field), self.assertRaises(AssertionError):
                retry.validate(self.run | {field: value}, self.jobs)
        with self.assertRaises(AssertionError):
            retry.validate(self.run | {'head_repository': {'full_name': 'someone/fork'}}, self.jobs)

    def test_no_build_artifacts_is_not_a_release(self):
        with self.assertRaises(AssertionError):
            retry.validate(self.run, [self.jobs[0]])


if __name__ == '__main__':
    unittest.main()
