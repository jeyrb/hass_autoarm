import asyncio
import datetime
import logging
import time
from functools import partial

import homeassistant.util.dt as dt_util
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_sunrise,
    async_track_sunset,
    async_track_utc_time_change,
)
from homeassistant.helpers.typing import ConfigType, EventType

from .const import (
    CONF_ACTIONS,
    CONF_ALARM_PANEL,
    CONF_ARM_AWAY_DELAY,
    CONF_AUTO_ARM,
    CONF_BUTTON_ENTITY_AWAY,
    CONF_BUTTON_ENTITY_DISARM,
    CONF_BUTTON_ENTITY_RESET,
    CONF_NOTIFY,
    CONF_OCCUPANTS,
    CONF_SLEEP_END,
    CONF_SLEEP_START,
    CONF_SUNRISE_CUTOFF,
    DOMAIN,
    CONFIG_SCHEMA
)

_LOGGER = logging.getLogger(__name__)


def load_time(v):
    if isinstance(v, datetime.time):
        return v
    elif v is None:
        return None
    else:
        return datetime.datetime.strptime(v, "%H:%M:%S").time()


total_secs = lambda t: (t.hour * 3600) + (t.minute * 60) + t.second 

OVERRIDE_STATES = ("armed_away", "armed_vacation")
ZOMBIE_STATES = ("unknown", "unavailable")
NS_MOBILE_ACTIONS = "mobile_actions"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    _ = CONFIG_SCHEMA
    config=config.get(DOMAIN,{})
    hass.states.async_set(
        "%s.configured" % DOMAIN,
        True,
        {
            CONF_ALARM_PANEL: config.get(CONF_ALARM_PANEL),
            CONF_AUTO_ARM: config.get(CONF_AUTO_ARM, True),
            CONF_SLEEP_START: config.get(CONF_SLEEP_START),
            CONF_SLEEP_END: config.get(CONF_SLEEP_END),
            CONF_SUNRISE_CUTOFF: config.get(CONF_SUNRISE_CUTOFF),
            CONF_ARM_AWAY_DELAY: config.get(CONF_ARM_AWAY_DELAY, ()),
            CONF_BUTTON_ENTITY_RESET: config.get(CONF_BUTTON_ENTITY_RESET),
            CONF_BUTTON_ENTITY_AWAY: config.get(CONF_BUTTON_ENTITY_AWAY),
            CONF_BUTTON_ENTITY_DISARM: config.get(CONF_BUTTON_ENTITY_DISARM),
            CONF_OCCUPANTS: config.get(CONF_OCCUPANTS, []),
            CONF_ACTIONS: config.get(CONF_ACTIONS, []),
            CONF_NOTIFY: config.get(CONF_NOTIFY, {}),
        },
    )

    armer = AlarmArmer(
        hass,
        alarm_panel=config[CONF_ALARM_PANEL],
        auto_disarm=config[CONF_AUTO_ARM],
        sleep_start=config.get(CONF_SLEEP_START),
        sleep_end=config.get(CONF_SLEEP_END),
        sunrise_cutoff=config.get(CONF_SUNRISE_CUTOFF),
        arm_away_delay=config[CONF_ARM_AWAY_DELAY],
        reset_button=config.get(CONF_BUTTON_ENTITY_RESET),
        away_button=config.get(CONF_BUTTON_ENTITY_AWAY),
        disarm_button=config.get(CONF_BUTTON_ENTITY_DISARM),
        occupants=config[CONF_OCCUPANTS],
        actions=config[CONF_ACTIONS],
        notify=config[CONF_NOTIFY],
    )
    await armer.initialize()
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, armer.async_shutdown)

    return True

