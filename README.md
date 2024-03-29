[![Rhizomatics Open Source](https://avatars.githubusercontent.com/u/162821163?s=96&v=4)](https://github.com/rhizomatics) Rhizomatics Open Source



# Alarm Auto Arming

Automate the arming and disarming of the built-in Home Assistant alarm 
control panel, with additional support for manual override via remote
control buttons, and mobile push actionable notifications.


## Setup

Register this GitHub repo as a custom repo 
in your [HACS]( https://hacs.xyz) configuration. 

Notifications will work with any HomeAssistant notification implementation
but works best with [Supernotifier](https://jeyrb.github.io/hass_supernotify/) for multi-channel notifications with mobile actions.

## Diurnal settings

Arming can happen strictly by sunset and sunrise. 
Alternatively, a defined `sleep_start` and `sleep_end` can be specified, so there's more
predictability, especially for high latitudes where sunrise varies wildly through the year.

Similarly, there's a `sunrise_cutoff` option to prevent alarm being armed at 
4am if you live far North, like Norway or Scotland.

## Throttling

To guard against loops, or other reasons why arming might be triggered too often,
rate limiting is applied around the arm call, limited to a set number of calls within
the past so many seconds. 

## Example Configuration
Configure in the Home Assistant config

```yaml
    alarm_panel: alarm_panel.testing
    auto_arm: True
    sleep_start: "09:00:00"
    sleep_end: "22:00:00"
    sunrise_cutoff: "06:30:00"
    arm_away_delay: 180
    reset_button: binary_sensor.button_left
    away_button: binary_sensor.button_right
    disarm_button: binary_sensor.button_middle
    throttle_seconds: 30
    throttle_calls: 6
    occupants: 
        - person.house_owner
        - person.tenant
    notify:
        common:
            service: notify.supernotifier
            data: 
                actions: 
                    action_groups: alarm_panel
                    action_category: alarm_panel
        quiet: 
            data: 
                priority: low
        normal:
            data:
                priority: medium
    actions:
        - action: ALARM_PANEL_DISARM
          title: Disarm Alarm Panel
          icon: sfsymbols:bell.slash
        - action: ALARM_PANEL_RESET
          title: Reset Alarm Panel
          icon: sfsymbols:bell
        - action: ALARM_PANEL_AWAY
          title: Arm Alarm Panel for Going Away
          icon: sfsymbols:airplane

```
