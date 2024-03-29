#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#
"""
Collection of functions for importing data from PMS and a runner to front them.

Functions:
    canImport
    canUpdateLastPlayedOnProvider
    canUpdateMetadataOnProvider
    canUpdatePlaycountOnProvider
    canUpdateResumePositionOnProvider
    discoverProvider
    discoverProviderLocally
    discoverProviderWithMyPlex
    execImport
    getServerId
    getLibrarySections
    getLibrarySectionsFromSettings
    getMatchingLibrarySections
    getServerResources
    isProviderReady
    isImportReady
    linkMyPlexAccount
    linkToMyPlexAccount
    loadImportSettings
    loadProviderSettings
    lookupProvider
    mediaTypesFromOptions
    run
    settingOptionsFillerLibrarySections
    testConnection
    updateOnProvider
"""
from dateutil import parser
from datetime import timezone
import sys
import time
from typing import List

from six.moves.urllib.parse import parse_qs, unquote, urlparse

import xbmc  # pylint: disable=import-error
import xbmcaddon  # pylint: disable=import-error
import xbmcgui  # pylint: disable=import-error
import xbmcmediaimport  # pylint: disable=import-error

import plexapi.exceptions
from plexapi.myplex import MyPlexAccount, MyPlexPinLogin, MyPlexResource
from plexapi.server import PlexServer

from lib.utils import getIcon, localize, log, mediaProvider2str, normalizeString
from lib.settings import ImportSettings, ProviderSettings, SynchronizationSettings

import plex
from plex.api import Api
from plex.converter import ToFileItemConverterThread
from plex.server import Server
from plex.constants import SETTINGS_PROVIDER_PLAYBACK_ALLOW_DIRECT_PLAY

# general constants
ITEM_REQUEST_LIMIT = 100


def mediaTypesFromOptions(options: dict) -> List[str]:
    """Parse mediatypes section from the provided options

    :param options: Options/parameters passed in with the call
    :type options: dict
    :return: List of media type strings parsed from options
    :rtype: list
    """
    if 'mediatypes' not in options and 'mediatypes[]' not in options:
        return None

    if 'mediatypes' in options.keys():
        mediaTypes = options['mediatypes']
    elif 'mediatypes[]' in options.keys():
        mediaTypes = options['mediatypes[]']
    else:
        mediaTypes = None

    return mediaTypes


def getServerId(path: str) -> str:
    """Parse the IP or hostname of the server from its URI

    :param path: A full URI (https://mything.com/some/path/to?query!=thing)
    :type path: str
    :return: IP or hostname of the server
    :rtype: str
    """
    if not path:
        return ""

    url = urlparse(path)
    if url.scheme != plex.constants.PLEX_PROTOCOL or not url.netloc:
        return ""

    return url.netloc


def getLibrarySections(plexServer: PlexServer, mediaTypes: List[str]) -> List[dict]:
    """Get a list of Plex library sections with types matching the provided list of media types

    :param plexServer: Plex server to pull list of libraries from
    :type plexServer: :class:`PlexServer`
    :param mediaTypes: List of media type strings to pull matching libraries of
    :type mediaTypes: list
    :return: List of matching library sections, dict with 'key' and 'title'
    :rtype: list
    """
    if not plexServer:
        raise ValueError('invalid plexServer')
    if not mediaTypes:
        raise ValueError('invalid mediaTypes')

    # get all library sections
    librarySections = []
    for section in plexServer.library.sections():
        plexMediaType = section.type
        kodiMediaTypes = Api.getKodiMediaTypes(plexMediaType)
        if not kodiMediaTypes:
            continue

        if not any(kodiMediaType['kodi'] in mediaTypes for kodiMediaType in kodiMediaTypes):
            continue

        librarySections.append({
            'key': section.key,
            'title': section.title
        })

    return librarySections


def getLibrarySectionsFromSettings(importSettings: xbmcaddon.Settings) -> List[int]:
    """Parses library sections from provided addon settings object

    :param importSettings: Settings from the mediaImport being processed
    :type importSettings: xbmcaddon.Settings
    :return: List of library section names
    :rtype: list
    """
    if not importSettings:
        raise ValueError('invalid importSettings')

    # TODO(Montellese): store section IDs as an int instead of str
    librarySectionsStr = importSettings.getStringList(plex.constants.SETTINGS_IMPORT_LIBRARY_SECTIONS)
    return [int(librarySectionStr) for librarySectionStr in librarySectionsStr]


def getMatchingLibrarySections(
        plexServer: PlexServer,
        mediaTypes: List[str],
        selectedLibrarySections: List[int]
) -> List[dict]:
    """Pull list of library sections matching both the media type and selection provided

    :param plexServer: Plex server to pull list of libraries from
    :type plexServer: :class:`PlexServer`
    :param mediaTypes: List of media type strings to pull matching libraries of
    :type mediaTypes: list
    :param selectedLibrarySections: List of library section names
    :type selectedLibrarySections: list
    :return: List of matching library sections, dict with 'key' and 'title'
    :rtype: list
    """
    if not plexServer:
        raise ValueError('invalid plexServer')
    if not mediaTypes:
        raise ValueError('invalid mediaTypes')

    if not selectedLibrarySections:
        return []

    librarySections = getLibrarySections(plexServer, mediaTypes)

    return [librarySection for librarySection in librarySections if librarySection['key'] in selectedLibrarySections]