class AlarmArmer:

    def __init__(
        self,
        hass,
        alarm_panel,
        auto_disarm=True,
        sleep_start=None,
        sleep_end=None,
        sunrise_cutoff=None,
        arm_away_delay=None,
        reset_button=None,
        away_button=None,
        disarm_button=None,
        occupants=None,
        actions=None,
        notify=None,
    ):
        self.hass = hass
        self.alarm_panel = alarm_panel
        self.auto_disarm = auto_disarm
        self.sleep_start = load_time(sleep_start)
        self.sleep_end = load_time(sleep_end)
        self.sunrise_cutoff = sunrise_cutoff
        self.arm_away_delay = arm_away_delay if arm_away_delay else 0
        self.reset_button = reset_button
        self.away_button = away_button
        self.disarm_button = disarm_button
        self.occupants = occupants or []
        self.actions = actions or []
        self.notify_profiles = notify or {}
        self.unsubscribes = []

    async def initialize(self):
        _LOGGER.debug("AUTOARM Initializing ...")
        _LOGGER.info("AUTOARM auto_disarm=%s, arm_delay=%s", self.auto_disarm, self.arm_away_delay)
        self.last_request = None

        self.arming_in_progress = asyncio.Event()
        self.initialize_alarm_panel()
        self.initialize_diurnal()
        self.initialize_occupancy()
        self.initialize_bedtime()
        self.initialize_buttons()
        self.reset_armed_state(force_arm=False)
        self.initialize_integration()
        _LOGGER.debug("AUTOARM Initialized")

    def initialize_integration(self):
        self.unsubscribes.append(self.hass.bus.async_listen("mobile_app_notification_action", self.on_mobile_action))
        self.unsubscribes.append(self.hass.bus.async_listen("homeassistant_start", self.ha_start))

    def ha_start(self):
        _LOGGER.debug("AUTOARM Home assistant restarted")
        self.reset_armed_state(force_arm=False)

    async def async_shutdown(self, event: Event) -> None:
        _LOGGER.info("AUTOARM shutting down")
        self.shutdown()

    def shutdown(self):
        for unsub in self.unsubscribes:
            unsub()
        _LOGGER.info("AUTOARM shut down")

    def initialize_alarm_panel(self):
        """Set up automation for Home Assistant alarm panel
        See https://www.home-assistant.io/integrations/alarm_control_panel/
        """
        self.unsubscribes.append(async_track_state_change_event(self.hass, [self.alarm_panel], self.on_panel_change))
        _LOGGER.debug("AUTOARM Auto-arming %s" % self.alarm_panel)

    def initialize_diurnal(self):
        self.unsubscribes.append(async_track_sunrise(self.hass, self.on_sunrise, None))
        self.unsubscribes.append(async_track_sunset(self.hass, self.on_sunset, None))

    def initialize_occupancy(self):
        """Configure occupants, and listen for changes in their state"""
        _LOGGER.debug("AUTOARM Occupancy determined by %s" % ",".join(self.occupants))
        self.unsubscribes.append(async_track_state_change_event(self.hass, self.occupants, self.on_occupancy_change))
        _LOGGER.debug(
            "AUTOARM Occupied: %s, Unoccupied: %s, Night: %s" % (self.is_occupied(), self.is_unoccupied(), self.is_night())
        )

    def initialize_bedtime(self):
        """Configure usual bed time (optional)"""
        if self.sleep_start:
            self.unsubscribes.append(
                async_track_utc_time_change(
                    self.hass, self.on_sleep_start, self.sleep_start.hour, self.sleep_start.minute, self.sleep_start.second
                )
            )
        if self.sleep_end:
            self.unsubscribes.append(
                async_track_utc_time_change(
                    self.hass, self.on_sleep_end, self.sleep_end.hour, self.sleep_end.minute, self.sleep_end.second
                )
            )
        _LOGGER.debug("AUTOARM Bed time from %s->%s" % (self.sleep_start, self.sleep_end))

    def initialize_buttons(self):
        """Initialize (optional) physical alarm state control buttons"""
        self.button_device = {}

        def setup_button(state, button_entity, callback):
            self.button_device[state] = button_entity
            if self.button_device[state]:
                self.unsubscribes.append(async_track_state_change_event(self.hass, [button_entity], callback))

                _LOGGER.debug("AUTOARM Configured %s button for %s" % (state, self.button_device[state]))

        setup_button("reset", self.reset_button, self.on_reset_button)
        setup_button("away", self.away_button, self.on_away_button)
        setup_button("disarm", self.disarm_button, self.on_disarm_button)

    def safe_state(self, state):
        try:
            return state.state
        except Exception as e:
            _LOGGER.debug("AUTOARM Failed to load state %s: %s", state, e)
            return None

    def is_occupied(self):
        return any(self.safe_state(self.hass.states.get(p)) == "home" for p in self.occupants)

    def is_unoccupied(self):
        return all(self.safe_state(self.hass.states.get(p)) != "home" for p in self.occupants)

    def is_night(self):
        return self.safe_state(self.hass.states.get("sun.sun")) == "below_horizon"

    def armed_state(self):
        return self.safe_state(self.hass.states.get(self.alarm_panel))

    @callback
    async def on_panel_change(self, event: EventType):
        entity_id, old, new = self._extract_event(event)
        if self.arming_in_progress.is_set():
            _LOGGER.debug(
                "AUTOARM Panel Change Ignored: %s,%s: %s-->%s",
                entity_id,
                event.event_type,
                old,
                new,
            )
            return
        _LOGGER.debug("AUTOARM Panel Change: %s,%s: %s-->%s", entity_id, event.event_type, old, new)

        if new in ZOMBIE_STATES:
            _LOGGER.debug("AUTOARM Dezombifying %s ...", new)
            await self.reset_armed_state()
        else:
            message = "Home Assistant alert level now set from %s to %s" % (old, new)
            self.notify_flex(message, title="Alarm now %s" % new, profile="quiet")

    def _extract_event(self, event):
        entity_id = old = new = None
        if event and event.data:
            entity_id = event.data.get("entity_id")
            old_obj = event.data.get("old_state")
            if old_obj:
                old = old_obj.state
            new_obj = event.data.get("new_state")
            if new_obj:
                new = new_obj.state
        return entity_id, old, new

    @callback
    async def on_occupancy_change(self, event: EventType[EventStateChangedData]):
        entity_id, old, new = self._extract_event(event)
        existing_state = self.armed_state()
        _LOGGER.debug("AUTOARM Occupancy Change: %s, %s, %s, %s" % (entity_id, old, new, event))
        if self.is_unoccupied() and existing_state not in OVERRIDE_STATES:
            await self.arm("armed_away")
        elif self.is_occupied() and existing_state == "armed_away":
            await self.reset_armed_state()

    def is_awake(self):
        if self.sleep_start and self.sleep_end:
            now = datetime.datetime.now()
            if now.time() >= self.sleep_end and now.time() <= self.sleep_start:
                return True
        else:
            return not self.is_night()

    async def reset_armed_state(self, force_arm=True, hint_arming=None):
        existing_state = self.armed_state()
        if existing_state != "disarmed" or force_arm:
            if existing_state not in OVERRIDE_STATES:
                if self.is_occupied():
                    if self.auto_disarm and self.is_awake() and not force_arm:
                        _LOGGER.debug("AUTOARM Disarming for occupied during waking hours")
                        return await self.arm("disarmed")
                    elif not self.is_awake():
                        _LOGGER.debug("AUTOARM Arming for occupied out of waking hours")
                        return await self.arm("armed_night")
                    elif hint_arming:
                        _LOGGER.debug(f"AUTOARM Using hinted arming state {hint_arming}")
                        return await self.arm(hint_arming)
                    else:
                        _LOGGER.debug("AUTOARM Defaulting to armed home")
                        return await self.arm("armed_home")
                if hint_arming:
                    _LOGGER.debug(f"AUTOARM Using hinted arming state {hint_arming}")
                    return await self.arm(hint_arming)
                else:
                    _LOGGER.debug("AUTOARM Defaulting to armed away")
                    return await self.arm("armed_away")
        return existing_state

    async def delayed_arm(self, arming_state, reset, requested_at):
        _LOGGER.debug("Delayed_arm %s, reset: %s", arming_state, reset)

        if self.last_request is not None and requested_at is not None:
            if self.last_request > requested_at:
                _LOGGER.debug("AUTOARM Cancelling delayed request for %s since subsequent manual action" % arming_state)
                return
            else:
                _LOGGER.debug("AUTOARM Delayed execution of %s requested at %s" % (arming_state, requested_at))
        if reset:
            await self.reset_armed_state(force_arm=True, hint_arming=arming_state)
        else:
            await self.arm(arming_state=arming_state)

    async def arm(self, arming_state=None):
        try:
            self.arming_in_progress.set()
            existing_state = self.armed_state()
            if arming_state != existing_state:
                self.hass.states.async_set(self.alarm_panel, arming_state)
                _LOGGER.debug("AUTOARM Setting %s from %s to %s" % (self.alarm_panel, existing_state, arming_state))
                return arming_state
            else:
                _LOGGER.debug("Skipping arm, as %s already %s" % (self.alarm_panel, arming_state))
                return existing_state
        finally:
            self.arming_in_progress.clear()

    def notify_flex(self, message, profile="normal", title=None):
        notify_service = None
        try:
            # separately merge base dict and data sub-dict as cheap and nasty semi-deep-merge
            selected_profile = self.notify_profiles.get(profile)
            base_profile = self.notify_profiles.get("common", {})
            base_profile_data = base_profile.get("data", {})
            selected_profile_data = selected_profile.get("data", {})
            merged_profile = dict(base_profile)
            merged_profile.update(selected_profile)
            merged_profile_data = dict(base_profile_data)
            merged_profile_data.update(selected_profile_data)
            merged_profile["data"] = merged_profile_data
            notify_service = merged_profile["service"].replace(".", "/")

            title = title or "Alarm Auto Arming"
            if merged_profile:
                self.call_service(
                    notify_service,
                    message=message,
                    title=title,
                    data=merged_profile.get("data", {}),
                )
        except Exception as e:
            _LOGGER.error("AUTOARM %s failed %s" % (notify_service, e))

    @callback
    async def on_sleep_start(self, kwargs):
        _LOGGER.debug("AUTOARM Sleep Period Start: %s" % kwargs)
        await self.reset_armed_state(force_arm=True)

    @callback
    async def on_sleep_end(self, kwargs):
        _LOGGER.debug("AUTOARM Sleep Period End: %s" % kwargs)
        await self.reset_armed_state(force_arm=False)

    @callback
    async def on_reset_button(self, event: EventType[EventStateChangedData]):
        _LOGGER.debug("AUTOARM Reset Button: %s", event)
        self.last_request = time.time()
        await self.reset_armed_state(force_arm=True)

    @callback
    async def on_mobile_action(self, event):
        _LOGGER.debug("AUTOARM Mobile Action: %s", event)
        self.last_request = time.time()
        match event.data.get("action"):
            case "ALARM_PANEL_DISARM":
                await self.arm("disarmed")
            case "ALARM_PANEL_RESET":
                await self.reset_armed_state(force_arm=True)
            case "ALARM_PANEL_AWAY":
                await self.arm("armed_away")
            case _:
                self.log("AUTOARM Ignoring mobile action: %s", event.data)

    @callback
    async def on_disarm_button(self, event: EventType[EventStateChangedData]):
        _LOGGER.debug("AUTOARM Disarm Button: %s", event)
        self.last_request = time.time()
        await self.arm("disarmed")

    @callback
    async def on_vacation_button(self, event: EventType[EventStateChangedData]):
        _LOGGER.debug("AUTOARM Vacation Button: %s", event)
        await self.arm("armed_vacation")

    @callback
    async def on_away_button(self, event: EventType[EventStateChangedData]):
        _LOGGER.debug("AUTOARM Away Button: %s", event)
        self.last_request = time.time()
        if self.arm_away_delay:
            self.unsubscribes.append(
                async_track_point_in_time(
                    self.hass,
                    partial(self.delayed_arm, "armed_away", False, dt_util.utc_from_timestamp(time.time())),
                    dt_util.utc_from_timestamp(time.time() + self.arm_away_delay),
                )
            )
            self.notify_flex(
                "Alarm will be armed for away in %s seconds" % self.arm_away_delay,
                title="Arm for away process starting",
            )
        else:
            await self.arm("armed_away")

    @callback
    async def on_sunrise(self):
        _LOGGER.debug("AUTOARM Sunrise")
        if not self.sunrise_cutoff or datetime.datetime.now().time() >= self.sunrise_cutoff:
            self.reset_armed_state(force_arm=False)
        elif self.sunrise_cutoff < self.sleep_end:
            sunrise_delay = total_secs(self.sleep_end) - total_secs(self.sunrise_cutoff)
            _LOGGER.debug("AUTOARM Rescheduling delayed sunrise action in %s seconds" % sunrise_delay)
            self.unsubscribes.append(
                async_track_point_in_time(
                    self.hass,
                    partial(self.delayed_arm, "armed_home", True, dt_util.utc_from_timestamp(time.time())),
                    dt_util.utc_from_timestamp(time.time() + sunrise_delay),
                )
            )

    @callback
    async def on_sunset(self):
        _LOGGER.debug("AUTOARM Sunset")
        await self.reset_armed_state(force_arm=True)
