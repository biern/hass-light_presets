import asyncio
from functools import partial
import logging
import types

import voluptuous as vol

from homeassistant.const import (
    EVENT_STATE_CHANGED,
    STATE_ON,
    EVENT_CALL_SERVICE,
    EVENT_SERVICE_REGISTERED,
)
from homeassistant.components.light import (
    LIGHT_TURN_ON_SCHEMA,
    preprocess_turn_on_alternatives,
)
from homeassistant.core import callback, ServiceCall
import homeassistant.helpers.config_validation as cv

DOMAIN = "light_presets"

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: cv.schema_with_slug_keys(
            vol.All(
                {
                    "preset": cv.string,
                    "presets": cv.schema_with_slug_keys(dict),
                    "lights": vol.All(cv.ensure_list, [cv.string]),
                }
            )
        ),
    },
    required=True,
    extra=vol.ALLOW_EXTRA,
)

LIGHT_ATTRIBUTES = (
    "brightness",
    "kelvin",
    "rgb_color",
    "white_value",
    "color_temp",
    "color_name",
    "brightness_pct",
    "effect",
    "hs_color",
)

COLOR_ATTRIBUTES = (
    "kelvin",
    "rgb_color",
    "white_value",
    "color_temp",
    "color_name",
    "hs_color",
)

DEFAULT_STATE = "on_if_anything_on"

def async_partial(func, *args, **kwargs):
    return asyncio.coroutine(partial(func, *args, **kwargs))


@asyncio.coroutine
def async_setup(hass, config):
    light_groups = LightGroupsConfig(config[DOMAIN])

    hass.bus.async_listen(
        EVENT_SERVICE_REGISTERED, partial(on_service_registered, hass, light_groups),
    )

    hass.bus.async_listen(
        EVENT_STATE_CHANGED, partial(on_state_changed, hass, light_groups),
    )

    hass.services.async_register(
        DOMAIN, "light_on", async_partial(service_light_on, hass, light_groups)
    )
    hass.services.async_register(
        DOMAIN, "light_off", async_partial(service_light_off, hass, light_groups)
    )
    hass.services.async_register(
        DOMAIN, "light_toggle", async_partial(service_light_toggle, hass, light_groups)
    )

    return True


async def service_light_on(hass, light_groups, call):
    _LOGGER.info("Light on", call.data)

    group_name = call.data["light_group"]
    group = light_groups.get_group_by_name(group_name)

    _LOGGER.debug("Lights %s", group["lights"])

    await group_lights_turn_on(hass, group, call.data)


async def service_light_off(hass, light_groups, call):
    _LOGGER.info("Light off %s", call.data)

    group_name = call.data["light_group"]
    group = light_groups.get_group_by_name(group_name)

    await group_lights_turn_off(hass, group)


async def service_light_toggle(hass, light_groups, call):
    _LOGGER.info("Light toggle %s", call.data)

    group_name = call.data["light_group"]
    group = light_groups.get_group_by_name(group_name)

    anything_on = is_anything_on(hass, group)

    if anything_on:
        await group_lights_turn_off(hass, group)
    else:
        await group_lights_turn_on(hass, group)


async def on_state_changed(hass, light_groups, event):
    groups = light_groups.get_group_by_preset_id(event.data.get("entity_id"),)

    if groups and event.data.get("old_state"):
        _LOGGER.info("preset changed event %s", event)
        for group in groups:
            _LOGGER.info("Updating group %s", group["id"])
            await group_lights_update(hass, group)


_light_override_registered = False


async def on_service_registered(hass, light_groups, event):
    global _light_override_registered

    if (
        event.data.get("domain") == "light"
        and event.data.get("service") == "turn_on"
        and _light_override_registered is False
    ):
        services = hass.services.async_services()
        try:
            light_turn_on = services["light"]["turn_on"]
        except KeyError:
            _LOGGER.warning("Light service not found, not overriding")
            return

        override = async_partial(turn_on_override, hass, light_groups, light_turn_on)

        hass.services.async_remove("light", "turn_on")
        _LOGGER.debug("Removed light service")
        _light_override_registered = True
        hass.services.async_register(
            "light",
            "turn_on",
            override,
            schema=cv.make_entity_service_schema(
                LIGHT_TURN_ON_SCHEMA, extra=vol.ALLOW_EXTRA
            ),
        )
        _LOGGER.debug("Registered light service override")


