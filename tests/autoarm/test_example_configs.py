import os
import os.path


import pytest
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.autoarm.const import DOMAIN


EXAMPLES_ROOT = "examples"

examples = os.listdir(EXAMPLES_ROOT)


@pytest.mark.parametrize("config_name", examples)
async def test_examples(hass: HomeAssistant, config_name) -> None:

    with open(os.path.join(EXAMPLES_ROOT, config_name), "r") as f:
        config = yaml.safe_load(f)
    assert await async_setup_component(hass, DOMAIN, config)
    await hass.async_block_till_done()