def discoverProviderLocally(handle: int, _options: dict) -> xbmcmediaimport.MediaProvider:
    """Set up a Plex server provider from user-provided URL

    :param handle: Handle id from input
    :type handle: int
    :param _options: Options/parameters passed in with the call, unused
    :type _options: dict
    :return: Fully setup and populated mediaProvider object for the PMS
    :rtype: xbmcmediaimport.MediaProvider
    """
    dialog = xbmcgui.Dialog()

    baseUrl = dialog.input(localize(32051))
    if not baseUrl:
        return None

    plexServer = PlexServer(baseUrl, timeout=plex.constants.REQUEST_TIMEOUT)
    if not plexServer:
        return None

    providerId = Server.BuildProviderId(plexServer.machineIdentifier)
    providerIconUrl = getIcon()

    provider = xbmcmediaimport.MediaProvider(
        identifier=providerId,
        friendlyName=plexServer.friendlyName,
        iconUrl=providerIconUrl,
        mediaTypes=plex.constants.SUPPORTED_MEDIA_TYPES,
        handle=handle
    )

    # store local authentication in settings
    providerSettings = provider.prepareSettings()
    if not providerSettings:
        return None

    ProviderSettings.SetUrl(providerSettings, baseUrl)
    ProviderSettings.SetAuthenticationMethod(providerSettings, \
        plex.constants.SETTINGS_PROVIDER_AUTHENTICATION_OPTION_LOCAL)
    providerSettings.save()

    return provider


def linkToMyPlexAccount() -> MyPlexAccount:
    """Log into MyPlex with user-provided settings and get authentication token

    :return: Returns authenticated MyPlexAccount object
    :rtype: :class:`MyPlexAccount`
    """
    dialog = xbmcgui.Dialog()

    pinLogin = MyPlexPinLogin()
    if not pinLogin.pin:
        dialog.ok(localize(32015), localize(32052))
        log('failed to get PIN to link MyPlex account', xbmc.LOGWARNING)
        return None

    # show the user the pin
    dialog.ok(localize(32015), localize(32053, pinLogin.pin))

    # check the status of the authentication
    while not pinLogin.finished:
        if pinLogin.checkLogin():
            break

    if pinLogin.expired:
        dialog.ok(localize(32015), localize(32054))
        log("linking the MyPlex account has expiried", xbmc.LOGWARNING)
        return None

    if not pinLogin.token:
        log("no valid token received from the linked MyPlex account", xbmc.LOGWARNING)
        return None

    # login to MyPlex
    try:
        plexAccount = MyPlexAccount(token=pinLogin.token, timeout=plex.constants.REQUEST_TIMEOUT)
    except Exception as e:
        log(f"failed to connect to the linked MyPlex account: {e}", xbmc.LOGWARNING)
        return None
    if not plexAccount:
        log("failed to connect to the linked MyPlex account", xbmc.LOGWARNING)
        return None

    return plexAccount


def getServerResources(plexAccount: MyPlexAccount) -> List[MyPlexResource]:
    """Get list of plex servers connected to the MyPlexAccount provided

    :param plexAccount: Authenticated PlexAccount object to pull resources from
    :type plexAccount: :class:`MyPlexAccount`
    :return: List of MyPlexResource objects (servers) connected to the plex account
    :rtype: list
    """
    if not plexAccount:
        raise ValueError('invalid plexAccount')

    # get all connected resources
    resources = plexAccount.resources()
    if not resources:
        return []

    # we are only interested in Plex Media Server resources
    return [
        resource for resource in resources
        if resource.product == 'Plex Media Server' and 'server' in resource.provides
    ]


def linkMyPlexAccount(handle: int, _options: dict):
    """Have user sign into MyPlex account, find servers on the account, and save authenticatino details for the server

    :param handle: Handle id from input
    :type handle: int
    :param _options: Options/parameters passed in with the call, unused
    :type _options: dict
    """
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # get the media provider settings
    providerSettings = mediaProvider.prepareSettings()
    if not providerSettings:
        return

    plexAccount = linkToMyPlexAccount()
    if not plexAccount:
        return

    username = plexAccount.username
    if not username:
        log('no valid username available for the linked MyPlex account', xbmc.LOGWARNING)
        return

    # make sure the configured Plex Media Server is still accessible
    serverUrl = ProviderSettings.GetUrl(providerSettings)
    matchingServer = None

    serverId = getServerId(mediaProvider.getIdentifier())

    # get all connected server resources
    serverResources = getServerResources(plexAccount)
    for server in serverResources:
        if server.clientIdentifier == serverId:
            matchingServer = server
            break

    if not matchingServer:
        log(f"no Plex Media Server matching {serverUrl} found", xbmc.LOGWARNING)
        xbmcgui.Dialog().ok(localize(32015), localize(32058))
        return

    xbmcgui.Dialog().ok(localize(32015), localize(32059, username))

    # change the settings
    ProviderSettings.SetUsername(providerSettings, username)
    ProviderSettings.SetAccessToken(providerSettings, matchingServer.accessToken)


