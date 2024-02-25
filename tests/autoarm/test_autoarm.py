
import pytest
from homeassistant.core import HomeAssistant

from custom_components.autoarm.autoarming import AlarmArmer

TEST_PANEL = "alarm_control_panel.test_panel"


@pytest.fixture
async def autoarm(hass: HomeAssistant):
    uut = AlarmArmer(hass, TEST_PANEL, occupants=["person.tester_bob"])
    await uut.initialize()
    yield uut
    uut.shutdown()


async def test_not_occupied(hass: HomeAssistant, autoarm: AlarmArmer) -> None:
    hass.states.async_set("person.tester_bob", "away")
    assert autoarm.is_occupied() is False


async def test_occupied(hass: HomeAssistant, autoarm: AlarmArmer):
    hass.states.async_set("person.tester_bob", "home")
    assert autoarm.is_occupied() is True


async def test_day(hass: HomeAssistant, autoarm: AlarmArmer):
    hass.states.async_set("sun.sun", "above_horizon")
    assert autoarm.is_night() is False


async def test_reset_armed_state_sets_night(hass: HomeAssistant, autoarm: AlarmArmer):
    hass.states.async_set(TEST_PANEL, "disarmed")
    hass.states.async_set("sun.sun", "below_horizon")
    hass.states.async_set("person.tester_bob", "home")
    assert await autoarm.reset_armed_state() == "armed_night"


async def test_reset_armed_state_sets_home(hass: HomeAssistant, autoarm: AlarmArmer):
    hass.states.async_set("sun.sun", "above_horizon")
    hass.states.async_set("person.tester_bob", "home")
    hass.states.async_set(TEST_PANEL, "disarmed")
    assert await autoarm.reset_armed_state() == "armed_home"

async def test_reset_armed_state_overrides_unknown(hass: HomeAssistant, autoarm: AlarmArmer):
    hass.states.async_set("sun.sun", "above_horizon")
    hass.states.async_set("person.tester_bob", "home")
    hass.states.async_set(TEST_PANEL, "whatever")
    assert await autoarm.reset_armed_state(force_arm=False) == "disarmed"

async def test_unforced_reset_leaves_disarmed(hass: HomeAssistant, autoarm: AlarmArmer):
    hass.states.async_set("sun.sun", "above_horizon")
    hass.states.async_set("person.tester_bob", "home")
    hass.states.async_set(TEST_PANEL, "disarmed")
    assert await autoarm.reset_armed_state(force_arm=False) == "disarmed"


async def test_forced_reset_sets_armed_home_from_disarmed(hass: HomeAssistant, autoarm: AlarmArmer):
    hass.states.async_set("sun.sun", "above_horizon")
    hass.states.async_set("person.tester_bob", "home")
    hass.states.async_set(TEST_PANEL, "disarmed")
    assert await autoarm.reset_armed_state(force_arm=True) == "armed_home"
