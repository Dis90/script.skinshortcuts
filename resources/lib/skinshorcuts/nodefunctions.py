# -*- coding: utf-8 -*-
"""
    Copyright (C) 2013-2021 Skin Shortcuts (script.skinshortcuts)
    This file is part of script.skinshortcuts
    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only.txt for more information.
"""
import os
import re
import xml.etree.ElementTree as ETree
# noinspection PyCompatibility
from html.entities import name2codepoint
from traceback import print_exc

import xbmc
import xbmcgui
import xbmcvfs
from .common import log
from .common import rpc_request
from .constants import ADDON
from .constants import CWD
from .constants import DATA_PATH
from .constants import HOME_WINDOW
from .constants import KODI_PATH
from .constants import LANGUAGE
from .constants import PROFILE_PATH
from .property_utils import write_properties

# character entity reference
CHAR_ENTITY_REXP = re.compile(r'&(%s);' % '|'.join(name2codepoint))

# decimal character reference
DECIMAL_REXP = re.compile(r'&#(\d+);')

# hexadecimal character reference
HEX_REXP = re.compile(r'&#x([\da-fA-F]+);')

REPLACE1_REXP = re.compile(r'[\']+')
REPLACE2_REXP = re.compile(r'[^-a-z0-9]+')
REMOVE_REXP = re.compile(r'-{2,}')