def testConnection(handle: int, _options: dict):
    """Test connection to the user provided PMS and display results to user

    :param handle: Handle id from input
    :type handle: int
    :param _options: Options/parameters passed in with the call, unused
    :type _options: dict
    """
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    success = False
    try:
        success = Server(mediaProvider).Authenticate()
    except:
        pass

    title = mediaProvider.getFriendlyName()
    line = 32019
    if success:
        line = 32018

    xbmcgui.Dialog().ok(title, localize(line))


def changeUrl(handle: int, _options: dict):
    """Change the URL of PMS

    :param handle: Handle id from input
    :type handle: int
    :param _options: Options/parameters passed in with the call, unused
    :type _options: dict
    """
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # get the media provider settings
    providerSettings = mediaProvider.prepareSettings()
    if not providerSettings:
        log("cannot prepare provider settings", xbmc.LOGERROR)
        return

    urlCurrent = ProviderSettings.GetUrl(providerSettings)
    if not urlCurrent:
        log("cannot retrieve current URL from provider settings", xbmc.LOGERROR)
        return

    # ask the user for a new URL
    urlNew = xbmcgui.Dialog().input(localize(32068), urlCurrent)
    if not urlNew:
        return

    # store the new URL in the settings
    ProviderSettings.SetUrl(providerSettings, urlNew)

    # try to connect and authenticate with the new URL
    success = False
    try:
        success = Server(mediaProvider).Authenticate()
    except:
        pass

    dialog = xbmcgui.Dialog()
    title = mediaProvider.getFriendlyName()
    if success:
        dialog.ok(title, localize(32018))
    else:
        # ask the user whether to change the URL anyway
        changeUrlAnyway = dialog.yesno(title, localize(32069))
        if not changeUrlAnyway:
            # revert the settings to the previous / old URL
            ProviderSettings.SetUrl(providerSettings, urlCurrent)


def discoverProviderWithMyPlex(handle: int, _options: dict) -> xbmcmediaimport.MediaProvider:
    """
    Prompts user to sign into their Plex account using the MyPlex pin link
    Finds a list of all servers connected to the account and prompts user to pick one
        Prompt for a local discovery if no servers found within their Plex account
    Setup and store the Plex server as a MediaProvider and store MyPlex auth information

    :param handle: Handle id from input
    :type handle: int
    :param _options: Options/parameters passed in with the call, unused
    :type _options: dict
    :return: Fully configured and authenticated Plex media provider
    :rtype: :class:`xbmcmediaimport.MediaProvider`
    """
    plexAccount = linkToMyPlexAccount()
    if not plexAccount:
        return None

    username = plexAccount.username
    if not username:
        log("no valid username available for the linked MyPlex account", xbmc.LOGWARNING)
        return None

    dialog = xbmcgui.Dialog()

    # get all connected server resources
    serverResources = getServerResources(plexAccount)
    if not serverResources:
        log(f"no servers available for MyPlex account {username}", xbmc.LOGWARNING)
        return None

    if len(serverResources) == 1:
        server = serverResources[0]
    else:
        # ask the user which server to use
        servers = [resource.name for resource in serverResources]
        serversChoice = dialog.select(localize(32055), servers)
        if serversChoice < 0 or serversChoice >= len(servers):
            return None

        server = serverResources[serversChoice]

    if not server:
        return None

    if not server.connections:
        # try to connect to the server
        plexServer = server.connect(timeout=plex.constants.REQUEST_TIMEOUT)
        if not plexServer:
            log(f"failed to connect to the Plex Media Server '{server.name}'", xbmc.LOGWARNING)
            return None

        baseUrl = plexServer.url('', includeToken=False)
    else:
        isLocal = False
        localConnections = [connection for connection in server.connections if connection.local]
        remoteConnections = [
            connection for connection in server.connections if not connection.local and not connection.relay
        ]
        remoteRelayConnections = [
            connection for connection in server.connections if not connection.local and connection.relay
        ]

        if localConnections:
            # ask the user whether to use a local or remote connection
            isLocal = dialog.yesno(localize(32056), localize(32057, server.name))

        urls = []
        if isLocal:
            urls.append((localConnections[0].httpuri, False))
        else:
            urls.extend([(conn.uri, False) for conn in remoteConnections])
            urls.extend([(conn.uri, True) for conn in remoteRelayConnections])
            urls.extend([(conn.uri, False) for conn in localConnections])

        baseUrl = None
        connectViaRelay = True
        # find a working connection / base URL
        for (url, isRelay) in urls:
            try:
                # don't try to connect via relay if the user has already declined it before
                if isRelay and not connectViaRelay:
                    log(f"ignoring relay connection to the Plex Media Server '{server.name}' at {url}", xbmc.LOGDEBUG)
                    continue

                # try to connect to the server
                _ = PlexServer(baseurl=url, token=server.accessToken, timeout=plex.constants.REQUEST_TIMEOUT)

                # if this is a relay ask the user if using it is ok
                if isRelay:
                    connectViaRelay = dialog.yesno(localize(32056), localize(32061, server.name))
                    if not connectViaRelay:
                        log(
                            f"ignoring relay connection to the Plex Media Server '{server.name}' at {url}",
                            xbmc.LOGDEBUG
                        )
                        continue

                baseUrl = url
                break
            except:
                log(f"failed to connect to '{server.name}' at {url}", xbmc.LOGDEBUG)
                continue

        if not baseUrl:
            dialog.ok(localize(32056), localize(32060, server.name))
            log(
                f"failed to connect to the Plex Media Server '{server.name}' for MyPlex account {username}",
                xbmc.LOGWARNING
            )
            return None

    if not baseUrl:
        log(
            f"failed to find the URL to access the Plex Media Server '{server.name}' for MyPlex account {username}",
            xbmc.LOGWARNING
        )
        return None

    log(
        f"successfully connected to Plex Media Server '{server.name}' for MyPlex account {username} at {baseUrl}",
        xbmc.LOGINFO
    )

    providerId = plex.server.Server.BuildProviderId(server.clientIdentifier)
    providerIconUrl = getIcon()
    provider = xbmcmediaimport.MediaProvider(
        providerId,
        server.name,
        providerIconUrl,
        plex.constants.SUPPORTED_MEDIA_TYPES,
        handle=handle
    )

    # store MyPlex account details and token in settings
    providerSettings = provider.prepareSettings()
    if not providerSettings:
        return None

    ProviderSettings.SetUrl(providerSettings, baseUrl)
    ProviderSettings.SetAuthenticationMethod(providerSettings, \
        plex.constants.SETTINGS_PROVIDER_AUTHENTICATION_OPTION_MYPLEX)
    ProviderSettings.SetUsername(providerSettings, username)
    ProviderSettings.SetAccessToken(providerSettings, server.accessToken)
    providerSettings.save()

    return provider


