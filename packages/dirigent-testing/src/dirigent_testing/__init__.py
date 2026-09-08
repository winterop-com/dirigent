"""Test doubles and pytest fixtures for writing and testing dirigent blocks."""

from dirigent_testing.conformance import assert_contribution_conforms, check_pack_examples
from dirigent_testing.doubles import FakeContext, FakeRuns, FakeSink, FakeStorage, RecordingLogger
from dirigent_testing.environment import CONFIGURING_PREFIXES, TEST_WIDTH, pin_terminal, scrub_configuration
from dirigent_testing.running import call_block

__all__ = [
    "CONFIGURING_PREFIXES",
    "TEST_WIDTH",
    "FakeContext",
    "FakeRuns",
    "FakeSink",
    "FakeStorage",
    "RecordingLogger",
    "assert_contribution_conforms",
    "call_block",
    "check_pack_examples",
    "pin_terminal",
    "scrub_configuration",
]