async def turn_on_override(hass, light_groups, light_turn_on, event):
    _LOGGER.debug("Override light turn on event %s", event)

    light = event.data.get("entity_id")

    # FIXME: handle lists correctly
    if isinstance(light, list):
        light = light[0]

    group = light_groups.get_group_by_light(light)

    has_custom_attributes = any(attr in event.data for attr in LIGHT_ATTRIBUTES)

    if group and not has_custom_attributes:
        settings = get_light_settings(hass, group, light)
        attributes = settings["attributes"]

        _LOGGER.debug("Adding turn on default attributes %s", attributes)

        event_data = {
            **event.data,
            **attributes,
        }
        _LOGGER.debug("New event attributes %s", event_data)

    else:
        event_data = event.data

    event = ServiceCall(
        domain=event.domain,
        service=event.service,
        data=preprocess_data(hass, {**event_data}),
        context=event.context,
    )

    await light_turn_on.job.target(event)


async def group_lights_update(hass, group):
    anything_on = is_anything_on(hass, group)

    for light in group["lights"]:
        settings = get_light_settings(hass, group, light)
        attributes = settings["attributes"]
        meta = settings["meta"]

        _LOGGER.debug("Updating light %s using settings %s", light, settings)

        if is_light_on(hass, light):
            if meta["state"] == "off":
                await turn_off_light(hass, light)
            else:
                await turn_on_light(hass, light, attributes)
        elif meta["state"] == "on" or (
            meta["state"] == "on_if_anything_on" and anything_on
        ):
            await turn_on_light(hass, light, attributes)


async def group_lights_turn_on(hass, group, service_params={}):
    for light in group["lights"]:
        settings = get_light_settings(hass, group, light)
        attributes = settings["attributes"]
        meta = settings["meta"]

        if 'preset_brightness_pct' in service_params:
            attributes['brightness'] = attributes.get('brightness', 255) * service_params['preset_brightness_pct'] / 100

        if meta["state"] != "off":
            await turn_on_light(hass, light, attributes)


async def group_lights_turn_off(hass, group):
    await hass.services.async_call("light", "turn_off", {"entity_id": group["lights"],})


async def turn_on_light(hass, light, attributes):
    _LOGGER.debug("turn on attributes %s", attributes)
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": light, **attributes,}
    )


async def turn_off_light(hass, light):
    await hass.services.async_call("light", "turn_off", {"entity_id": light,})


def is_anything_on(hass, group):
    return any(is_light_on(hass, light) for light in group["lights"])

def is_light_on(hass, light):
    light_state = hass.states.get(light)

    return light_state and light_state.state == STATE_ON


def get_group_attributes(hass, group):
    selected_preset = hass.states.get(group["preset"]).state
    return group["presets"].get(selected_preset.lower(), {}).get("defaults")


def get_light_settings(hass, group, entity_id):
    selected_preset = hass.states.get(group["preset"]).state

    preset = group["presets"].get(selected_preset.lower(), {})

    defaults = preset.get("defaults", {})
    overrides = preset.get(entity_id, {})

    merged = merge_light_attributes(defaults, overrides)

    meta = {
        "state": merged.pop("state", DEFAULT_STATE),
    }

    return {
        "attributes": merged,
        "meta": meta,
    }


def merge_light_attributes(defaults, overrides):
    sets_color = lambda attr: len(set(attr.keys()) & set(COLOR_ATTRIBUTES)) > 0
    if sets_color(defaults) and sets_color(overrides):
        defaults = {k: v for (k, v) in defaults.items() if k not in COLOR_ATTRIBUTES}

    return {**defaults, **overrides}


class LightGroupsConfig:
    def __init__(self, config):
        for id, group in config.items():
            group["id"] = id

        self._config = config

    def get_group_by_preset_id(self, entity_id):
        return [
            group for id, group in self._config.items() if group["preset"] == entity_id
        ]

    def get_group_by_name(self, name):
        return next((group for id, group in self._config.items() if id == name), None,)

    def get_group_by_light(self, light):
        for group in self._config.values():
            if light in group["lights"]:
                return group

"""
Copied from light service
"""
def preprocess_data(hass, data):
    """Preprocess the service data."""
    base = {
        entity_field: data.pop(entity_field)
        for entity_field in cv.ENTITY_SERVICE_FIELDS
        if entity_field in data
    }

    preprocess_turn_on_alternatives(hass, data)
    base["params"] = data
    return base