def discoverProvider(handle: int, options: dict):
    """Prompt user for Plex authentication type, perform server discovery based on their choice, register the provider

    :param handle: Handle id from input
    :type handle: int
    :param options: Options/parameters passed in with the call
    :type options: dict
    """
    dialog = xbmcgui.Dialog()

    authenticationChoices = [
        localize(32013),  # local only
        localize(32014)   # MyPlex
    ]
    authenticationChoice = dialog.select(localize(32050), authenticationChoices)

    if authenticationChoice == 0:  # local only
        provider = discoverProviderLocally(handle, options)
    elif authenticationChoice == 1:  # MyPlex
        provider = discoverProviderWithMyPlex(handle, options)
    else:
        return

    if not provider:
        return

    xbmcmediaimport.setDiscoveredProvider(handle, True, provider)


def lookupProvider(handle: int, _options: dict):
    """Find provider from handle ID, authenticate to it, and set as active

    :param handle: Handle id from input
    :type handle: int
    :param _options: Options/parameters passed in with the call, unused
    :type _options: dict
    """
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log("cannot retrieve media provider", xbmc.LOGERROR)
        xbmcmediaimport.setProviderFound(handle, False)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log("cannot prepare media provider settings", xbmc.LOGERROR)
        xbmcmediaimport.setProviderFound(handle, False)
        return

    providerFound = False
    try:
        providerFound = Server(mediaProvider).Authenticate()
    except:
        pass

    xbmcmediaimport.setProviderFound(handle, providerFound)


def canImport(handle: int, options: dict):
    """Validate that the 'path' in options references a PMS that can be imported

    :param handle: Handle id from input
    :type handle: int
    :param options: Options/parameters passed in with the call, 'path' required
    :type options: dict
    """
    if 'path' not in options:
        log("cannot execute 'canimport' without path", xbmc.LOGERROR)
        xbmcmediaimport.setCanImport(handle, False)
        return

    path = unquote(options['path'][0])

    # try to get the Plex Media Server's identifier from the path
    identifier = getServerId(path)
    if not identifier:
        return

    xbmcmediaimport.setCanImport(handle, True)


def isProviderReady(handle: int, _options: dict):
    """Validate that the provider from handle ID exists, can be connected to, and that stored authentication works

    :param handle: Handle id from input
    :type handle: int
    :param _options: Options/parameters passed in with the call, Unused
    :type _options: dict
    """
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        xbmcmediaimport.setProviderReady(handle, False)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('cannot prepare media provider settings', xbmc.LOGERROR)
        xbmcmediaimport.setProviderReady(handle, False)
        return

    # check if authentication works with the current provider settings
    providerReady = False
    try:
        providerReady = Server(mediaProvider).Authenticate()
    except:
        pass

    xbmcmediaimport.setProviderReady(handle, providerReady)


def isImportReady(handle: int, _options: dict):
    """Validate that MediaImport at handle ID and associated provider are ready

    :param handle: Handle id from input
    :type handle: int
    :param _options: Options/parameters passed in with the call, Unused
    :type _options: dict
    """
    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log("cannot retrieve media import", xbmc.LOGERROR)
        xbmcmediaimport.setImportReady(handle, False)
        return

    # prepare and get the media import settings
    importSettings = mediaImport.prepareSettings()
    if not importSettings:
        log("cannot prepare media import settings", xbmc.LOGERROR)
        xbmcmediaimport.setImportReady(handle, False)
        return

    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log("cannot retrieve media provider", xbmc.LOGERROR)
        xbmcmediaimport.setImportReady(handle, False)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log("cannot prepare media provider settings", xbmc.LOGERROR)
        xbmcmediaimport.setImportReady(handle, False)
        return

    try:
        server = Server(mediaProvider)
    except:
        pass

    importReady = False
    # check if authentication works with the current provider settings
    if server.Authenticate():
        # check if the chosen library sections exist
        selectedLibrarySections = getLibrarySectionsFromSettings(importSettings)
        matchingLibrarySections = getMatchingLibrarySections(
            server.PlexServer(),
            mediaImport.getMediaTypes(),
            selectedLibrarySections
        )
        importReady = len(matchingLibrarySections) > 0

    xbmcmediaimport.setImportReady(handle, importReady)


