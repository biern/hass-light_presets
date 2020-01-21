Easily set default colors and brightness of your lights based on time of the day or any other factor.

# Overview

This component enables defining presets of default attributes to use when turning on a light.

It integrates with hass light service seamlessly, so that all existing automation, eg. switches, time triggers as well as lovelace UI components will use declared presets when turning on the light.

# Features

 - Whenever a light turns on it will use default attributes based on currently selected preset.
 - Whenever a light preset is updated, associated lights will be updated to match new state as well.
 - Default attributes are used only if event does not already include a specific light configuration.
 - Force turn lights on / off when entering new preset.
 - Define multiple presets containing mulitple lights.
 - Presets can be easily modified from other automations. Eg. changing light preset based on time of the day is straightforward.
 - Presets are defined in `input_select` so they can be easily changed using default hass UI.

# Setup

Clone / copy this repository to your home assistant config `custom_components` directory, eg:

``` shell
cd my-home-assistant-config-path
git clone https://github.com/biern/hass-light_presets.git custom_components/light_presets
```

# Configuration

## Example

``` yaml
light_presets:
  kitchen:
    preset: input_select.living_room_preset
    lights:
      - light.kitchen_ceiling
    presets:
      day:
        defaults:
          brightness: 255
          kelvin: 6500
      ambient:
        defaults:
          brightness: 50
          kelvin: 3100
      evening:
        defaults:
          brightness: 130
          kelvin: 3100

  bedroom:
    preset: input_select.bedroom_preset
    lights:
      - light.bedroom_a
      - light.bedroom_b
      - light.bedroom_c
    presets:
      day:
        defaults:
          brightness: 255
          kelvin: 6500
      evening:
        defaults:
          brightness: 100
          kelvin: 3100
      night:
        light.bedroom_a:
          brightness: 255
          rgb_color:
            - 255
            - 80
            - 0
        light.bedroom_b:
          state: "off"
        light.bedroom_c:
          state: "off"
```

# Integrating with automations

## Changing lights preset

Just update corresponding `input_select`. Eg:

``` yaml
- alias: Bedroom Profile Evening Set
  trigger:
  - at: '20:00'
    platform: time
  action:
  - service: input_select.select_option
    data:
      entity_id: input_select.bedroom_preset
      option: Evening
```

## Turning on the lights

Use built in `light.turn_on` service.
