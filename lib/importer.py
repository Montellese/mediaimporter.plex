#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import sys
from six.moves.urllib.parse import parse_qs, unquote, urlparse

import xbmc
import xbmcgui
import xbmcmediaimport

from plexapi.myplex import MyPlexAccount, MyPlexPinLogin
from plexapi.server import PlexServer

from lib.utils import localise, log, mediaProvider2str
import plex
from plex.api import Api
from plex.server import Server

# general constants
ITEM_REQUEST_LIMIT = 100

def mediaTypesFromOptions(options):
    if not 'mediatypes' in options and not 'mediatypes[]' in options:
        return None

    if 'mediatypes' in options:
        mediaTypes = options['mediatypes']
    elif 'mediatypes[]' in options:
        mediaTypes = options['mediatypes[]']
    else:
        mediaTypes = None

    return mediaTypes

def getServerId(path):
    if not path:
        return False

    url = urlparse(path)
    if url.scheme != plex.constants.PLEX_PROTOCOL or not url.netloc:
        return False

    return url.netloc

def getLibrarySections(plexServer, mediaTypes):
    if not plexServer:
        raise ValueError('invalid plexServer')
    if not mediaTypes:
        raise ValueError('invlaid mediaTypes')

    # get all library sections
    librarySections = []
    for section in  plexServer.library.sections():
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

def getLibrarySectionsFromSettings(importSettings):
    if not importSettings:
        raise ValueError('invalid importSettings')

    return importSettings.getStringList(plex.constants.SETTINGS_IMPORT_LIBRARY_SECTIONS)

def getMatchingLibrarySections(plexServer, mediaTypes, selectedLibrarySections):
    if not plexServer:
        raise ValueError('invalid plexServer')
    if not mediaTypes:
        raise ValueError('invalid mediaTypes')

    if not selectedLibrarySections:
        return []

    librarySections = getLibrarySections(plexServer, mediaTypes)

    return [ librarySection for librarySection in librarySections if librarySection['key'] in selectedLibrarySections ]

def dicsoverProviderLocally(handle, options):
    dialog = xbmcgui.Dialog()

    baseUrl = dialog.input(localise(32051))
    if not baseUrl:
        return None

    plexServer = PlexServer(baseUrl, timeout=plex.constants.REQUEST_TIMEOUT)
    if not plexServer:
        return None

    providerId = Server.BuildProviderId(plexServer.machineIdentifier)
    providerIconUrl = Server.BuildIconUrl(baseUrl)

    provider = xbmcmediaimport.MediaProvider(providerId,baseUrl, plexServer.friendlyName, providerIconUrl, plex.constants.SUPPORTED_MEDIA_TYPES, handle=handle)

    # store local authentication in settings
    providerSettings = provider.prepareSettings()
    if not providerSettings:
        return None

    providerSettings.setInt(plex.constants.SETTINGS_PROVIDER_AUTHENTICATION, plex.constants.SETTINGS_PROVIDER_AUTHENTICATION_OPTION_LOCAL)
    providerSettings.save()

    return provider

def linkToMyPlexAccount():
    dialog = xbmcgui.Dialog()

    pinLogin = MyPlexPinLogin()
    if not pinLogin.pin:
        dialog.ok(localise(32015), localise(32052))
        log('failed to get PIN to link MyPlex account', xbmc.LOGWARNING)
        return None

    # show the user the pin
    dialog.ok(localise(32015), localise(32053), '[COLOR FFE5A00D]{}[/COLOR]'.format(pinLogin.pin))

    # check the status of the authentication
    while not pinLogin.finished:
        if pinLogin.checkLogin():
            break

    if pinLogin.expired:
        dialog.ok(localise(32015), localise(32054))
        log('linking the MyPlex account has expiried', xbmc.LOGWARNING)
        return None

    if not pinLogin.token:
        log('no valid token received from the linked MyPlex account', xbmc.LOGWARNING)
        return None

    # login to MyPlex
    try:
        plexAccount = MyPlexAccount(token=pinLogin.token, timeout=plex.constants.REQUEST_TIMEOUT)
    except Exception as e:
        log('failed to connect to the linked MyPlex account: {}'.format(e), xbmc.LOGWARNING)
        return None
    if not plexAccount:
        log('failed to connect to the linked MyPlex account', xbmc.LOGWARNING)
        return None

    return plexAccount

def getServerResources(plexAccount):
    if not plexAccount:
        raise ValueError('invalid plexAccount')

    # get all connected resources
    resources = plexAccount.resources()
    if not resources:
        return []

    # we are only interested in Plex Media Server resources
    return [ resource for resource in resources if resource.product == 'Plex Media Server' and 'server' in resource.provides ]