class NodeFunctions:
    def __init__(self):
        self.indexCounter = 0

    ##############################################
    # Functions used by library.py to list nodes #
    ##############################################

    def get_nodes(self, path, prefix):
        dirs, files = xbmcvfs.listdir(path)
        nodes = {}

        try:
            for _dir in dirs:
                self.parse_node(os.path.join(path, _dir), _dir, nodes, prefix)
            for file in files:
                self.parse_view(os.path.join(path, file), nodes,
                                origPath="%s/%s" % (prefix, file))
        except:
            print_exc()
            return False

        return nodes

    def parse_node(self, node, directory, nodes, prefix):
        # If the folder we've been passed contains an index.xml, send that file to be processed
        if xbmcvfs.exists(os.path.join(node, "index.xml")):
            self.parse_view(os.path.join(node, "index.xml"), nodes, True,
                            "%s/%s/" % (prefix, directory), node)

    def parse_view(self, file, nodes, isFolder=False, origFolder=None, origPath=None):
        if not isFolder and file.endswith("index.xml"):
            return
        try:
            # Load the xml file
            tree = ETree.parse(file)
            root = tree.getroot()

            # Get the item index
            if "order" in root.attrib:
                index = root.attrib.get("order")
                origIndex = index
                while int(index) in nodes:
                    index = int(index)
                    index += 1
                    index = str(index)
            else:
                self.indexCounter -= 1
                index = str(self.indexCounter)
                origIndex = "-"

            # Try to get media type from visibility condition
            mediaType = None
            if "visible" in root.attrib:
                visibleAttrib = root.attrib.get("visible")
                if not xbmc.getCondVisibility(visibleAttrib):
                    # The node isn't visible
                    return
                if "Library.HasContent(" in visibleAttrib and "+" not in visibleAttrib and \
                        "|" not in visibleAttrib:
                    mediaType = visibleAttrib.split("(")[1].split(")")[0].lower()

            # Try to get media type from content node
            contentNode = root.find("content")
            if contentNode is not None:
                mediaType = contentNode.text

            # Get label and icon
            label = root.find("label").text
            icon = root.find("icon")
            if icon is not None:
                icon = icon.text
            else:
                icon = ""

            if isFolder:
                # Add it to our list of nodes
                nodes[int(index)] = [label, icon, origFolder, "folder", origIndex, mediaType]
            else:
                # Check for a path
                path = root.find("path")
                if path is not None:
                    # Change the origPath (the url used as the shortcut address) to it
                    origPath = path.text

                # Check for a grouping
                group = root.find("group")
                if group is None:
                    # Add it as an item
                    nodes[int(index)] = [label, icon, origPath, "item", origIndex, mediaType]
                else:
                    # Add it as grouped
                    nodes[int(index)] = [label, icon, origPath, "grouped", origIndex, mediaType]
        except:
            print_exc()

    @staticmethod
    def is_grouped(path):
        customPathVideo = path.replace("library://video",
                                       os.path.join(PROFILE_PATH, "library", "video"))[:-1]
        defaultPathVideo = path.replace("library://video",
                                        os.path.join(KODI_PATH, "system", "library", "video"))[:-1]
        customPathAudio = path.replace("library://music",
                                       os.path.join(PROFILE_PATH, "library", "music"))[:-1]
        defaultPathAudio = path.replace("library://music",
                                        os.path.join(KODI_PATH, "system", "library", "music"))[:-1]

        paths = [customPathVideo, defaultPathVideo, customPathAudio, defaultPathAudio]
        foundPath = False

        for tryPath in paths:
            if xbmcvfs.exists(tryPath):
                path = tryPath
                foundPath = True
                break
        if foundPath is False:
            return False

        # Open the file
        try:
            # Load the xml file
            tree = ETree.parse(path)
            root = tree.getroot()

            group = root.find("group")
            if group is None:
                return False
            else:
                return True
        except:
            return False

    #####################################
    # Function used by DataFunctions.py #
    #####################################

    @staticmethod
    def get_visibility(path):
        path = path.replace("videodb://", "library://video/")
        path = path.replace("musicdb://", "library://music/")
        if path.endswith(".xml"):
            path = path[:-3]
        if path.endswith(".xml/"):
            path = path[:-4]

        if "library://video" in path:
            pathStart = "library://video"
            pathEnd = "video"
        elif "library://music" in path:
            pathStart = "library://music"
            pathEnd = "music"
        else:
            return ""

        customPath = path.replace(pathStart,
                                  os.path.join(PROFILE_PATH, "library", pathEnd)) + "index.xml"
        customFile = path.replace(pathStart,
                                  os.path.join(PROFILE_PATH, "library", pathEnd))[:-1] + ".xml"
        defaultPath = path.replace(
            pathStart,
            os.path.join(KODI_PATH, "system", "library", pathEnd)
        ) + "index.xml"
        defaultFile = path.replace(
            pathStart,
            os.path.join(KODI_PATH, "system", "library", pathEnd)
        )[:-1] + ".xml"

        # Check whether the node exists - either as a parent node (with an index.xml)
        # or a view node (append .xml) in first custom video nodes, then default video nodes
        nodeFile = None
        if xbmcvfs.exists(customPath):
            nodeFile = customPath
        elif xbmcvfs.exists(defaultPath):
            nodeFile = defaultPath
        if xbmcvfs.exists(customFile):
            nodeFile = customFile
        elif xbmcvfs.exists(defaultFile):
            nodeFile = defaultFile

        # Next check if there is a parent node
        if path.endswith("/"):
            path = path[:-1]
        path = path.rsplit("/", 1)[0]
        customPath = path.replace(pathStart,
                                  os.path.join(PROFILE_PATH, "library", pathEnd)) + "/index.xml"
        defaultPath = path.replace(
            pathStart,
            os.path.join(KODI_PATH, "system", "library", pathEnd)
        ) + "/index.xml"
        nodeParent = None

        if xbmcvfs.exists(customPath):
            nodeParent = customPath
        elif xbmcvfs.exists(defaultPath):
            nodeParent = defaultPath

        if not nodeFile and not nodeParent:
            return ""

        for path in (nodeFile, nodeParent):
            if path is None:
                continue
            # Open the file
            try:
                # Load the xml file
                tree = ETree.parse(path)
                root = tree.getroot()

                if "visible" in root.attrib:
                    return root.attrib.get("visible")
            except:
                pass

        return ""

    @staticmethod
    def get_media_type(path):
        path = path.replace("videodb://", "library://video/")
        path = path.replace("musicdb://", "library://music/")
        if path.endswith(".xml"):
            path = path[:-3]
        if path.endswith(".xml/"):
            path = path[:-4]

        if "library://video" in path:
            pathStart = "library://video"
            pathEnd = "video"
        elif "library://music" in path:
            pathStart = "library://music"
            pathEnd = "music"
        else:
            return "unknown"

        customPath = path.replace(pathStart,
                                  os.path.join(PROFILE_PATH, "library", pathEnd)) + "index.xml"
        customFile = path.replace(pathStart,
                                  os.path.join(PROFILE_PATH, "library", pathEnd))[:-1] + ".xml"
        defaultPath = path.replace(
            pathStart,
            os.path.join(KODI_PATH, "system", "library", pathEnd)
        ) + "index.xml"
        defaultFile = path.replace(
            pathStart,
            os.path.join(KODI_PATH, "system", "library", pathEnd)
        )[:-1] + ".xml"

        # Check whether the node exists - either as a parent node (with an index.xml)
        # or a view node (append .xml) in first custom video nodes, then default video nodes
        if xbmcvfs.exists(customPath):
            path = customPath
        elif xbmcvfs.exists(customFile):
            path = customFile
        elif xbmcvfs.exists(defaultPath):
            path = defaultPath
        elif xbmcvfs.exists(defaultFile):
            path = defaultFile
        else:
            return "unknown"

        # Open the file
        try:
            # Load the xml file
            tree = ETree.parse(path)
            root = tree.getroot()

            mediaType = "unknown"
            if "visible" in root.attrib:
                visibleAttrib = root.attrib.get("visible")
                if "Library.HasContent(" in visibleAttrib and "+" not in visibleAttrib and \
                        "|" not in visibleAttrib:
                    mediaType = visibleAttrib.split("(")[1].split(")")[0].lower()

            contentNode = root.find("content")
            if contentNode is not None:
                mediaType = contentNode.text

            return mediaType

        except:
            return "unknown"

    ##################################################
    # Functions to externally add a node to the menu #
    ##################################################

    def add_to_menu(self, path, label, icon, content, window, data_func):
        log(repr(window))
        log(repr(label))
        log(repr(path))
        log(repr(content))
        # Show a waiting dialog
        dialog = xbmcgui.DialogProgress()
        dialog.create(path, LANGUAGE(32063))

        # Work out if it's a single item, or a node
        isNode = False
        jsonPath = path.replace("\\", "\\\\")
        json_payload = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "Files.GetDirectory",
            "params": {
                "properties": ["title", "file", "thumbnail"],
                "directory": "%s" % jsonPath,
                "media": "files"
            }
        }
        json_response = rpc_request(json_payload)

        nodePaths = []

        # Add all directories returned by the json query
        if 'result' in json_response and 'files' in json_response['result'] and \
                json_response['result']['files'] is not None:
            labels = [LANGUAGE(32058)]
            paths = ["ActivateWindow(%s,%s,return)" % (window, path)]
            for item in json_response['result']['files']:
                if item["filetype"] == "directory":
                    isNode = True
                    labels.append(item["label"])
                    nodePaths.append("ActivateWindow(%s,%s,return)" % (window, item["file"]))
        else:
            # Unable to add to get directory listings
            log("Invalid JSON response returned")
            log(repr(json_response))
            # And tell the user it failed
            xbmcgui.Dialog().ok(ADDON.getAddonInfo("name"), ADDON.getLocalizedString(32115))
            return

        # Add actions based on content
        if content == "albums":
            labels.append("Play")
            paths.append("RunScript(script.skinshortcuts,type=launchalbum&album=%s)" %
                         (self.extract_id(path)))
        if window == 10002:
            labels.append("Slideshow")
            paths.append("SlideShow(%s,notrandom)" % path)
            labels.append("Slideshow (random)")
            paths.append("SlideShow(%s,random)" % path)
            labels.append("Slideshow (recursive)")
            paths.append("SlideShow(%s,recursive,notrandom)" % path)
            labels.append("Slideshow (recursive, random)")
            paths.append("SlideShow(%s,recursive,random)" % path)
        if path.endswith(".xsp"):
            labels.append("Play")
            paths.append("PlayMedia(%s)" % path)

        allMenuItems = [xbmcgui.ListItem(label=LANGUAGE(32112))]  # Main menu
        allLabelIDs = ["mainmenu"]
        if isNode:
            allMenuItems.append(
                xbmcgui.ListItem(label=LANGUAGE(32113))  # Main menu + autofill submenu
            )
            allLabelIDs.append("mainmenu")

        # Get main menu items
        menuitems = data_func.get_shortcuts("mainmenu", processShortcuts=False)
        data_func.clear_labelID()
        for menuitem in menuitems.findall("shortcut"):
            # Get existing items labelID's
            listitem = xbmcgui.ListItem(label=data_func.local(menuitem.find("label").text)[2])
            listitem.setArt({
                'icon': menuitem.find("icon").text
            })
            allMenuItems.append(listitem)
            allLabelIDs.append(data_func.get_labelID(
                data_func.local(menuitem.find("label").text)[3], menuitem.find("action").text)
            )

        # Close progress dialog
        dialog.close()

        # Show a select dialog so the user can pick where in the menu to add the item
        w = ShowDialog("DialogSelect.xml", CWD, listing=allMenuItems, windowtitle=LANGUAGE(32114))
        w.doModal()
        selectedMenu = w.result
        del w

        if selectedMenu == -1 or selectedMenu is None:
            # User cancelled
            return

        action = paths[0]
        if isNode and selectedMenu == 1:
            # We're auto-filling submenu, so add all sub-nodes as possible default actions
            paths = paths + nodePaths

        if len(paths) > 1:
            # There are multiple actions to choose from
            selectedAction = xbmcgui.Dialog().select(LANGUAGE(32095), labels)

            if selectedAction == -1 or selectedAction is None:
                # User cancelled
                return True

            action = paths[selectedAction]

        # Add the shortcut to the menu the user has selected
        # Load existing main menu items
        menuitems = data_func.get_shortcuts(allLabelIDs[selectedMenu], processShortcuts=False)
        data_func.clear_labelID()

        # Generate a new labelID
        newLabelID = data_func.get_labelID(label, action)

        # Write the updated mainmenu.DATA.xml
        newelement = ETree.SubElement(menuitems.getroot(), "shortcut")
        ETree.SubElement(newelement, "label").text = label
        ETree.SubElement(newelement, "label2").text = "32024"  # Custom shortcut
        ETree.SubElement(newelement, "icon").text = icon
        ETree.SubElement(newelement, "thumb")
        ETree.SubElement(newelement, "action").text = action

        data_func.indent(menuitems.getroot())
        path = data_func.data_xml_filename(DATA_PATH,
                                           data_func.slugify(allLabelIDs[selectedMenu], True))
        menuitems.write(path, encoding="UTF-8")

        if isNode and selectedMenu == 1:
            # We're also going to write a submenu
            menuitems = ETree.ElementTree(ETree.Element("shortcuts"))

            for item in json_response['result']['files']:
                if item["filetype"] == "directory":
                    newelement = ETree.SubElement(menuitems.getroot(), "shortcut")
                    ETree.SubElement(newelement, "label").text = item["label"]
                    ETree.SubElement(newelement, "label2").text = "32024"  # Custom shortcut
                    ETree.SubElement(newelement, "icon").text = item["thumbnail"]
                    ETree.SubElement(newelement, "thumb")
                    ETree.SubElement(newelement, "action").text = \
                        "ActivateWindow(%s,%s,return)" % (window, item["file"])

            data_func.indent(menuitems.getroot())
            path = data_func.data_xml_filename(DATA_PATH, data_func.slugify(newLabelID, True))
            menuitems.write(path, encoding="UTF-8")

        # Mark that the menu needs to be rebuilt
        HOME_WINDOW.setProperty("skinshortcuts-reloadmainmenu", "True")

        # And tell the user it all worked
        xbmcgui.Dialog().ok(ADDON.getAddonInfo("name"), LANGUAGE(32090))

    @staticmethod
    def extract_id(path):
        # Extract the ID of an item from its path
        itemID = path
        if "?" in itemID:
            itemID = itemID.rsplit("?", 1)[0]
        if itemID.endswith("/"):
            itemID = itemID[:-1]
        itemID = itemID.rsplit("/", 1)[1]
        return itemID

    # ##############################################
    # ### Functions to externally set properties ###
    # ##############################################

    # noinspection PyDictCreation
    @staticmethod
    def set_properties(properties, values, labelID, group, data_func):
        # This function will take a list of properties and values and apply them to the
        # main menu item with the given labelID
        if not group:
            group = "mainmenu"

        # Split up property names and values
        propertyNames = properties.split("|")
        propertyValues = values.replace("::INFO::", "$INFO").split("|")
        labelIDValues = labelID.split("|")
        if len(labelIDValues) == 0:
            # No labelID passed in, lets assume we were called in error
            return
        if len(propertyNames) == 0:
            # No values passed in, lets assume we were called in error
            return

        # Get user confirmation that they want to make these changes
        message = "Set %s property to %s?" % (propertyNames[0], propertyValues[0])
        if len(propertyNames) == 2:
            message += "[CR](and 1 other property)"
        elif len(propertyNames) > 2:
            message += "[CR](and %d other properties)" % (len(propertyNames) - 1)
        shouldRun = xbmcgui.Dialog().yesno(ADDON.getAddonInfo("name"), message)
        if not shouldRun:
            return

        # Load the properties
        currentProperties, defaultProperties = data_func.get_additionalproperties()
        otherProperties, requires, templateOnly = data_func.getPropertyRequires()

        # If there aren't any currentProperties, use the defaultProperties instead
        if currentProperties == [None]:
            currentProperties = defaultProperties

        # Pull out all properties into multi-dimensional dicts
        allProps = {}
        allProps[group] = {}
        for currentProperty in currentProperties:
            # If the group isn't in allProps, add it
            if currentProperty[0] not in list(allProps.keys()):
                allProps[currentProperty[0]] = {}
            # If the labelID isn't in the allProps[ group ], add it
            if currentProperty[1] not in list(allProps[currentProperty[0]].keys()):
                allProps[currentProperty[0]][currentProperty[1]] = {}
            # And add the property to allProps[ group ][ labelID ]
            if currentProperty[3] is not None:
                allProps[currentProperty[0]][currentProperty[1]][currentProperty[2]] = \
                    currentProperty[3]

        # Loop through the properties we've been asked to set
        for count, propertyName in enumerate(propertyNames):
            # Set the new value
            log("Setting %s to %s" % (propertyName, propertyValues[count]))
            if len(labelIDValues) != 1:
                labelID = labelIDValues[count]
            if labelID not in list(allProps[group].keys()):
                allProps[group][labelID] = {}
            allProps[group][labelID][propertyName] = propertyValues[count]

            # Remove any properties whose requirements haven't been met
            for key in otherProperties:
                if key in list(allProps[group][labelID].keys()) and \
                        key in list(requires.keys()) and \
                        requires[key] not in list(allProps[group][labelID].keys()):
                    # This properties requirements aren't met
                    log("Removing value %s" % key)
                    allProps[group][labelID].pop(key)

        # Build the list of all properties to save
        saveData = []
        for saveGroup in allProps:
            for saveLabelID in allProps[saveGroup]:
                for saveProperty in allProps[saveGroup][saveLabelID]:
                    saveData.append([saveGroup, saveLabelID, saveProperty,
                                     allProps[saveGroup][saveLabelID][saveProperty]])

        write_properties(saveData)

        # The properties will only be used if the .DATA.xml file exists in the
        # addon_data folder( otherwise the script will use the default values),
        # so we're going to open and write the 'group' that has been passed to us
        menuitems = data_func.get_shortcuts(group, processShortcuts=False)
        data_func.indent(menuitems.getroot())
        path = data_func.data_xml_filename(DATA_PATH, data_func.slugify(group, True))
        menuitems.write(path, encoding="UTF-8")

        log("Properties updated")

        # Mark that the menu needs to be rebuilt
        HOME_WINDOW.setProperty("skinshortcuts-reloadmainmenu", "True")


