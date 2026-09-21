"""Every refusal a test double makes, catalogued under the ``testing`` prefix."""

from dirigent_common import Catalogue

TESTING = Catalogue("testing")

TEST_REFUSAL = TESTING.define("refusal", "{detail}")