def loadProviderSettings(handle: int, _options: dict):
    """Load and save settings from media provider at handle ID, register some callbacks in the settings

    :param handle: Handle id from input
    :type handle: int
    :param _options: Options/parameters passed in with the call, Unused
    :type _options: dict
    """
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log("cannot retrieve media provider", xbmc.LOGERROR)
        return

    settings = mediaProvider.getSettings()
    if not settings:
        log("cannot retrieve media provider settings", xbmc.LOGERROR)
        return

    settings.registerActionCallback(plex.constants.SETTINGS_PROVIDER_LINK_MYPLEX_ACCOUNT, 'linkmyplexaccount')
    settings.registerActionCallback(plex.constants.SETTINGS_PROVIDER_TEST_CONNECTION, 'testconnection')
    settings.registerActionCallback(plex.constants.SETTINGS_PROVIDER_ADVANCED_CHANGE_URL, 'changeurl')

    settings.setLoaded()


def forceSync(handle: int, _options: dict):
    """Confirm if user wants to force a full sync and update the settings hash

    :param handle: Handle id from input
    :type handle: int
    :param _options: Options/parameters passed in with the call, Unused
    :type _options: dict
    """
    # ask the user whether he is sure
    force = xbmcgui.Dialog().yesno(localize(32022), localize(32065))
    if not force:
        return

    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return

    # prepare the media provider settings
    importSettings = mediaImport.prepareSettings()
    if not importSettings:
        log('cannot prepare media import settings', xbmc.LOGERROR)
        return

    # reset the synchronization hash setting to force a full synchronization
    SynchronizationSettings.ResetHash(importSettings, save=False)

    # tell the user that he needs to save the settings
    xbmcgui.Dialog().ok(localize(32022), localize(32067))


def settingOptionsFillerLibrarySections(handle: int, _options: dict):
    """Find and set the library sections setting from Plex matching a mediaImport's media type

    :param handle: Handle id from input
    :type handle: int
    :param _options: Options/parameters passed in with the call, Unused
    :type _options: dict
    """
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('cannot prepare media provider settings', xbmc.LOGERROR)
        return

    server = Server(mediaProvider)
    if not server.Authenticate():
        log(f"failed to connect to Plex Media Server for {mediaProvider2str(mediaProvider)}", xbmc.LOGWARNING)
        return

    plexServer = server.PlexServer()

    # get all library sections
    mediaTypes = mediaImport.getMediaTypes()
    librarySections = getLibrarySections(plexServer, mediaTypes)
    # TODO(Montellese): store section IDs as an int instead of str
    sections = [(section['title'], str(section['key'])) for section in librarySections]

    # get the import's settings
    settings = mediaImport.getSettings()

    # pass the list of views back to Kodi
    settings.setStringOptions(plex.constants.SETTINGS_IMPORT_LIBRARY_SECTIONS, sections)


def loadImportSettings(handle: int, _options: dict):
    """Load and save settings from media import at handle ID, register some callbacks in the settings

    :param handle: Handle id from input
    :type handle: int
    :param _options: Options/parameters passed in with the call, Unused
    :type _options: dict
    """
    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return

    settings = mediaImport.getSettings()
    if not settings:
        log('cannot retrieve media import settings', xbmc.LOGERROR)
        return

    # register force sync callback
    settings.registerActionCallback(plex.constants.SETTINGS_IMPORT_FORCE_SYNC, 'forcesync')

    # register a setting options filler for the list of views
    settings.registerOptionsFillerCallback(
        plex.constants.SETTINGS_IMPORT_LIBRARY_SECTIONS,
        'settingoptionsfillerlibrarysections'
    )

    settings.setLoaded()


def canUpdateMetadataOnProvider(handle, _):
    """NOT IMPLEMENTED"""
    xbmcmediaimport.setCanUpdateMetadataOnProvider(handle, False)


def canUpdatePlaycountOnProvider(handle, _):
    """NOT IMPLEMENTED"""
    xbmcmediaimport.setCanUpdatePlaycountOnProvider(handle, True)


def canUpdateLastPlayedOnProvider(handle, _):
    """NOT IMPLEMENTED"""
    xbmcmediaimport.setCanUpdateLastPlayedOnProvider(handle, False)


def canUpdateResumePositionOnProvider(handle, _):
    """NOT IMPLEMENTED"""
    xbmcmediaimport.setCanUpdateResumePositionOnProvider(handle, False)


