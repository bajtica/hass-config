"""
Support Denon and Marantz AVR's on the Home-Assistant project
using the HTTP / XML-based API's instead of the commonly used telnet connections
https://home-assistant.io/
"""

import logging
import xml.etree.ElementTree as eTree
import urllib.request
import urllib.parse
import urllib.error

from homeassistant.components.media_player import DOMAIN
from homeassistant.components.media_player import (
    SUPPORT_TURN_OFF, SUPPORT_TURN_ON, SUPPORT_VOLUME_MUTE, SUPPORT_VOLUME_SET,
    SUPPORT_SELECT_SOURCE, MediaPlayerDevice)
from homeassistant.const import CONF_HOST, STATE_OFF, STATE_ON, STATE_UNKNOWN

_LOGGER = logging.getLogger(__name__)

SUPPORT_DENON = SUPPORT_VOLUME_SET | SUPPORT_VOLUME_MUTE | \
                SUPPORT_TURN_ON | SUPPORT_TURN_OFF | SUPPORT_SELECT_SOURCE


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Setup the Denon platform."""
    if not config.get(CONF_HOST):
        _LOGGER.error(
            "Missing required configuration items in %s: %s",
            DOMAIN,
            CONF_HOST)
        return False

    denon = DenonDevice(
        config.get("name", "Music station"),
        config.get("host")
    )
    if denon.update():
        add_devices([denon])
        return True
    else:
        return False


class DenonDevice(MediaPlayerDevice):
    """Representation of a Denon device."""

    DENON_MIN_VOLUME = -80
    DENON_MAX_VOLUME = 18

    def __init__(self, name, host):
        """Initialize the Denon device."""
        self._name = name

        if not host.startswith('http://'):
            host = 'http://{}'.format(host)

        self._host = host
        self._mainzone_url = self._host + '/goform/formMainZone_MainZoneXml.xml'
        self._mainzone_status_url = self._host + '/goform/formMainZone_MainZoneXmlStatus.xml'
        self._post_url = self._host + '/MainZone/index.put.asp'

        self._friendlyname = None
        self._pwstate = STATE_UNKNOWN
        self._volume = 0
        self._muted = False
        self._current_source = None
        self._source_list = None
        self._source_lookup = None

        self.update()

    @staticmethod
    def __get_xml_elements(src_xml, xpath=None):
        try:
            tree = eTree.parse(src_xml)
        except eTree.ParseError:
            logging.exception('An exception occured while trying to parse the xml elements!')
            return False
        else:
            root = tree.getroot()

            if xpath is None:
                return root
            else:
                return root.findall(xpath)

    def _get_api_value(self, value, target=None, return_as_string=True):
        """Connect to the API and return the content for `value`."""
        if target == 'MainZoneXmlStatus':
            target_url = self._mainzone_status_url
        else:
            target_url = self._mainzone_url

        try:
            response = urllib.request.urlopen(target_url)
        except urllib.error.HTTPError as e:
            logging.error('Error code: ', e.code)
            return False
        except urllib.error.URLError as e:
            logging.error('Reason: ', e.reason)
            return False

        api_results = (self.__get_xml_elements(response, './/{}/value'.format(value)))
        results = []

        if len(api_results) > 0:
            for api_result in api_results:
                if return_as_string:
                    if api_result.text is not None:
                        results.append(api_result.text)
                    else:
                        results.append('')
                else:
                    results.append(api_result)

        if len(results) == 1:
            return results[0]
        elif len(results) > 1:
            return results
        else:
            logging.warning('No value found for item {}'.format(value))
            return False

    def _send_api_command(self, command):
        """Establish a connection to the API and send `command`."""
        body = urllib.parse.urlencode({
            'cmd0': command
        })
        body = body.encode('UTF-8')

        url = urllib.request.Request(self._post_url, body)
        url.add_header("Content-type", "text/html")

        try:
            urllib.request.urlopen(url).read()
        except urllib.error.HTTPError as e:
            logging.error('Error code: ', e.code)
            return False
        except urllib.error.URLError as e:
            logging.error('Reason: ', e.reason)
            return False
        else:
            self.update()
            return True

    def update(self):
        """Get the latest details from the device."""
        self._friendlyname = self._get_api_value('FriendlyName')

        if self._get_api_value('Power') == "ON":
            self._pwstate = STATE_ON
        else:
            self._pwstate = STATE_OFF

        self._current_source = self._get_api_value('InputFuncSelect')
        self._volume = self._get_api_value('MasterVolume')

        if self._get_api_value('Mute') == "on":
            self._muted = True
        else:
            self._muted = False

        if self._source_list is None:
            self.build_source_list()

        return True

    def build_source_list(self):
        """Build the source list."""
        input_func_list = self._get_api_value('InputFuncList', 'MainZoneXmlStatus')
        rename_source = self._get_api_value('RenameSource/value', 'MainZoneXmlStatus')
        source_delete = self._get_api_value('SourceDelete', 'MainZoneXmlStatus')

        video_select_lists = {}
        for element in self._get_api_value('VideoSelectLists', return_as_string=False):
            if 'index' in element.attrib and 'table' in element.attrib and element.text is None:
                video_select_lists[element.attrib['table'].upper().strip()] = element.attrib['index']
            elif 'index' in element.attrib and element.text is not None:
                video_select_lists[element.text.upper().strip()] = element.attrib['index']

        self._source_list = []
        self._source_lookup = {}
        for index in range(len(input_func_list)):
            if source_delete[index].upper() == 'USE':
                input_pretty_name = rename_source[index].strip()
                input_name = input_func_list[index]

                if input_name.upper() in video_select_lists:
                    input_name = video_select_lists[input_name.upper()]

                self._source_list.append(input_pretty_name)
                self._source_lookup[input_pretty_name] = input_name

        return True

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def friendly_name(self):
        """Return the friendly name of the device."""
        return self._friendlyname

    @property
    def supported_media_commands(self):
        """Flag of media commands that are supported."""
        return SUPPORT_DENON

    @property
    def state(self):
        """Return the state of the device."""
        return self._pwstate

    @property
    def volume_level(self):
        """Volume level of the media player (0..1) converted from DENON_MIN_VOLUME to DENON_MAX_VOLUME range."""
        volume = (((float(self._volume) - self.DENON_MIN_VOLUME) * (1 - 0)) / (
            self.DENON_MAX_VOLUME - self.DENON_MIN_VOLUME)) + 0
        return volume

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        return self._muted

    @property
    def source(self):
        """Return the current input source."""
        return self._current_source

    @property
    def source_list(self):
        """List of available input sources."""
        return sorted(self._source_lookup.keys())

    def volume_up(self):
        """Volume up media player."""
        self._send_api_command("PutMasterVolumeSet/>")

    def volume_down(self):
        """Volume down media player."""
        self._send_api_command("PutMasterVolumeSet/<")

    def set_volume_level(self, volume):
        """Set volume level, convert range 0..1 to DENON_MIN_VOLUME to DENON_MAX_VOLUME."""
        new_volume = (volume * (self.DENON_MAX_VOLUME - self.DENON_MIN_VOLUME)) + \
            self.DENON_MIN_VOLUME
        self._set_volume_level_relative(new_volume)

    def _set_volume_level_relative(self, volume):
        """Set volume level to a relative value within the min/max range of the receiver."""
        # Make sure the new volume respects the DENON_MIN_VOLUME and DENON_MAX_VOLUME values
        volume = self.DENON_MIN_VOLUME if volume < self.DENON_MIN_VOLUME else volume
        volume = self.DENON_MAX_VOLUME if volume > self.DENON_MAX_VOLUME else volume
        volume = round(volume * 2.0) / 2.0

        self._send_api_command("PutMasterVolumeSet/{}".format(volume))

    def mute_volume(self, mute):
        """Mute (true) or unmute (false) receiver."""
        self._send_api_command("PutVolumeMute/" + ("on" if mute else "off"))

    def select_source(self, source):
        """Select input source based on the mapping/renaming done by the receiver."""
        if source in self._source_lookup:
            source = self._source_lookup[source]
        self._send_api_command("PutZone_InputFunction/" + source)

    def turn_off(self):
        """Turn off media player."""
        self._send_api_command("PutZone_OnOff/OFF")

    def turn_on(self):
        """Turn the media player on."""
        self._send_api_command("PutZone_OnOff/ON")