# ============================
# === PRETTY SELECT DIALOG ===
# ============================

class ShowDialog(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        xbmcgui.WindowXMLDialog.__init__(self, *args)
        self.listing = kwargs.get("listing")
        self.windowtitle = kwargs.get("windowtitle")
        self.getmore = kwargs.get("getmore")
        self.result = -1
        self.fav_list = None

    def onInit(self):
        try:
            self.fav_list = self.getControl(6)
            self.getControl(3).setVisible(False)
        except:
            print_exc()
            self.fav_list = self.getControl(3)

        if self.getmore is True:
            self.getControl(5).setLabel(xbmc.getLocalizedString(21452))
        else:
            self.getControl(5).setVisible(False)
        self.getControl(1).setLabel(self.windowtitle)

        # Set Cancel label (Kodi 17+)
        self.getControl(7).setLabel(xbmc.getLocalizedString(222))

        for item in self.listing:
            listitem = xbmcgui.ListItem(label=item.getLabel(), label2=item.getLabel2())
            listitem.setArt({
                'icon': item.getProperty("icon"),
                'thumb': item.getProperty("thumbnail")
            })
            listitem.setProperty("Addon.Summary", item.getLabel2())
            self.fav_list.addItem(listitem)

        self.setFocus(self.fav_list)

    def onAction(self, action):
        if action.getId() in (9, 10, 92, 216, 247, 257, 275, 61467, 61448,):
            self.result = -1
            self.close()

    def onClick(self, controlID):
        if controlID == 5:
            self.result = -2
        elif controlID == 6 or controlID == 3:
            num = self.fav_list.getSelectedPosition()
            self.result = num
        else:
            self.result = -1

        self.close()

    def onFocus(self, controlID):
        pass