def execImport(handle: int, options: dict):
    """Perform library update/import of all configured items from a configured PMS into Kodi

    :param handle: Handle id from input
    :type handle: int
    :param options: Options/parameters passed in with the call, required mediatypes or mediatypes[]
    :type options: dict
    """
    # parse all necessary options
    mediaTypes = mediaTypesFromOptions(options)
    if not mediaTypes:
        log("cannot execute 'import' without media types", xbmc.LOGERROR)
        return

    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log("cannot retrieve media import", xbmc.LOGERROR)
        return

    # prepare and get the media import settings
    importSettings = mediaImport.prepareSettings()
    if not importSettings:
        log("cannot prepare media import settings", xbmc.LOGERROR)
        return

    # retrieve the media provider
    mediaProvider = mediaImport.getProvider()
    if not mediaProvider:
        log("cannot retrieve media provider", xbmc.LOGERROR)
        return

    # prepare and get the media provider settings
    providerSettings = mediaProvider.prepareSettings()
    if not providerSettings:
        log("cannot prepare provider settings", xbmc.LOGERROR)
        return

    # get direct play settings from provider
    allowDirectPlay = providerSettings.getBool(SETTINGS_PROVIDER_PLAYBACK_ALLOW_DIRECT_PLAY)

    # create a Plex Media Server instance
    server = Server(mediaProvider)
    plexServer = server.PlexServer()
    plexLibrary = plexServer.library

    # get all (matching) library sections
    selectedLibrarySections = getLibrarySectionsFromSettings(importSettings)
    librarySections = getMatchingLibrarySections(plexServer, mediaTypes, selectedLibrarySections)
    if not librarySections:
        log(f"cannot retrieve {mediaTypes} items without any library section", xbmc.LOGERROR)
        return

    numDownloadThreads = ImportSettings.GetNumberOfDownloadThreads(importSettings)
    numRetriesOnTimeout = ImportSettings.GetNumberOfRetriesOnTimeout(importSettings)
    numSecondsBetweenRetries = ImportSettings.GetNumberOfSecondsBetweenRetries(importSettings)

    # Decide if doing fast sync or not, if so set filter string to include updatedAt
    fastSync = True
    lastSync = mediaImport.getLastSynced()

    # Check if import settings have changed, or if this is the first time we are importing this library type
    if not lastSync:
        fastSync = False
        SynchronizationSettings.CalculateHash(
            importSettings=importSettings,
            providerSettings=providerSettings,
            save=True
        )
        log("first time syncronizing library, forcing a full syncronization", xbmc.LOGINFO)
    elif SynchronizationSettings.HaveChanged(
            importSettings=importSettings,
            providerSettings=providerSettings,
            save=True
    ):
        fastSync = False
        log("library import settings have changed, forcing a full syncronization", xbmc.LOGINFO)

    if SynchronizationSettings.HaveChanged(importSettings=importSettings, providerSettings=providerSettings, save=True):
        fastSync = False
        log("library import settings have changed, forcing a full syncronization", xbmc.LOGINFO)

    if fastSync:
        log(f"performing fast syncronization of items viewed or updated since {str(lastSync)}")

    # loop over all media types to be imported
    progressTotal = len(mediaTypes)
    for progress, mediaType in enumerate(mediaTypes):
        if xbmcmediaimport.shouldCancel(handle, progress, progressTotal):
            return

        mappedMediaType = Api.getPlexMediaType(mediaType)
        if not mappedMediaType:
            log(f"cannot import unsupported media type '{mediaType}'", xbmc.LOGERROR)
            continue

        plexLibType = mappedMediaType['libtype']
        localizedMediaType = localize(mappedMediaType['label']).decode()

        # prepare and start the converter threads
        converterThreads = []
        for _ in range(0, numDownloadThreads):
            converterThreads.append(ToFileItemConverterThread(mediaProvider, mediaImport, plexServer,
                media_type=mediaType, plex_lib_type=plexLibType, allow_direct_play=allowDirectPlay))
        log((
            f"starting {len(converterThreads)} threads to import {mediaType} items "
            f"from {mediaProvider2str(mediaProvider)}..."),
            xbmc.LOGDEBUG)
        for converterThread in converterThreads:
            converterThread.start()

        # prepare function to stop all converter threads
        def stopConverterThreads(converterThreads):
            log((
                f"stopping {len(converterThreads)} threads importing {mediaType} items "
                f"from {mediaProvider2str(mediaProvider)}..."),
                xbmc.LOGDEBUG)
            for converterThread in converterThreads:
                converterThread.stop()

        xbmcmediaimport.setProgressStatus(handle, localize(32001, localizedMediaType))

        log(f"importing {mediaType} items from {mediaProvider2str(mediaProvider)}", xbmc.LOGINFO)

        # handle library sections
        sectionsProgressTotal = len(librarySections)
        for sectionsProgress, librarySection in enumerate(librarySections):
            if xbmcmediaimport.shouldCancel(handle, sectionsProgress, sectionsProgressTotal):
                stopConverterThreads(converterThreads)
                return

            # get the library section from the Plex Media Server
            section = plexLibrary.sectionByID(librarySection['key'])
            if not section:
                log(f"cannot import {mediaType} items from unknown library section {librarySection}", xbmc.LOGWARNING)
                continue

            # get all matching items from the library section and turn them into ListItems
            sectionRetrievalProgress = 0
            sectionConversionProgress = 0
            sectionProgressTotal = ITEM_REQUEST_LIMIT

            while sectionRetrievalProgress < sectionProgressTotal:
                if xbmcmediaimport.shouldCancel(handle, sectionConversionProgress, sectionProgressTotal):
                    stopConverterThreads(converterThreads)
                    return

                maxResults = min(ITEM_REQUEST_LIMIT, sectionProgressTotal - sectionRetrievalProgress)

                retries = numRetriesOnTimeout
                while retries > 0:
                    try:
                        if fastSync:
                            lastSyncDatetime = parser.parse(lastSync).astimezone(timezone.utc)
                            prefix = ''
                            if mediaType in (xbmcmediaimport.MediaTypeTvShow, xbmcmediaimport.MediaTypeEpisode):
                                prefix = Api.getPlexMediaType(mediaType)['libtype'] + '.'
                            elif mediaType == xbmcmediaimport.MediaTypeSeason:
                                prefix = Api.getPlexMediaType(xbmcmediaimport.MediaTypeEpisode)['libtype'] + '.'

                            updatedFilter = {prefix + 'updatedAt>>': lastSyncDatetime}
                            watchedFilter = {prefix + 'lastViewedAt>>': lastSyncDatetime}

                            updatedPlexItems = section.search(
                                libtype=plexLibType,
                                container_start=sectionRetrievalProgress,
                                container_size=maxResults,
                                maxresults=maxResults,
                                filters=updatedFilter
                            )
                            log(f"discovered {len(updatedPlexItems)} updated {mediaType} items from {mediaProvider2str(mediaProvider)}")
                            watchedPlexItems = section.search(
                                libtype=plexLibType,
                                container_start=sectionRetrievalProgress,
                                container_size=maxResults,
                                maxresults=maxResults,
                                filters=watchedFilter
                            )
                            log(f"discovered {len(watchedPlexItems)} newly watched {mediaType} items from {mediaProvider2str(mediaProvider)}")

                            plexItems = updatedPlexItems
                            plexItems.extend(
                                [item for item in watchedPlexItems if item.key not in [item.key for item in plexItems]]
                            )

                        else:
                            plexItems = section.search(
                                libtype=plexLibType,
                                container_start=sectionRetrievalProgress,
                                container_size=maxResults,
                                maxresults=maxResults,
                            )

                        # get out of the retry loop
                        break
                    except Exception as e:
                        log(f"failed to fetch {mediaType} items from {mediaProvider2str(mediaProvider)}: {e}", xbmc.LOGWARNING)

                        # retry after timeout
                        retries -= 1

                        # check if there are any more retries left
                        # if not abort the import process
                        if retries == 0:
                            log(
                                (
                                    f"fetching {mediaType} items from {mediaProvider2str(mediaProvider)} failed "
                                    f"after {numRetriesOnTimeout} retries"
                                ),
                                xbmc.LOGWARNING)
                            stopConverterThreads(converterThreads)
                            return
                        else:
                            # otherwise wait before trying again
                            log(
                                (
                                    f"retrying to fetch {mediaType} items from {mediaProvider2str(mediaProvider)} in "
                                    f"{numSecondsBetweenRetries} seconds"
                                )
                            )
                            time.sleep(float(numSecondsBetweenRetries))

                # Update sectionProgressTotal now that search has run and totalSize has been updated
                # TODO(Montellese): fix access of private LibrarySection._totalViewSize
                sectionProgressTotal = section._totalViewSize

                # nothing to do if no items have been retrieved from Plex
                if not plexItems:
                    continue

                # automatically determine how to distribute the retrieved items across the available converter threads
                plexItemsPerConverter, remainingPlexItems = divmod(len(plexItems), len(converterThreads))
                plexItemsPerConverters = [plexItemsPerConverter] * len(converterThreads)
                plexItemsPerConverters[0:remainingPlexItems] = [plexItemsPerConverter + 1] * remainingPlexItems
                converterThreadIndex = 0

                splitItems = []
                for plexItem in plexItems:
                    if xbmcmediaimport.shouldCancel(handle, sectionConversionProgress, sectionProgressTotal):
                        stopConverterThreads(converterThreads)
                        return

                    sectionRetrievalProgress += 1

                    # copllect the plex items for the next converter thread
                    splitItems.append(plexItem)
                    plexItemsPerConverters[converterThreadIndex] -= 1

                    # move to the next converter thread if necessary
                    if not plexItemsPerConverters[converterThreadIndex]:
                        converterThreads[converterThreadIndex].add_items_to_convert(splitItems)
                        splitItems.clear()

                        converterThreadIndex += 1

                    # retrieve and combine the progress of all converter threads
                    sectionConversionProgress = \
                        sum(converterThread.get_converted_items_count() for converterThread in converterThreads)

                if splitItems:
                    log(f"forgot to process {len(splitItems)} {mediaType} items", xbmc.LOGWARNING)

        # retrieve converted items from the converter threads
        totalItemsToImport = 0
        countFinishedConverterThreads = 0
        while countFinishedConverterThreads < len(converterThreads):
            if xbmcmediaimport.shouldCancel(handle, sectionConversionProgress, sectionProgressTotal):
                stopConverterThreads(converterThreads)
                return

            sectionConversionProgress = 0
            itemsToImport = []
            for converterThread in converterThreads:
                # update the progress
                sectionConversionProgress += converterThread.get_converted_items_count()

                # ignore finished converter threads
                if converterThread.should_finish():
                    continue

                # retrieve the converted items
                convertedItems = converterThread.get_converted_items()
                itemsToImport.extend(convertedItems)

                # check if all items have been converted
                if not converterThread.get_items_to_convert_count():
                    converterThread.finish()
                    countFinishedConverterThreads += 1

            if itemsToImport:
                totalItemsToImport += len(itemsToImport)
                xbmcmediaimport.addImportItems(handle, itemsToImport, mediaType)

            time.sleep(0.1)

        if totalItemsToImport:
            log(f"{totalItemsToImport} {mediaType} items imported from {mediaProvider2str(mediaProvider)}", xbmc.LOGINFO)

    xbmcmediaimport.finishImport(handle, fastSync)


