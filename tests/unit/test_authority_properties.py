"""Generated grant/price histories use independently modeled authorization and costs."""

import unittest

from tests import generated_authority
from tests.generated_inputs import settings


class AuthorityPriceProperties(unittest.TestCase):
    def test_grants_prices_replays_and_historical_cost_follow_the_independent_model(self):
        seed, count = settings(48)
        generated_authority.run(seed, count)
