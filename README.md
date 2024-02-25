# Alarm Auto Arming

Automate the arming and disarming of the built-in Home Assistant alarm 
control panel, with additional support for manual override via remote
control buttons, and mobile push actionable notifications.


## Setup

Register this GitHub repo as a custom repo 
in your [HACS]( https://hacs.xyz) configuration. 

Configure in the Home Assistant config

```yaml
    alarm_panel: alarm_panel.testing
    auto_arm: True
    sleep_start: 09:00:00
    sleep_end: 22:00:00
    sunrise_cutoff: 06:30:00
    reset_button: binary_sensor.button_left
    away_button: binary_sensor.button_right
    disarm_button: binary_sensor.button_middle
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