def updateOnProvider(handle: int, _options: dict):
    """Perform update/export of library items from Kodi into conifigured PMS (watch status, resume points, etc.)

    :param handle: Handle id from input
    :type handle: int
    :param _options: Options/parameters passed in with the call, Unused
    :type _options: dict
    """
    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log("cannot retrieve media import", xbmc.LOGERROR)
        return

    # retrieve the media provider
    mediaProvider = mediaImport.getProvider()
    if not mediaProvider:
        log("cannot retrieve media provider", xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log("cannot prepare media provider settings", xbmc.LOGERROR)
        return

    # prepare and get the media import settings
    importSettings = mediaImport.prepareSettings()
    if not importSettings:
        log("cannot prepare media import settings", xbmc.LOGERROR)
        return

    item = xbmcmediaimport.getUpdatedItem(handle)
    if not item:
        log("cannot retrieve updated item", xbmc.LOGERROR)
        return

    itemVideoInfoTag = item.getVideoInfoTag()
    if not itemVideoInfoTag:
        log("updated item is not a video item", xbmc.LOGERROR)
        return

    # determine the item's identifier / ratingKey
    itemId = Api.getItemIdFromVideoInfoTag(itemVideoInfoTag)
    if not itemId:
        log(f"cannot determine the identifier of the updated item: {itemVideoInfoTag.getPath()}", xbmc.LOGERROR)
        return

    # create a Plex server instance
    server = Server(mediaProvider)
    if not server.Authenticate():
        log(f"failed to connect to Plex Media Server for {mediaProvider2str(mediaProvider)}", xbmc.LOGWARNING)
        return

    plexItem = Api.getPlexItemDetails(
        server.PlexServer(),
        itemId,
        Api.getPlexMediaClassFromMediaType(itemVideoInfoTag.getMediaType())
    )
    if not plexItem:
        log(f"cannot retrieve details of updated item {itemVideoInfoTag.getPath()} with id {itemId}", xbmc.LOGERROR)
        return

    # check / update watched state
    playcount = itemVideoInfoTag.getPlayCount()
    watched = playcount > 0
    if watched != plexItem.isWatched:
        if watched:
            plexItem.markWatched()
        else:
            plexItem.markUnwatched()

    # TODO(Montellese): check / update last played
    # TODO(Montellese): check / update resume point

    xbmcmediaimport.finishUpdateOnProvider(handle)


ACTIONS = {
    # official media import callbacks
    'discoverprovider': discoverProvider,
    'lookupprovider': lookupProvider,
    'canimport': canImport,
    'isproviderready': isProviderReady,
    'isimportready': isImportReady,
    'loadprovidersettings': loadProviderSettings,
    'loadimportsettings': loadImportSettings,
    'canupdatemetadataonprovider': canUpdateMetadataOnProvider,
    'canupdateplaycountonprovider': canUpdatePlaycountOnProvider,
    'canupdatelastplayedonprovider': canUpdateLastPlayedOnProvider,
    'canupdateresumepositiononprovider': canUpdateResumePositionOnProvider,
    'import': execImport,
    'updateonprovider': updateOnProvider,

    # custom setting callbacks
    'linkmyplexaccount': linkMyPlexAccount,
    'testconnection': testConnection,
    'forcesync': forceSync,
    'changeurl': changeUrl,

    # custom setting options fillers
    'settingoptionsfillerlibrarysections': settingOptionsFillerLibrarySections
}


def run(argv: list):
    """Function runner: Reads call type from input args and calls associated function

    :param argv: Input arguments, <path> <handle> <options>
    :type argv: list
    """
    path = argv[0]
    handle = int(argv[1])

    options = {}
    if len(argv) > 2:
        # get the options but remove the leading ?
        params = argv[2][1:]
        if params:
            options = parse_qs(params)

    log(f"path = {path}, handle = {handle}, options = {options}", xbmc.LOGDEBUG)

    url = urlparse(path)
    action = url.path
    if action[0] == '/':
        action = action[1:]

    if action not in ACTIONS:
        log(f"cannot process unknown action: {action}", xbmc.LOGERROR)
        sys.exit(0)

    actionMethod = ACTIONS[action]
    if not actionMethod:
        log(f"action not implemented: {action}", xbmc.LOGWARNING)
        sys.exit(0)

    # initialize some global variables
    plex.Initialize()

    log(f"executing action '{action}'...", xbmc.LOGDEBUG)
    actionMethod(handle, options)
