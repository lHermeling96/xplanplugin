﻿# -*- coding: utf-8 -*-
"""
/***************************************************************************
XPlan
A QGIS plugin
Fachschale XPlan für XPlanung
                             -------------------
begin                : 2013-03-08
copyright            : (C) 2013 by Bernhard Stroebl, KIJ/DV
email                : bernhard.stroebl@jena.de
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
# Import the PyQt and QGIS libraries
from PyQt4 import QtCore, QtGui, QtSql,  QtXml
# Initialize Qt resources from file resources.py
from qgis.core import *
from qgis.gui import *
from XPlanDialog import BereichsauswahlDialog
from XPlanDialog import StilauswahlDialog

class XPTools():
    def __init__(self, iface, standardName):
        self.iface = iface
        self.standardName = standardName # Name des Standardstils
        self.bereiche = {}
        # dictionary, um den Typ eines Bereichs zu speichern, so dass nur einmal pro Session und Bereich eine SQL-Abfrage nötig ist

    def chooseBereich(self,  db,  multiSelect = False,  title = "Bereichsauswahl"):
        '''Starte Dialog zur Bereichsauswahl'''
        dlg = BereichsauswahlDialog(self.iface,  db,  multiSelect,  title)
        dlg.show()
        result = dlg.exec_()

        if result == 0: #Abbruch
            return {-1: -1}
        else:
            return dlg.selected

    def chooseStyle(self, layer):
        '''
        Biete Auswahl der für diesen Layer zur Verfügung stehenden Stile an
        und gib den Namen des ausgewählten Stils zurück
        '''

        stile = {}
        styleMan = layer.styleManager()
        i = 0

        for aStyle in styleMan.styles():
            if aStyle != u"":
               i += 1
               stile[i] = aStyle

        if len(stile) == 0:
            self.noStyleWarning(layer)
            return None
        elif len(stile) == 1:
            return stile[1]
        else:
            dlg = StilauswahlDialog(self.iface, stile)
            dlg.show()
            stilId = dlg.exec_()

            if stilId == -1:
                return None
            else:
                return stile[stilId]

    def getLayerStyles(self, db, layer, showWarning = False):
        '''
        Liste alle für diesen Layer in der DB gespeicherten XP-Stile
        auf und gibt sie als Dict zurück Stil-Id:[Bereichsname, Stil(XML)]
        '''

        relation = self.getPostgresRelation(layer)

        if relation:
            sel = "SELECT l.id, COALESCE(b.name,\'" + \
                self.standardName + "\'), l.style \
                FROM \"QGIS\".\"layer\" l \
                LEFT JOIN \"XP_Basisobjekte\".\"XP_Bereich\" b ON l.\"XP_Bereich_gid\" = b.gid \
                WHERE l.schemaname = :schema \
                    AND l.tablename = :table \
                ORDER BY \"XP_Bereich_gid\" NULLS FIRST"

            query = QtSql.QSqlQuery(db)
            query.prepare(sel)
            query.bindValue(":schema", relation[0])
            query.bindValue(":table", relation[1])
            query.exec_()

            if query.isActive():
                if query.size() == 0:
                    if showWarning:
                        self.noStyleWarning(layer)
                    query.finish()
                    return None
                else:
                    stile = {}

                    while query.next():
                        styleId = query.value(0)
                        bereich = query.value(1)
                        style = unicode(query.value(2))
                        stile[styleId] = [bereich, style]

                    query.finish()
                    return stile
            else:
                self.showQueryError(query)
                query.finish()
                return None
        else:
            return None

    def loadStyles(self, db, layer):
        '''
        die Stile dieses Layers laden und auf den Layer anwenden
        '''
        styleMan = layer.styleManager()
        stile = self.getLayerStyles(db, layer)

        for key, value in stile.items():
            bereich = value[0]
            stil = value[1]
            styleMan.renameStyle(bereich, bereich + "_old") # falls schon vorhanden
            style = QgsMapLayerStyle(stil)
            styleMan.addStyle(bereich, style)
            styleMan.removeStyle(bereich + "_old")

        if len(stile) > 0:
            styleMan.removeStyle(u"") # den unbenannten Stil entfernen

    def useStyle(self, layer, bereich):
        '''
        benutze den Stil der den Namen "bereich" hat
        '''
        styleMan = layer.styleManager()

        if styleMan.setCurrentStyle(bereich):
            self.iface.legendInterface().refreshLayerSymbology(layer)
        else:
            if styleMan.setCurrentStyle(self.standardName):
                self.iface.legendInterface().refreshLayerSymbology(layer)

    def getBereichTyp(self,  db,  bereichGid):
        '''gibt den Typ (FP, BP etc) des Bereichs mit der übergebenen gid zurück'''
        bereichTyp = None

        try:
            bereichTyp = self.bereiche[bereichGid]
        except KeyError:
            sel = "SELECT substring(\"Objektart\",1,2) FROM \"XP_Basisobjekte\".\"XP_Bereiche\" WHERE gid = :bereichGid"
            query = QtSql.QSqlQuery(db)
            query.prepare(sel)
            query.bindValue(":bereichGid", bereichGid)
            query.exec_()

            if query.isActive():
                while query.next(): # returns false when all records are done
                    bereichTyp = query.value(0)

                query.finish()
                self.bereiche[bereichGid]  = bereichTyp
            else:
                self.showQueryError(query)
                query.finish()
                bereichTyp = None

        return bereichTyp

    def getBereicheFuerFeatures(self,  db,  bereichTyp,  fids):
        retValue = {}
        sel = "SELECT gid, \"" + bereichTyp + "_Bereich_gid\"  \
            FROM \"" + bereichTyp + "_Basisobjekte\".\"" + bereichTyp + "_Objekte\" "
        whereClause = ""

        for aFid in fids:
            if whereClause == "":
                whereClause = "WHERE \"" + bereichTyp + "_Bereich_gid\" IS NOT NULL AND (gid=" + str(aFid)
            else:
                whereClause += " OR gid=" + str(aFid)

        sel += whereClause + ") ORDER BY gid"

        query = QtSql.QSqlQuery(db)
        query.prepare(sel)
        query.exec_()

        if query.isActive():
            lastGid = -9999
            bereiche = []

            while query.next(): # returns false when all records are done
                gid = query.value(0)

                if gid != lastGid:
                    retValue[lastGid] = bereiche
                    lastGid = gid
                    bereiche = []

                bereiche.append(query.value(1))
            retValue[lastGid] = bereiche # letzten noch rein
            query.finish()
        else:
            self.showQueryError(query)
            query.finish()

        return retValue


    def joinLayer(self, sourceLayer, joinLayer, targetField = "gid",
            joinField = "gid", prefix = None, memoryCache = False):
        '''Zwei Layer joinen
        sourceLayer ist der Layer, an den der joinLayer angeknüpft wird
        targetField ist das Feld im sourceLayer, an das geknüpft wird, joinField
        ist das Feld im joinLayer'''

        for aJoinInfo in sourceLayer.vectorJoins():
            if aJoinInfo.joinLayerId == joinLayer.id():
                sourceLayer.removeJoin(joinLayer.id())

        joinInfo = QgsVectorJoinInfo()
        joinInfo.targetField = sourceLayer.fieldNameIndex(targetField)
        joinInfo.joinField = joinLayer.fieldNameIndex(joinField)
        joinInfo.joinLayerId = joinLayer.id()
        joinInfo.memoryCache = memoryCache

        if prefix != None:
            joinInfo.prefix = prefix

        sourceLayer.addJoin(joinInfo)

    def getPostgresRelation(self,  layer):
        '''gibt die Relation [schema, relation, Name_der_Geometriespalte] eines PostgreSQL-Layers zurück'''
        retValue = None

        if isinstance(layer, QgsVectorLayer):
            if layer.dataProvider().storageType().find("PostgreSQL") != -1:
                retValue = []
                for s in str(layer.source()).split(" "):
                    if s.startswith("table="):
                        for val in s.replace("table=", "").split("."):
                            retValue.append(val.replace('"',  ''))
                        if layer.geometryType() == 4: # geometrielos
                            retValue.append("")
                            break

                    elif s.startswith("("):
                        retValue.append(s.replace("(", "").replace(")", ""))

        return retValue

    def getLayerInBereich(self,  db,  bereichGid):
        '''gibt ein Array mit Arrays (Punkt, Linie, Fläche) aller Layer zurück, die Elemente
        im XP_Bereich mit der übergebenen gid haben'''
        bereichTyp = self.getBereichTyp(db,  bereichGid)

        if bereichTyp:
            sel = "SELECT \"Objektart\",  \
            CASE \"Objektart\" LIKE \'%Punkt\' WHEN true THEN \'Punkt\' ELSE \
                CASE \"Objektart\" LIKE \'%Linie\' WHEN true THEN \'Linie\' ELSE \'Flaeche\' \
                END \
            END as typ, \
            \"Objektartengruppe\" FROM ( \
            SELECT DISTINCT \"Objektart\", \"Objektartengruppe\" \
            FROM \"" + bereichTyp +"_Basisobjekte\".\"" + bereichTyp + "_Objekte\" \
            WHERE \"" + bereichTyp +"_Bereich_gid\" = :bereichGid) foo"
            query = QtSql.QSqlQuery(db)
            query.prepare(sel)
            query.bindValue(":bereichGid", bereichGid)
            query.exec_()

            if query.isActive():
                punktLayer = {}
                linienLayer = {}
                flaechenLayer = {}

                while query.next(): # returns false when all records are done
                    layer = query.value(0)
                    art = query.value(1)
                    gruppe = query.value(2)

                    if art == "Punkt":
                        try:
                            pLayerList = punktLayer[gruppe]
                            pLayerList.append(layer)
                        except KeyError:
                            punktLayer[gruppe] = [layer]
                    elif art == "Linie":
                        try:
                            lLayerList = linienLayer[gruppe]
                            lLayerList.append(layer)
                        except KeyError:
                            linienLayer[gruppe] = [layer]
                    elif art == "Flaeche":
                        try:
                            fLayerList = flaechenLayer[gruppe]
                            fLayerList.append(layer)
                        except KeyError:
                            flaechenLayer[gruppe] = [layer]

                query.finish()
                return [punktLayer,  linienLayer,  flaechenLayer]
        else:
            self.showQueryError(query)
            query.finish()
            return None

    def styleLayerDeprecated(self,  layer,  xmlStyle):
        '''wende den übergebenen Stil auf den übergebenen Layer an'''

        doc = QtXml.QDomDocument()

        if doc.setContent(xmlStyle.encode("utf-8"))[0]:
            rootNode = doc.firstChildElement()
            if layer.readSymbology(rootNode, "Fehler beim Anwenden"):

                if rootNode.hasAttributes():
                    attrs = rootNode.attributes()

                    if attrs.contains("minimumScale"):
                        minScaleAttr = attrs.namedItem("minimumScale")
                        layer.setMinimumScale(float(minScaleAttr.nodeValue()))

                    if attrs.contains("maximumScale"):
                        maxScaleAttr = attrs.namedItem("maximumScale")
                        layer.setMaximumScale(float(maxScaleAttr.nodeValue()))

                    if attrs.contains("hasScaleBasedVisibilityFlag"):
                        scaleBasedVisAttr = attrs.namedItem("hasScaleBasedVisibilityFlag")
                        layer.toggleScaleBasedVisibility(scaleBasedVisAttr.nodeValue() == "1")
                self.iface.legendInterface().refreshLayerSymbology(layer)
                return True
            else:
                return False

    def getXmlLayerStyle(self, layer):
        '''erzeuge ein XML-Style-Dokument'''
        doc=QtXml.QDomDocument()
        rootNode = doc.createElement("qgis")
        versionAttr = doc.createAttribute("version")
        versionAttr.setValue(QGis.QGIS_VERSION)
        rootNode.setAttributeNode(versionAttr)
        minScaleAttr = doc.createAttribute("minimumScale")
        minScaleAttr.setValue(str(layer.minimumScale()))
        rootNode.setAttributeNode(minScaleAttr)
        maxScaleAttr = doc.createAttribute("maximumScale")
        maxScaleAttr.setValue(str(layer.maximumScale()))
        rootNode.setAttributeNode(maxScaleAttr)
        scaleBasedVisAttr = doc.createAttribute("hasScaleBasedVisibilityFlag")
        scaleBasedVisAttr.setValue(str(int(layer.hasScaleBasedVisibility())))
        rootNode.setAttributeNode(scaleBasedVisAttr)
        doc.appendChild(rootNode)

        if layer.writeSymbology(rootNode,doc,"Fehler"):
            return doc
        else:
            return None

    def getGroupIndex(self,  groupName):
        '''Finde den Gruppenindex für Gruppe groupName'''
        retValue = -1
        groups = self.iface.legendInterface().groups()

        for i in range(len(groups)):
            if groups[i] == groupName:
                retValue = i
                break

        return retValue

    def createFeature(self,  layer, fid = None):
        '''Ein Feature für den übergebenen Layer erzeugen'''
        if isinstance(layer, QgsVectorLayer):
            if fid:
                newFeature = QgsFeature(fid)
            else:
                newFeature = QgsFeature()

            provider = layer.dataProvider()
            fields = layer.pendingFields()
            newFeature.initAttributes(fields.count())

            for i in range(fields.count()):
                newFeature.setAttribute(i,provider.defaultValue(i))

            return newFeature
        else:
            return None

    def isXpDb(self,  db):
        retValue = False
        sel = "SELECT * FROM pg_namespace WHERE nspname = \'XP_Basisobjekte\'"
        query = QtSql.QSqlQuery(db)
        query.prepare(sel)
        query.exec_()

        if query.isActive():
            retValue = (query.size() == 1)
        else:
            self.showQueryError(query)

        return retValue

    def setEditable(self, layer, showErrorMsg = False, iface = None):
    # is it a vectorLayer?
        ok = isinstance(layer, QgsVectorLayer)
        title = "Editierfehler"

        if ok:
            ok = layer.isEditable() # is already in editMode

            if not ok:
                # try to start editing
                ok = layer.startEditing()

                if not ok and showErrorMsg:
                    msg = u"Bitte sorgen Sie dafür, dass der Layer " + layer.name() + u" editierbar ist!"
                    if iface:
                        iface.messageBar().pushMessage(title, msg, level=QgsMessageBar.CRITICAL)
                    else:
                        QtGui.QMessageBox.information(None, title, msg)

        else:
            if showErrorMsg:
                msg = u"Der Layer " + layer.name() + u" ist kein Vektorlayer " + \
                    u" und damit nicht editierbar!"

                if iface:
                    iface.messageBar().pushMessage(title, msg, level=QgsMessageBar.CRITICAL)
                else:
                    QtGui.QMessageBox.information(None, title, msg)

        return ok

    def showQueryError(self, query):
        QtGui.QMessageBox.warning(None, "DBError",  "Database Error: \
            %(error)s \n %(query)s" % {"error": query.lastError().text(),  "query": query.lastQuery()})

    def noStyleWarning(self, layer):
        self.iface.messageBar().pushMessage(
            "XPlanung", u"Für den Layer " + layer.name() + u" sind keine Stile gespeichert",
            level=QgsMessageBar.WARNING, duration = 10)

    def debug(self,  msg):
        QtGui.QMessageBox.information(None, "Debug",  msg)