def linkMyPlexAccount(handle, options):
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
    serverUrl = mediaProvider.getBasePath()
    matchingServer = None

    serverId = getServerId(mediaProvider.getIdentifier())

    # get all connected server resources
    serverResources = getServerResources(plexAccount)
    for server in serverResources:
        if server.clientIdentifier == serverId:
            matchingServer = server
            break

    if not matchingServer:
        log('no Plex Media Server matching {} found'.format(serverUrl), xbmc.LOGWARNING)
        xbmcgui.Dialog().ok(localise(32015), localise(32058))
        return

    xbmcgui.Dialog().ok(localise(32015), localise(32059).format(username))

    # change the settings
    providerSettings.setString(plex.constants.SETTINGS_PROVIDER_USERNAME, username)
    providerSettings.setString(plex.constants.SETTINGS_PROVIDER_TOKEN, matchingServer.accessToken)

def testConnection(handle, options):
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
    xbmcgui.Dialog().ok(title, localise(line))

def dicsoverProviderWithMyPlex(handle, options):
    plexAccount = linkToMyPlexAccount()
    if not plexAccount:
        return None

    username = plexAccount.username
    if not username:
        log('no valid username available for the linked MyPlex account', xbmc.LOGWARNING)
        return None

    dialog = xbmcgui.Dialog()

    # get all connected server resources
    serverResources = getServerResources(plexAccount)
    if not serverResources:
        log('no servers available for MyPlex account {}'.format(username), xbmc.LOGWARNING)
        return None

    if len(serverResources) == 1:
        server = serverResources[0]
    else:
        # ask the user which server to use
        servers = [ resource.name for resource in serverResources ]
        serversChoice = dialog.select(localise(32055), servers)
        if serversChoice < 0 or serversChoice >= len(servers):
            return None

        server = serverResources[serversChoice]

    if not server:
        return None

    if not server.connections:
        # try to connect to the server
        plexServer = server.connect(timeout=plex.constants.REQUEST_TIMEOUT)
        if not plexServer:
            log('failed to connect to the Plex Media Server "{}"'.format(server.name), xbmc.LOGWARNING)
            return None

        baseUrl = plexServer.url('', includeToken=False)
    else:
        isLocal = False
        localConnections = [ connection for connection in server.connections if connection.local ]
        remoteConnections = [ connection for connection in server.connections if not connection.local and not connection.relay ]
        remoteRelayConnections = [ connection for connection in server.connections if not connection.local and connection.relay ]

        if localConnections:
            # ask the user whether to use a local or remote connection
            isLocal = dialog.yesno(localise(32056), localise(32057).format(server.name))

        if isLocal:
            baseUrl = localConnections[0].httpuri
        elif remoteConnections:
            baseUrl = remoteConnections[0].uri
        elif remoteRelayConnections:
            baseUrl = remoteRelayConnections[0].uri
        else:
            baseUrl = localConnections[0].uri

        # try to connect to the server
        try:
            plexServer = PlexServer(baseurl=baseUrl, token=server.accessToken, timeout=plex.constants.REQUEST_TIMEOUT)
        except:
            dialog.ok(localise(32056), localise(32060).format(server.name, baseUrl))
            return None

    if not baseUrl:
        log('failed to determine the URL to access the Plex Media Server "{}" for MyPlex account {}'.format(plexServer.friendlyName, username), xbmc.LOGWARNING)
        return None

    providerId = plex.server.Server.BuildProviderId(server.clientIdentifier)
    providerIconUrl = plex.server.Server.BuildIconUrl(baseUrl)
    provider = xbmcmediaimport.MediaProvider(providerId, baseUrl, server.name, providerIconUrl, plex.constants.SUPPORTED_MEDIA_TYPES, handle=handle)

    # store MyPlex account details and token in settings
    providerSettings = provider.prepareSettings()
    if not providerSettings:
        return None

    providerSettings.setInt(plex.constants.SETTINGS_PROVIDER_AUTHENTICATION, plex.constants.SETTINGS_PROVIDER_AUTHENTICATION_OPTION_MYPLEX)
    providerSettings.setString(plex.constants.SETTINGS_PROVIDER_USERNAME, username)
    providerSettings.setString(plex.constants.SETTINGS_PROVIDER_TOKEN, server.accessToken)
    providerSettings.save()

    return provider

def discoverProvider(handle, options):
    dialog = xbmcgui.Dialog()

    authenticationChoices = [
        localise(32013),  # local only
        localise(32014)   # MyPlex
    ]
    authenticationChoice = dialog.select(localise(32050), authenticationChoices)

    if authenticationChoice == 0:  # local only
        provider = dicsoverProviderLocally(handle, options)
    elif authenticationChoice == 1:  # MyPlex
        provider = dicsoverProviderWithMyPlex(handle, options)
    else:
        return

    if not provider:
        return

    xbmcmediaimport.setDiscoveredProvider(handle, True, provider)

def lookupProvider(handle, options):
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('cannot prepare media provider settings', xbmc.LOGERROR)
        return

    providerFound = False
    try:
        providerFound = Server(mediaProvider).Authenticate()
    except:
        pass

    xbmcmediaimport.setProviderFound(handle, providerFound)

def canImport(handle, options):
    if not 'path' in options:
        log('cannot execute "canimport" without path')
        return

    path = unquote(options['path'][0])

    # try to get the Plex Media Server's identifier from the path
    id = getServerId(path)
    if not id:
      return

    xbmcmediaimport.setCanImport(handle, True)

def isProviderReady(handle, options):
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('cannot prepare media provider settings', xbmc.LOGERROR)
        return

    # check if authentication works with the current provider settings
    providerReady = False
    try:
        providerReady = Server(mediaProvider).Authenticate()
    except:
        pass

    xbmcmediaimport.setProviderReady(handle, providerReady)

def isImportReady(handle, options):
    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return
    # prepare and get the media import settings
    importSettings = mediaImport.prepareSettings()
    if not importSettings:
        log('cannot prepare media import settings', xbmc.LOGERROR)
        return

    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('cannot prepare media provider settings', xbmc.LOGERROR)
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
        matchingLibrarySections = getMatchingLibrarySections(server.PlexServer(), mediaImport.getMediaTypes(), selectedLibrarySections)
        importReady = len(matchingLibrarySections) > 0

    xbmcmediaimport.setImportReady(handle, importReady)

def loadProviderSettings(handle, options):
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    settings = mediaProvider.getSettings()
    if not settings:
        log('cannot retrieve media provider settings', xbmc.LOGERROR)
        return

    settings.registerActionCallback(plex.constants.SETTINGS_PROVIDER_LINK_MYPLEX_ACCOUNT, 'linkmyplexaccount')
    settings.registerActionCallback(plex.constants.SETTINGS_PROVIDER_TEST_CONNECTION, 'testconnection')

    settings.setLoaded()

def settingOptionsFillerLibrarySections(handle, options):
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
        log('failed to connect to Plex Media Server for {}'.format(mediaProvider2str(mediaProvider)), xbmc.LOGWARNING)
        return

    plexServer = server.PlexServer()

    # get all library sections
    mediaTypes = mediaImport.getMediaTypes()
    librarySections = getLibrarySections(plexServer, mediaTypes)
    sections = [ (section['title'], section['key']) for section in librarySections ]

    # get the import's settings
    settings = mediaImport.getSettings()

    # pass the list of views back to Kodi
    settings.setStringOptions(plex.constants.SETTINGS_IMPORT_LIBRARY_SECTIONS, sections)

def loadImportSettings(handle, options):
    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return

    settings = mediaImport.getSettings()
    if not settings:
        log('cannot retrieve media import settings', xbmc.LOGERROR)
        return

     # register a setting options filler for the list of views
    settings.registerOptionsFillerCallback(plex.constants.SETTINGS_IMPORT_LIBRARY_SECTIONS, 'settingoptionsfillerlibrarysections')

    settings.setLoaded()

def canUpdateMetadataOnProvider(handle, options):
    # TODO(Montellese)
    xbmcmediaimport.setCanUpdateMetadataOnProvider(False)

def canUpdatePlaycountOnProvider(handle, options):
    xbmcmediaimport.setCanUpdatePlaycountOnProvider(True)

def canUpdateLastPlayedOnProvider(handle, options):
    # TODO(Montellese)
    xbmcmediaimport.setCanUpdateLastPlayedOnProvider(False)

def canUpdateResumePositionOnProvider(handle, options):
    # TODO(Montellese)
    xbmcmediaimport.setCanUpdateResumePositionOnProvider(False)

def execImport(handle, options):
    if not 'path' in options:
        log('cannot execute "import" without path', xbmc.LOGERROR)
        return

    # parse all necessary options
    mediaTypes = mediaTypesFromOptions(options)
    if not mediaTypes:
        log('cannot execute "import" without media types', xbmc.LOGERROR)
        return

    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return

    # prepare and get the media import settings
    importSettings = mediaImport.prepareSettings()
    if not importSettings:
        log('cannot prepare media import settings', xbmc.LOGERROR)
        return

    # retrieve the media provider
    mediaProvider = mediaImport.getProvider()
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('cannot prepare media provider settings', xbmc.LOGERROR)
        return

    # create a Plex Media Server instance
    server = Server(mediaProvider)
    plexServer = server.PlexServer()
    plexLibrary = plexServer.library

    # get all (matching) library sections
    selectedLibrarySections = getLibrarySectionsFromSettings(importSettings)
    librarySections = getMatchingLibrarySections(plexServer, mediaTypes, selectedLibrarySections)
    if not librarySections:
        log('cannot retrieve {} items without any library section'.format(mediaTypes), xbmc.LOGERROR)
        return

    # loop over all media types to be imported
    progressTotal = len(mediaTypes)
    for progress, mediaType in enumerate(mediaTypes):
        if xbmcmediaimport.shouldCancel(handle, progress, progressTotal):
            return

        mappedMediaType = Api.getPlexMediaType(mediaType)
        if not mappedMediaType:
            log('cannot import unsupported media type "{}"'.format(mediaType), xbmc.LOGERROR)
            continue

        plexLibType = mappedMediaType['libtype']
        localizedMediaType = localise(mappedMediaType['label'])

        xbmcmediaimport.setProgressStatus(handle, localise(32001).format(localizedMediaType))

        log('importing {} items from {}'.format(mediaType, mediaProvider2str(mediaProvider)))

        # handle library sections
        plexItems = []
        sectionsProgressTotal = len(librarySections)
        for sectionsProgress, librarySection in enumerate(librarySections):
            if xbmcmediaimport.shouldCancel(handle, sectionsProgress, sectionsProgressTotal):
                return

            # get the library section from the Plex Media Server
            section = plexLibrary.sectionByID(librarySection['key'])
            if not section:
                log('cannot import {} items from unknown library section {}'.format(mediaType, librarySection), xbmc.LOGWARNING)
                continue

            # get all matching items from the library section
            plexSectionItems = section.search(libtype=plexLibType)
            plexItems.extend(plexSectionItems)

        # parse all items
        items = []
        itemsProgressTotal = len(plexItems)
        for itemsProgress, plexItem in enumerate(plexItems):
            if xbmcmediaimport.shouldCancel(handle, itemsProgress, itemsProgressTotal):
                return

            item = Api.toFileItem(plexItem, mediaType, plexLibType)
            if not item:
                continue

            items.append(item)

        if items:
            log('{} {} items imported from {}'.format(len(items), mediaType, mediaProvider2str(mediaProvider)))
            xbmcmediaimport.addImportItems(handle, items, mediaType)

    xbmcmediaimport.finishImport(handle)

def updateOnProvider(handle, options):
    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return

    # retrieve the media provider
    mediaProvider = mediaImport.getProvider()
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('cannot prepare media provider settings', xbmc.LOGERROR)
        return

    # prepare and get the media import settings
    importSettings = mediaImport.prepareSettings()
    if not importSettings:
        log('cannot prepare media import settings', xbmc.LOGERROR)
        return

    item = xbmcmediaimport.GetUpdatedItem(handle)
    if not item:
        log('cannot retrieve updated item', xbmc.LOGERROR)
        return

    itemVideoInfoTag = item.getVideoInfoTag()
    if not itemVideoInfoTag:
        log('updated item is not a video item', xbmc.LOGERROR)
        return

    # determine the item's identifier / ratingKey
    itemId = Api.getItemIdFromListItem(item)
    if not itemId:
        log('cannot determine the identifier of the updated item: {}'.format(itemVideoInfoTag.getPath()), xbmc.LOGERROR)
        return

    # create a Plex server instance
    server = Server(mediaProvider)
    if not server.Authenticate():
        log('failed to connect to Plex Media Server for {}'.format(mediaProvider2str(mediaProvider)), xbmc.LOGWARNING)
        return

    plexItem = Api.getPlexItemDetails(server.PlexServer(), itemId, Api.getPlexMediaClassFromMediaType(itemVideoInfoTag.getMediaType()))
    if not plexItem:
        log('cannot retrieve details of updated item {} with id {}'.format(itemVideoInfoTag.getPath(), itemId), xbmc.LOGERROR)
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

    # custom setting options fillers
    'settingoptionsfillerlibrarysections': settingOptionsFillerLibrarySections
}

def run(argv):
    path = argv[0]
    handle = int(argv[1])

    options = None
    if len(argv) > 2:
        # get the options but remove the leading ?
        params = argv[2][1:]
        if params:
            options = parse_qs(params)

    log('path = {}, handle = {}, options = {}'.format(path, handle, params), xbmc.LOGDEBUG)

    url = urlparse(path)
    action = url.path
    if action[0] == '/':
        action = action[1:]

    if not action in ACTIONS:
        log('cannot process unknown action: {}'.format(action), xbmc.LOGERROR)
        sys.exit(0)

    actionMethod = ACTIONS[action]
    if not actionMethod:
        log('action not implemented: {}'.format(action), xbmc.LOGWARNING)
        sys.exit(0)

    # initialize some global variables
    plex.Initialize()

    log('executing action "{}"...'.format(action), xbmc.LOGDEBUG)
    actionMethod(handle, options)
