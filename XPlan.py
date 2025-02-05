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
from __future__ import absolute_import
from builtins import map
from builtins import str
from builtins import range
from builtins import object
from qgis.PyQt import QtCore, QtWidgets, QtSql
from qgis.core import *
from qgis.gui import *

try:
    from DataDrivenInputMask.ddattribute import DdTable
except:
    pass

import sys, os

BASEDIR = os.path.dirname( str(__file__) )

from .HandleDb import DbHandler
from .XPTools import XPTools
from .XPImport import XPImporter
from .XPExport import XPExporter
from .XPlanDialog import XPlanungConf
from .XPlanDialog import ChooseObjektart
from .XPlanDialog import XPNutzungsschablone, BereichsmanagerDialog, ReferenzmanagerDialog, ImportDialog, ExportDialog

class XpError(object):
    '''General error'''
    def __init__(self, value, iface = None):
        self.value = value

        if iface == None:
            QtWidgets.QMessageBox.warning(None, "XPlanung", value, duration = 10)
        else:
            iface.messageBar().pushMessage("XPlanung", value,
                level=Qgis.Critical)
    def __str__(self):
        return repr(self.value)

class XPlan(object):
    def __init__(self, iface):
        # Save reference to the QGIS interface
        self.iface = iface
        self.standardName = u"XP-Standard"
        self.simpleStyleName = "einfarbig"
        self.tmpAct = QtWidgets.QAction(self.iface.mainWindow()) # eine nicht benötigte QAction
        self.app = QgsApplication.instance()
        self.app.xpPlugin = self
        self.nutzungsschablone = None
        self.tools = XPTools(self.iface, self.standardName, self.simpleStyleName)
        self.dbHandler = DbHandler(self.iface, self.tools)
        self.db = None
        self.aktiveBereiche = {}
        self.auswahlPlan = {} # Auswahl der Plangebiete für den Export
        self.xpLayers = {} # dict, key = layerId
            # item = [layer (QgsVectorLayer), maxGid (long),
            # featuresHaveBeenAdded (Boolean), bereichsFilterAktiv (Boolean)]
        self.displayLayers = {} # dict, key = layerId
            # item = [layer, None, None, bereichsFilterAktiv] für Ansichtslayer
        self.layerLayer = None
        # Liste der implementierten Fachschemata
        self.implementedSchemas = []
        self.willAktivenBereich = True # Nutzer möchte aktive Bereiche festlegen

        #importiere DataDrivenInputMask
        pluginDir = QtCore.QFileInfo(QgsApplication.qgisUserDatabaseFilePath()).path() + "/python/plugins/"
        maskDir = pluginDir + "DataDrivenInputMask"
        maskFound = False

        for p in sys.path:
            if p == maskDir:
                maskFound = True
                break

        if not maskFound:
            sys.path.append(maskDir)

        try:
            from DataDrivenInputMask import ddui, ddmanager
            self.ddUi = ddui.DataDrivenUi(self.iface)

            try:
                self.app.xpManager
            except AttributeError:
                ddManager = ddmanager.DdManager(self.iface)
                self.app.xpManager = ddManager
        except ImportError:
            self.unload()
            XpError(u"Bitte installieren Sie das Plugin " + \
                "DataDrivenInputMask aus dem QGIS Official Repository!",
                self.iface)

        # Layer der die Zuordnung von Objekten zu Bereichen enthält
        self.gehoertZuLayer = None

        qs = QtCore.QSettings()
        svgpaths = qs.value( "svg/searchPathsForSVG", "", type=str )

        if isinstance(svgpaths, str):
            if svgpaths == "":
                svgpaths = []
            else:
                svgpaths = [svgpaths]

        svgpath = os.path.abspath( os.path.join( BASEDIR, "svg" ) )

        if not svgpath.upper() in list(map(str.upper, svgpaths)):
            svgpaths.append( svgpath )
            qs.setValue( "svg/searchPathsForSVG", svgpaths )

        self.initializeAllLayers()

    def initGui(self):
        # Code von fTools

        self.xpMenu = QtWidgets.QMenu(u"XPlanung")
        self.bereichMenu = QtWidgets.QMenu(u"XP_Bereich")
        self.bereichMenu.setToolTip(u"Ein Planbereich fasst die Inhalte eines Plans " +\
            u"nach bestimmten Kriterien zusammen.")
        self.bpMenu = QtWidgets.QMenu(u"BPlan")
        self.bpMenu.setToolTip(u"Fachschema BPlan für Bebauungspläne")
        self.fpMenu = QtWidgets.QMenu(u"FPlan")
        self.fpMenu.setToolTip(u"Fachschema FPlan für Flächennutzungspläne")
        self.lpMenu = QtWidgets.QMenu(u"LPlan")
        self.lpMenu.setToolTip(u"Fachschema LPlan für Landschaftspläne")
        self.rpMenu = QtWidgets.QMenu(u"Regionalplan")
        self.rpMenu.setToolTip(u"Fachschema für Regionalpläne")
        self.soMenu = QtWidgets.QMenu(u"SonstigePlanwerke")
        self.soMenu.setToolTip(u"Fachschema zur Modellierung nachrichtlicher Übernahmen " + \
            u"aus anderen Rechtsbereichen und sonstiger raumbezogener Pläne nach BauGB. ")
        self.xpDbMenu = QtWidgets.QMenu(u"XPlanung")

        self.action9 = QtWidgets.QAction(u"Einstellungen", self.iface.mainWindow())
        self.action9.triggered.connect(self.setSettings)
        self.action0 = QtWidgets.QAction(u"Initialisieren", self.iface.mainWindow())
        self.action0.triggered.connect(self.initialize)
        self.action1 = QtWidgets.QAction(u"Bereich laden", self.iface.mainWindow())
        self.action1.setToolTip(u"Alle zu einem Bereich gehörenden Elemente " + \
            u"laden und mit gespeichertem Stil darstellen")
        self.action1.triggered.connect(self.bereichLaden)
        self.action2 = QtWidgets.QAction(u"Layer initialisieren", self.iface.mainWindow())
        self.action2.setToolTip(u"aktiver Layer: Eingabemaske erzeugen, neue Features den aktiven " +\
            u"Bereichen zuweisen.")
        self.action2.triggered.connect(self.layerInitializeSlot)
        self.action3 = QtWidgets.QAction(u"Bereichsmanager starten", self.iface.mainWindow())
        self.action3.setToolTip(u"Bereichsmanager starten")
        self.action3.triggered.connect(self.bereichsmanagerStartenSlot)
        self.action4 = QtWidgets.QAction(u"Auswahl den aktiven Bereichen zuordnen", self.iface.mainWindow())
        self.action4.setToolTip(u"aktiver Layer: ausgewählte Elemente den aktiven Bereichen zuweisen. " +\
                                u"Damit werden sie zum originären Inhalt des Planbereichs.")
        self.action4.triggered.connect(self.aktivenBereichenZuordnenSlot)
        self.action6 = QtWidgets.QAction(u"Layer darstellen (nach PlanZV)", self.iface.mainWindow())
        self.action6.setToolTip(u"aktiver Layer: gespeicherten Stil anwenden")
        self.action6.triggered.connect(self.layerStyleSlot)
        self.action10 = QtWidgets.QAction(u"Mehrfachdateneingabe", self.iface.mainWindow())
        self.action10.setToolTip(u"Eingabe für alle gewählten Objekte")
        self.action10.triggered.connect(self.layerMultiEditSlot)
        self.action7 = QtWidgets.QAction(u"Layerstil speichern", self.iface.mainWindow())
        self.action7.setToolTip(u"aktiver Layer: Stil speichern")
        self.action7.triggered.connect(self.saveStyleSlot)
        self.action8 = QtWidgets.QAction(u"gespeicherten Layerstil löschen", self.iface.mainWindow())
        self.action8.setToolTip(u"aktiver Layer: aktien Layerstil löschen")
        self.action8.triggered.connect(self.deleteStyleSlot)

        self.action20 = QtWidgets.QAction(u"Objektart laden", self.iface.mainWindow())
        self.action20.triggered.connect(self.loadXP)
        self.action21 = QtWidgets.QAction(u"Objektart laden", self.iface.mainWindow())
        self.action21.triggered.connect(self.loadBP)
        self.action22 = QtWidgets.QAction(u"Objektart laden", self.iface.mainWindow())
        self.action22.triggered.connect(self.loadFP)
        self.action23 = QtWidgets.QAction(u"Objektart laden", self.iface.mainWindow())
        self.action23.triggered.connect(self.loadLP)
        self.action24 = QtWidgets.QAction(u"Objektart laden", self.iface.mainWindow())
        self.action24.triggered.connect(self.loadSO)
        self.action25 = QtWidgets.QAction(u"ExterneReferenzen bearbeiten", self.iface.mainWindow())
        self.action25.triggered.connect(self.referenzmanagerStarten)
        self.action26 = QtWidgets.QAction(u"räuml. Geltungsbereiche neu berechnen",
            self.iface.mainWindow())
        self.action26.triggered.connect(self.geltungsbereichBerechnen)
        self.action27 = QtWidgets.QAction(u"Objektart laden", self.iface.mainWindow())
        self.action27.triggered.connect(self.loadRP)
        self.action28 = QtWidgets.QAction(u"Nutzungsschablone konfigurieren", self.iface.mainWindow())
        self.action28.triggered.connect(self.konfiguriereNutzungsschablone)
        self.action29 = QtWidgets.QAction(u"Stylesheetparameter konfigurieren", self.iface.mainWindow())
        self.action29.triggered.connect(self.konfiguriereStylesheet)
        self.action30 = QtWidgets.QAction(u"Importieren", self.iface.mainWindow())
        self.action30.triggered.connect(self.importData)
        self.action31 = QtWidgets.QAction(u"Exportieren", self.iface.mainWindow())
        self.action31.triggered.connect(self.exportData)
        


        self.xpMenu.addActions([self.action20, self.action25, self.action29,
            self.action6, self.action10, self.action30, self.action31])
        self.bereichMenu.addActions([self.action3, self.action1, self.action4])
        self.bpMenu.addActions([self.action21, self.action26, self.action28])
        self.fpMenu.addActions([self.action22])
        self.lpMenu.addActions([self.action23])
        self.rpMenu.addActions([self.action27])
        self.soMenu.addActions([self.action24])
        self.xpDbMenu.addActions([self.action9, self.action7, self.action8])
        # Add toolbar button and menu item

        self.iface.addPluginToVectorMenu("tmp", self.tmpAct) # sicherstellen, dass das VektorMenu da ist
        self.vectorMenu = self.iface.vectorMenu()
        self.vectorMenu.addMenu(self.xpMenu)
        self.vectorMenu.addMenu(self.bereichMenu)
        self.vectorMenu.addMenu(self.bpMenu)
        self.vectorMenu.addMenu(self.fpMenu)
        self.vectorMenu.addMenu(self.lpMenu)
        self.vectorMenu.addMenu(self.rpMenu)
        self.vectorMenu.addMenu(self.soMenu)
        self.iface.removePluginVectorMenu("tmp", self.tmpAct)
        self.iface.addPluginToDatabaseMenu("tmp", self.tmpAct)
        self.databaseMenu = self.iface.databaseMenu()
        self.databaseMenu.addMenu(self.xpDbMenu)
        self.iface.removePluginDatabaseMenu("tmp", self.tmpAct)

    # Deinstalieren und löschen aus dem Menü
    def unload(self):
        try:
            self.app.xpManager.quit()
            self.iface.addPluginToVectorMenu("tmp", self.tmpAct)
            self.vectorMenu.removeAction(self.xpMenu.menuAction())
            self.vectorMenu.removeAction(self.bereichMenu.menuAction())
            self.vectorMenu.removeAction(self.bpMenu.menuAction())
            self.vectorMenu.removeAction(self.fpMenu.menuAction())
            self.vectorMenu.removeAction(self.lpMenu.menuAction())
            self.vectorMenu.removeAction(self.rpMenu.menuAction())
            self.vectorMenu.removeAction(self.soMenu.menuAction())
            self.iface.removePluginVectorMenu("tmp", self.tmpAct)
            self.iface.addPluginToDatabaseMenu("tmp", self.tmpAct)
            self.databaseMenu.removeAction(self.xpDbMenu.menuAction())
            self.iface.removePluginDatabaseMenu("tmp", self.tmpAct)
        except:
            pass

    # Methode zum debuggen von Fehlern mit Tool aus XPTools
    def debug(self, msg):
        self.tools.log("Debug" + "\n" + msg)

    # ???:  Funktion mit der geschaut wird ob Layer in den Tabellen geladen werden kann
    def loadLayerLayer(self):
        self.layerLayer = self.getLayerForTable("QGIS", "layer")

        if self.layerLayer == None:
            XpError(u"Kann Tabelle QGIS.layer nicht laden!", self.iface)
            return False
        else:
            self.layerLayer.destroyed.connect(self.onLayerLayerDeleted)
            return True

    # Ausgabe der Style ID
    def getStyleId(self, schemaName, tableName, bereich):
        sel = "SELECT id, COALESCE(\"XP_Bereich_gid\",-9999) \
            FROM \"QGIS\".\"layer\" l \
            LEFT JOIN \"XP_Basisobjekte\".\"XP_Bereiche\" b ON l.\"XP_Bereich_gid\" = b.gid \
            WHERE l.schemaname = :schema \
            AND l.tablename = :table \
            AND b.name"

        if bereich == self.standardName:
            sel += " IS NULL"
        else:
            sel += " = :bereich"

        query = QtSql.QSqlQuery(self.db)
        query.prepare(sel)
        query.bindValue(":schema", schemaName)
        query.bindValue(":table", tableName)

        if bereich != self.standardName:
            query.bindValue(":bereich", bereich)

        query.exec_()

        if query.isActive():
            stilId = None

            while query.next(): # returns false when all records are done
                stilId = query.value(0)

            query.finish()
            return stilId
        else:
            self.showQueryError(query)
            return None

    # Nutrzungsschablone
    def erzeugeNutzungsschablone(self, gid):
        '''
        die Werte für die Nutzungsschablone aus der DB auslesen
        und als String zurückgeben
        '''
        returnValue = [None, None, None]

        if self.nutzungsschablone != None:
            # Anzahl Zeilen und Spalten feststellen
            if self.nutzungsschablone[1] != None or \
                    self.nutzungsschablone[3] != None or \
                    self.nutzungsschablone[5] != None:
                anzSpalten = 2
            else:
                anzSpalten = 1

            if self.nutzungsschablone[2] != None or \
                    self.nutzungsschablone[3] != None:
                anzZeilen = 2

                if self.nutzungsschablone[4] != None or \
                        self.nutzungsschablone[5] != None:
                    anzZeilen = 3
            else:
                anzZeilen = 1

            # Abfrage bauen
            sQuery = "SELECT "

            for fld in self.nutzungsschablone:
                if fld == None:
                    fld = "NULL"
                else:
                    fld = "\"" + fld + "\""

                if sQuery != "SELECT ":
                    sQuery += ","

                sQuery += fld

            sQuery += " FROM \"BP_Bebauung\".\"BP_BaugebietsTeilFlaeche\" b \
            JOIN \"BP_Bebauung\".\"BP_BaugebietObjekt\" o ON b.gid = o.gid \
            JOIN \"BP_Bebauung\".\"BP_FestsetzungenBaugebiet\" f ON b.gid = f.gid \
            JOIN \"BP_Bebauung\".\"BP_BaugebietBauweise\" bw ON b.gid = bw.gid \
            WHERE b.gid = :gid;"
            query = QtSql.QSqlQuery(self.db)
            query.prepare(sQuery)
            query.bindValue(":gid", gid)
            # DB abfragen
            query.exec_()

            if query.isActive():
                werte = []
                while query.next():
                    for i in range(len(self.nutzungsschablone)):
                        werte.append(query.value(i))

                query.finish()
            else:
                self.tools.showQueryError(query)
                return returnValue

            #Text zusammenbauen
            allgArtBlNtzg = {1000:"W", 2000:"M", 3000:"G", 4000:"S", 9999:"Sonst"}
            besArtBlNtzg = {1000:"WS", 1100:"WR", 1200:"WA", 1300:"WB", 1400:"MD", 1500:"MI",
                1600:"MK", 1700:"GE", 1800:"GI", 2000:"SO", 2100:"SO", 3000:"SO", 4000:"SO", 9999:"Sonst"}
            bauweise = {1000:"o", 2000:"g"}
            #bebArt = {1000:"E", 2000:"D", 3000:"H", 4000:"ED", 5000:"EH", 6000:"DH", 7000:"R"}
            geschoss = {1:"I", 2:"II", 3:"III", 4:"IV", 5:"V", 6:"VI", 7:"VII", 8:"VIII", 9:"IX", 10:"X",
                11:"XI", 12:"XII", 13:"XIII", 14:"XIV", 15:"XV", 16:"XVI", 17:"XVII", 18:"XVIII", 19:"XIX", 20:"XX"}
            schablonenText = ""
            loc = QtCore.QLocale.system()

            for i in range(len(self.nutzungsschablone)):
                fld = self.nutzungsschablone[i]
                wert = werte[i]

                if fld != None and wert != None:
                    if fld == "allgArtDerBaulNutzung":
                        thisStr = allgArtBlNtzg[wert]
                    elif fld == "besondereArtDerBaulNutzung":
                        thisStr = besArtBlNtzg[wert]
                    elif fld == "bauweise":
                        thisStr = bauweise[wert]
                    elif fld == "GFZ" or fld == "GFZmin":
                        thisStr = "GFZ " + loc.toString(wert)
                    elif fld == "GFZmax":
                        thisStr = "bis " + loc.toString(wert)
                    elif fld == "GF" or fld == "GFmin":
                        thisStr = "GF " + str(wert) + u" m²"
                    elif fld == "GFmax":
                        thisStr = "bis " + str(wert) + u" m²"
                    elif fld == "BMZ" or fld == "BMZmin":
                        thisStr = "BMZ " + loc.toString(wert)
                    elif fld == "BMZmax":
                        thisStr = "bis " + loc.toString(wert)
                    elif fld == "BM" or fld == "BMmin":
                        thisStr = "BM " + str(wert) + u" m³"
                    elif fld == "BMmax":
                        thisStr = "bis " + str(wert) + u" m³"
                    elif fld == "GRZ" or fld == "GRZmin":
                        thisStr = "GRZ " + loc.toString(wert)
                    elif fld == "GRZmax":
                        thisStr = "bis " + loc.toString(wert)
                    elif fld == "GR" or fld == "GRmin":
                        thisStr = "GR " + str(wert) + u" m²"
                    elif fld == "GRmax":
                        thisStr = "bis " + str(wert) + u" m²"
                    elif fld == "Z" or  fld == "Zmin":
                        thisStr = geschoss[wert]
                    elif fld == "Zmax":
                        thisStr = " - " + geschoss[wert]
                else:
                    thisStr = ""

                if i in [0, 2, 4]:
                    zeile = " " + thisStr
                else:
                    while len(zeile) < 10:
                        zeile += " " # mit Leerzeichen auffüllen

                    zeile += thisStr

                    if (i == 1 and anzZeilen > 1) or (i == 3 and anzZeilen > 2):
                        zeile += "\n"

                    schablonenText += zeile

            returnValue = [anzSpalten, anzZeilen, schablonenText]
        return returnValue

    # 
    def plaziereNutzungsschablone(self, gid, x, y):
        ''' gid von BP_Baugebietsteilflaeche'''

        if self.nutzungsschablone == None:
            self.konfiguriereNutzungsschablone()

        if self.db == None:
            self.initialize((self.willAktivenBereich and len(self.aktiveBereiche) == 0))

        if self.db != None:
            anzSpalten,  anzZeilen, schablonenText = self.erzeugeNutzungsschablone(gid)

            if anzSpalten == None and anzZeilen == None:
                self.debug("anzSpalten == None and anzZeilen == None")
                return None

            nutzungsschabloneLayer = self.getLayerForTable(
                "XP_Praesentationsobjekte", "XP_Nutzungsschablone",
                geomColumn = "position")

            if nutzungsschabloneLayer == None:
                self.debug("nutzungsschabloneLayer nicht gefunden")
                return None
            else:
                self.layerInitialize(nutzungsschabloneLayer)

            tpoLayer = self.getLayerForTable(
                "XP_Praesentationsobjekte", "XP_TPO")

            if tpoLayer == None:
                self.debug("tpoLayer nicht gefunden")
                return None

            nutzungsschabloneFeat = self.tools.createFeature(nutzungsschabloneLayer)
            nutzungsschabloneFeat[nutzungsschabloneLayer.fields().lookupField("spaltenAnz")] = anzSpalten
            nutzungsschabloneFeat[nutzungsschabloneLayer.fields().lookupField("zeilenAnz")] = anzZeilen
            nutzungsschabloneFeat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))

            if self.tools.setEditable(nutzungsschabloneLayer):
                if not nutzungsschabloneLayer.addFeature(nutzungsschabloneFeat):
                    self.tools.showError(u"Konnte neue Nutzungsschablone nicht hinzufügen")
                    return None
                else:
                    if not nutzungsschabloneLayer.commitChanges():
                        self.tools.showError(u"Konnte neue Nutzungsschablone nicht speichern")
                        return None
                    else:
                        expr = "round($x,2) = round(" + str(x) + ",2) and round($y,2) = round(" + str(y) + ",2)"
                        #runden wegen unterschiedlicher Präzision
                        savedFeat = QgsFeature()

                        if nutzungsschabloneLayer.getFeatures(
                                QgsFeatureRequest().setFilterExpression(expr)).nextFeature(savedFeat):
                            newGid = savedFeat[nutzungsschabloneLayer.fields().lookupField("gid")]
                        else:
                            self.tools.showError(u"Neu angelegtes Objekt nicht gefunden!")
                            return None

                        if self.tools.setEditable(tpoLayer):
                            expr = "gid = " + str(newGid)
                            tpoFeat = QgsFeature()

                            if tpoLayer.getFeatures(
                                    QgsFeatureRequest().setFilterExpression(expr)).nextFeature(tpoFeat):
                                tpoLayer.changeAttributeValue(tpoFeat.id(), tpoLayer.fields().lookupField("schriftinhalt"),
                                    schablonenText)
                                if not tpoLayer.commitChanges():
                                    self.tools.showError(u"Konnte Schriftinhalt nicht speichern")
                                    return None

    #Slots
    def importData(self):
        if self.db == None:
            self.initialize()

        dlg = ImportDialog(self)
        dlg.show()
        result = dlg.exec_()

        if result == 1:
            schritt1 = dlg.params["schritt1"]
            schritt2 = dlg.params["schritt2"]
            importer = XPImporter(self.db, self.tools, dlg.params)
            importSchema = dlg.params["importSchema"]

            if schritt1:
                proc, loglines = importer.importGml()

                if proc == 0:
                    ogrSuccess = "Import mit ogr2ogr (GMLAS) nach Schema \"" +  \
                            importSchema + "\" erfolgreich"
                    self.tools.showInfo(ogrSuccess)
                    self.tools.log(ogrSuccess)
                else:
                    self.tools.showError("Import mit ogr2ogr fehlgeschlagen, Details im Protokoll")
                    self.tools.log(loglines, "error")
                    return None
            else:
                proc = 0

            if proc == 0 and schritt2:
                impResult = importer.importPlan()

                if impResult != None:
                    successMsg = "Import war erfolgreich"
                    self.tools.showInfo(successMsg + ", Details im Protokoll")
                    self.tools.log(successMsg + "\n" + impResult)
                else:
                    self.tools.showError("Import fehlgeschlagen")

                # db-Anmeldung erneuern
                self.dbHandler.dbDisconnect(self.db)
                self.db = None
                self.db = self.dbHandler.dbConnect()

##############################################################################################################
############################### Export-Bereich ###############################################################
##############################################################################################################

    def exportData(self):
        # Abfrage der Datenbankverbindung
        if self.db == None:
            self.initialize(False) # False: Dialog "aktive Bereiche auswählen" wird nicht geöffnet
        # Aufruf GUI Export
        dlg = ExportDialog(self)
        dlg.show()
        result = dlg.exec_()
        # Erzeugen der Klasse Exporter
        exp = None
        if result == 1:
            exporter = XPExporter(self.db, self.tools, dlg.params, self.auswahlPlanart)
            # Ausführen der Funktion für den Export
            exp = exporter.exportGml()
        # Abfrage ob der Export erfolgreich durchgeführt wurde
        if exp != None:
            self.tools.showInfo('Export des Plan-Gebiets "'+ exp +'" erfolgreich!')
        else:
             self.tools.showInfo('Export wurde abgebrochen!!!')
    
    # Fenster für die Auswahl des Plangebiets im Export
    def exportGebiete(self):
        '''Gebietsauswahl für den Export'''
        if self.db == None:
            self.initialize(False)
        
        if self.db:
            planAuswahl, planartAuswahl = self.tools.chooseGebiete(self.db,  False,  u"Gebietsauswahl für den Export")
            
            # Auswahl der Gebiete zum Export wurde getroffen oder es wurde abgebrochen
            if len(planAuswahl) > 0:
                self.auswahlPlan = planAuswahl
                self.auswahlPlanart = planartAuswahl
                return True
            else:
                return None  
##############################################################################################################
##############################################################################################################
##############################################################################################################


    # Nutzungsschablone konfigurieren
    def konfiguriereNutzungsschablone(self):
        dlg = XPNutzungsschablone(self.nutzungsschablone)
        dlg.show()
        result = dlg.exec_()

        if result == 1:
            self.nutzungsschablone = dlg.nutzungsschablone

    #
    def konfiguriereStylesheet(self, isChecked = False, forCode = None):
        if self.db == None:
            self.initialize()

        stylesheetParameterLayer = self.getLayerForTable("QGIS","XP_StylesheetParameter")
        stylesheetLayer = self.getLayerForTable("XP_Praesentationsobjekte","XP_StylesheetListe")

        if stylesheetParameterLayer != None and stylesheetLayer != None:
            if forCode == None:
                forCode, ok = QtWidgets.QInputDialog.getInt(None, u"Stylesheetparameter konfigurieren",
                    u"Code des Stylesheets eingeben", min = 1)
            else:
                ok = True

            if ok:
                paraFeat = QgsFeature()
                expr = "\"Code\" = " + str(forCode)

                if stylesheetParameterLayer.getFeatures(QgsFeatureRequest().setFilterExpression(expr)).nextFeature(paraFeat):
                    # gibt es bereits; editieren
                    self.app.xpManager.showFeatureForm(
                            stylesheetParameterLayer, paraFeat, askForSave = False)
                else:
                    # prüfen, ob es das stylesheet schon gibt, ansonsten anlegen
                    styleFeat = QgsFeature()

                    if not stylesheetLayer.getFeatures(QgsFeatureRequest().setFilterExpression(expr)).nextFeature(styleFeat):
                        styleFeat = self.tools.createFeature(stylesheetLayer)

                        if styleFeat != None and self.tools.setEditable(stylesheetLayer, True, self.iface):
                            if not stylesheetLayer.addFeature(styleFeat):
                                self.tools.showError(u"Konnte neues Stylesheetfeature nicht einfügen")
                                stylesheetLayer.rollBack()
                                return None
                            else:
                                if not stylesheetLayer.changeAttributeValue(
                                        styleFeat.id(), stylesheetLayer.fields().lookupField("Code"), forCode):
                                    self.tools.showError(u"Konnte Code für stylesheet nicht ändern")
                                    stylesheetLayer.rollBack()
                                    return None
                                else:
                                    if not stylesheetLayer.changeAttributeValue(
                                            styleFeat.id(), stylesheetLayer.fields().lookupField("Bezeichner"), "Code " + str(forCode)):
                                        self.tools.showError(u"Konnte Bezeichner für stylesheet nicht ändern")
                                        stylesheetLayer.rollBack()
                                        return None
                                    else:
                                        if not stylesheetLayer.commitChanges():
                                            self.tools.showError(u"Konnte Änderungen in XP_StylesheetListe nicht speichern")
                                            return None
                                        else:
                                            self.konfiguriereStylesheet(forCode = forCode)
                    else:
                        paraFeat = self.tools.createFeature(stylesheetParameterLayer)

                        if paraFeat != None and self.tools.setEditable(stylesheetParameterLayer, True, self.iface):
                            if not stylesheetParameterLayer.addFeature(paraFeat):
                                self.tools.showError(u"Konnte neues StylesheetParameterfeature nicht einfügen")
                                stylesheetParameterLayer.rollBack()
                                return None
                            else:
                                if not stylesheetParameterLayer.changeAttributeValue(
                                        paraFeat.id(), stylesheetParameterLayer.fields().lookupField("Code"), forCode):
                                    self.tools.showError(u"Konnte Code für stylesheetParameter nicht ändern")
                                    stylesheetParameterLayer.rollBack()
                                    return None
                                else:
                                    if not stylesheetParameterLayer.commitChanges():
                                        self.tools.showError(u"Konnte Änderungen in XP_StylesheetParamenter nicht speichern")
                                        return None
                                    else:
                                        # zeige die DataDrivenInputMask
                                        if stylesheetParameterLayer.getFeatures(
                                                QgsFeatureRequest().setFilterExpression(expr)).nextFeature(paraFeat):
                                            self.app.xpManager.showFeatureForm(
                                                    stylesheetParameterLayer, paraFeat, askForSave = False)


    def geltungsbereichBerechnen(self):
        '''raeumlicherGeltungsbereich für alle (selektierten)
        BP_Plan aus den Geltungsbereichen
        von BP_Bereich berechnen'''
        if self.db == None:
            self.initialize(False)

        if self.db != None:
            bpPlanLayer = self.getLayerForTable(
                "BP_Basisobjekte","BP_Plan",
                geomColumn = "raeumlicherGeltungsbereich")

            if bpPlanLayer == None:
                return None

            bpBereichLayer = self.getLayerForTable(
                "BP_Basisobjekte","BP_Bereich",
                geomColumn = "geltungsbereich")

            if bpBereichLayer != None:
                bpPlaene = {}
                bpFids = {}
                planGidField = bpPlanLayer.fields().lookupField("gid")

                for bpPlanFeat in self.tools.getFeatures(bpPlanLayer):
                    bpPlaene[bpPlanFeat[planGidField]] = []
                    bpFids[bpPlanFeat[planGidField]] = bpPlanFeat.id()

                if len(bpPlaene) > 0:
                    if self.tools.setEditable(bpPlanLayer, True, self.iface):
                        bpBereichLayer.selectAll()
                        gehoertZuPlanFld = bpBereichLayer.fields().lookupField("gehoertZuPlan")

                        for bereichFeat in self.tools.getFeatures(bpBereichLayer):
                            bpPlanId = bereichFeat[gehoertZuPlanFld]

                            if bpPlanId in bpPlaene:
                                bereichGeom = QgsGeometry(bereichFeat.geometry())

                                if not bereichGeom.isNull():
                                    bpPlaene[bpPlanId].append(bereichGeom)

                        bpBereichLayer.invertSelection()
                        bpPlanLayer.beginEditCommand(u"XPlan: räumliche Geltungsbereiche erneuert")

                        for gid, geomList in list(bpPlaene.items()):
                            if len(geomList) == 0:
                                continue

                            fid = bpFids[gid]
                            first = True
                            for aGeom in geomList:
                                if first:
                                    outGeom = aGeom
                                    first = False
                                else:
                                    outGeom = QgsGeometry(outGeom.combine(aGeom))

                            bpPlanLayer.changeGeometry(fid, outGeom)
                        bpPlanLayer.endEditCommand()

    def referenzmanagerStarten(self):
        if self.db == None:
            self.initialize(False)

        if self.db != None:
            refSchema = "XP_Basisobjekte"
            refTable = "XP_ExterneReferenz"
            extRefLayer = self.getLayerForTable(refSchema, refTable)

            if extRefLayer != None:
                self.app.xpManager.moveLayerToGroup(extRefLayer, refSchema)
                dlg = ReferenzmanagerDialog(self, extRefLayer)
                dlg.show()
                dlg.exec_()

    def onLayerDestroyed(self, layer):
        '''Slot, der aufgerufen wird wenn ein XP-Layer aus dem Projekt entfernt wird
        erst in QGIS3 wird das Layerobjekt übergeben'''

        try:
            self.xpLayers.pop(layer.id())
        except:
            pass

        try:
            self.displayLayers.pop(layer.id())
        except:
            pass


    def onLayerLayerDeleted(self):
        self.layerLayer = None

    def setSettings(self):
        dlg = XPlanungConf(self.dbHandler, self.tools)
        dlg.show()
        result = dlg.exec_()

        if result == 1:
            self.initialize()

    def initializeAllLayers(self, layerCheck = True):
        allLayerIds = []

        for aLayerTreeLayer in QgsProject.instance().layerTreeRoot().findLayers():
            allLayerIds.append(aLayerTreeLayer.layer().id())

        # entfernte Layer aus Dicts entfernen
        if len(self.xpLayers) > 0:
            removeXp = []

            for aLayerId, value in list(self.xpLayers.items()):
                if allLayerIds.count(aLayerId) == 0:
                    removeXp.append(aLayerId)

            for aLayerId in removeXp:
                self.xpLayers.pop(aLayerId)

        if len(self.displayLayers) > 0:
            removeDisp = []

            for aLayerId, value in list(self.displayLayers.items()):
                if allLayerIds.count(aLayerId) == 0:
                    removeDisp.append(aLayerId)

            for aLayerId in removeDisp:
                self.displayLayers.pop(aLayerId)

        for aLayerTreeLayer in QgsProject.instance().layerTreeRoot().findLayers():
            self.layerInitialize(aLayerTreeLayer.layer(), layerCheck = layerCheck)

    def initialize(self,  aktiveBereiche = True):
        self.db = self.dbHandler.dbConnect()

        if self.db != None:
            # implementedSchemas feststellen
            query = QtSql.QSqlQuery(self.db)
            query.prepare("SELECT substr(nspname,0,3) \
                        FROM pg_namespace \
                        WHERE nspname ILIKE \'%Basisobjekte%\' \
                        ORDER BY nspname;")
            query.exec_()

            if query.isActive():
                while query.next():
                    self.implementedSchemas.append(query.value(0))

                query.finish()
            else:
                self.showQueryError(query)

            if not self.tools.isXpDb(self.db):
                XpError(u"Die konfigurierte Datenbank ist keine XPlan-Datenbank. Bitte " +\
                u"konfigurieren Sie eine solche und initialisieren " +\
                u"Sie dann erneut.", self.iface)
                self.dbHandler.dbDisconnect(self.db)
                self.db = None
                self.setSettings()
            else:
                if aktiveBereiche:
                    self.aktiveBereicheFestlegen()

    def loadObjektart(self, objektart):
        if self.db == None:
            self.initialize(False)

        if self.db != None:
            dlg = ChooseObjektart(objektart, self.db, self.aktiveBereiche)
            dlg.show()
            result = dlg.exec_()

            if result == 1:
                withDisplay = dlg.withDisplay
                nurAktiveBereiche = dlg.aktiveBereiche

                if nurAktiveBereiche:
                    if len(self.aktiveBereiche) == 0:
                        if self.aktiveBereicheFestlegen():
                            if len(self.aktiveBereiche) == 0:
                                nurAktiveBereiche = False

                    aktiveBereiche = self.aktiveBereicheGids()

                for aSel in dlg.selection:
                    schemaName = aSel[0]
                    tableName = aSel[1]
                    geomColumn = aSel[2]
                    description = aSel[3]
                    displayName = tableName + " (editierbar)"
                    editLayer, isView = self.loadTable(schemaName, tableName,
                        geomColumn, displayName = displayName)

                    if editLayer != None:
                        self.app.xpManager.moveLayerToGroup(editLayer, schemaName)
                        editLayer.setAbstract(description)
                        stile = self.tools.getLayerStyles(self.db,
                            editLayer, schemaName, tableName)

                        if stile != None:
                            self.tools.applyStyles(editLayer, stile)
                            self.tools.useStyle(editLayer, self.simpleStyleName)

                        if not isView:
                            ddInit = self.layerInitialize(editLayer,
                                layerCheck = self.willAktivenBereich)

                            if ddInit:
                                self.app.xpManager.addAction(editLayer,
                                    actionName = "XP_Sachdaten",
                                    ddManagerName = "xpManager")

                            if nurAktiveBereiche:
                                self.layerFilterBereich(editLayer, aktiveBereiche)

                            if tableName == "BP_BaugebietsTeilFlaeche":
                                self.tools.createAction(editLayer, "Nutzungsschablone plazieren",
                                    "app=QgsApplication.instance();app.xpPlugin.plaziereNutzungsschablone(" +\
                                        "[%gid%],[% x( $geometry )%],[% y( $geometry )%]);")

                            if withDisplay:
                                displayName = tableName + " (Darst.)"
                                displayLayer, isView = self.loadTable(schemaName, tableName + "_qv",
                                    geomColumn, displayName = displayName)

                                if displayLayer == None:
                                    self.debug("displayLayer == None")
                                    # lade Layer als Darstelllungsvariante
                                    # eigene Darstellungsvarianten gibt es nur, wenn nötig
                                    displayLayer, isView = self.loadTable(schemaName, tableName,
                                        geomColumn, displayName = displayName)

                                if displayLayer != None:
                                    if nurAktiveBereiche:
                                        self.layerFilterBereich(displayLayer, aktiveBereiche)

                                    self.app.xpManager.moveLayerToGroup(displayLayer, schemaName)

                                    if stile != None:
                                        self.tools.applyStyles(displayLayer, stile)
                                        stil = self.tools.chooseStyle(displayLayer)

                                        if stil != None:
                                            self.tools.useStyle(displayLayer, stil)

                                    self.displayLayers[displayLayer.id()] = [displayLayer, None, None, nurAktiveBereiche]

    def loadTable(self,  schemaName, tableName, geomColumn,
            displayName = None, filter = None):
        '''eine Relation als Layer laden'''

        thisLayer = None

        if displayName == None:
            displayName = tableName

        if self.db != None:
            ddTable = self.app.xpManager.createDdTable(self.db,
                schemaName, tableName, withOid = False,
                withComment = False)

            isView = ddTable == None

            if isView:
                ddTable = DdTable(schemaName = schemaName, tableName = tableName)

            if self.app.xpManager.existsInDb(ddTable, self.db):
                thisLayer = self.app.xpManager.loadPostGISLayer(self.db,
                    ddTable, displayName = displayName,
                    geomColumn = geomColumn, keyColumn = "gid",
                    whereClause = filter,  intoDdGroup = False)

        return [thisLayer, isView]

    def loadXP(self):
        self.loadObjektart("XP")

    def loadBP(self):
        self.loadObjektart("BP")

    def loadFP(self):
        self.loadObjektart("FP")

    def loadLP(self):
        self.loadObjektart("LP")

    def loadRP(self):
        self.loadObjektart("RP")

    def loadSO(self):
        self.loadObjektart("SO")

    def aktiveBereicheGids(self):
        bereiche = []

        for aKey, aValue in list(self.aktiveBereiche.items()):
            bereiche.append(aKey)

        return bereiche

    def aktiveBereicheFestlegen(self):
        '''Auswahl der Bereiche, in die neu gezeichnete Elemente eingefügt werden sollen'''
        if self.db == None:
            self.initialize(False)

        if self.db:
            bereichsAuswahl = self.tools.chooseBereich(self.db,  True,  u"Aktive Bereiche festlegen")

            if len(bereichsAuswahl) > 0: # Auswahl wurde getroffen oder es wurde abgebrochen
                try:
                    bereichsAuswahl[-1] #Abbruch; bisherigen aktive Bereiche bleiben aktiv
                    return None
                except KeyError:
                    self.aktiveBereiche = bereichsAuswahl

                self.willAktivenBereich = True

                if self.gehoertZuLayer == None:
                   self.createBereichZuordnungsLayer()

                self.initializeAllLayers()
            else:
                self.aktiveBereiche = bereichsAuswahl # keine Auswahl => keine aktiven Bereiche

        return True
    


    def layerInitializeSlot(self):
        layer = self.iface.activeLayer()

        if layer != None:
            if self.db == None:
                self.initialize(False)
            self.layerInitialize(layer)
            self.app.xpManager.addAction(layer, actionName = "XP_Sachdaten",
                ddManagerName = "xpManager")
            self.iface.mapCanvas().refresh() # neuzeichnen

    def deleteStyleSlot(self):
        layer = self.iface.activeLayer()

        if layer == None:
            return None

        if self.layerLayer == None:
            if not self.loadLayerLayer():
                return None

        if self.db == None:
            self.initialize(False)

        styleMan = layer.styleManager()
        bereich = styleMan.currentStyle()

        if bereich == u"":
            return None

        relation = self.tools.getPostgresRelation(layer)
        schemaName = relation[0]
        tableName = relation[1]
        stilId = self.getStyleId(schemaName, tableName, bereich)

        if stilId != None: # Eintrag löschen
            feat = QgsFeature()

            if self.layerLayer.getFeatures(
                    QgsFeatureRequest().setFilterFid(stilId).setFlags(
                    QgsFeatureRequest.NoGeometry)).nextFeature(feat):
                if self.tools.setEditable(self.layerLayer):
                    if self.layerLayer.deleteFeature(stilId):
                        if self.layerLayer.commitChanges():
                            self.tools.showInfo("XPlanung",
                                u"Stil " + bereich + u" gelöscht",)
                        else:
                            XpError(u"Konnte Änderungen an " + \
                                self.layerLayer.name() + u"nicht speichern!",
                                self.iface)

    def saveStyleSlot(self):
        layer = self.iface.activeLayer()

        if layer == None:
            return None

        if self.db == None:
            self.initialize(False)

        if self.layerLayer == None:
            if not self.loadLayerLayer():
                return None

        styleMan = layer.styleManager()
        bereich = styleMan.currentStyle()

        if bereich == u"":
            bereich = self.standardName

        relation = self.tools.getPostgresRelation(layer)
        schemaName = relation[0]
        tableName = relation[1]
        tableName = tableName.replace("_qv", "")
        stilId = self.getStyleId(schemaName, tableName, bereich)
        self.app.xpManager.removeAction(layer, actionName = "XP_Sachdaten")
        doc = self.tools.getXmlLayerStyle(layer)

        if doc != None:
            if stilId != None: # Eintrag ändern
                reply = QtWidgets.QMessageBox.question(
                    None, u"Stil vorhanden",
                    u"Vorhandenen Stil für Bereich %s ersetzen?" % bereich,
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel,
                    defaultButton = QtWidgets.QMessageBox.No)

                if reply == QtWidgets.QMessageBox.Yes:
                    changeStyle = True
                elif reply == QtWidgets.QMessageBox.No:
                    changeStyle = False
                else:
                    return None
            else:
                changeStyle = False

            if changeStyle:
                feat = QgsFeature()

                if self.layerLayer.getFeatures(
                        QgsFeatureRequest().setFilterFid(stilId).setFlags(
                        QgsFeatureRequest.NoGeometry)).nextFeature(feat):
                    feat[self.layerLayer.fields().lookupField("style")] = doc.toString()

                    if self.app.xpManager.showFeatureForm(
                            self.layerLayer, feat) != 0:
                        if self.tools.setEditable(self.layerLayer):
                            self.layerLayer.changeAttributeValue(
                                stilId, self.layerLayer.fields().lookupField("style"),
                                doc.toString())
                            if not self.layerLayer.commitChanges():
                                XpError(u"Konnte Änderungen an " + \
                                self.layerLayer.name() + u"nicht speichern!",
                                self.iface)
            else: # neuer Eintrag
                newFeat = self.tools.createFeature(self.layerLayer)
                # füge den neuen Stil in das Feature ein
                newFeat[self.layerLayer.fields().lookupField("style")] = doc.toString()
                # vergebe eine Fake-Id, damit kein Fehler kommt, id wird aus Sequenz vergeben
                newFeat[self.layerLayer.fields().lookupField("id")] = 1
                newFeat[self.layerLayer.fields().lookupField("schemaname")] = schemaName
                newFeat[self.layerLayer.fields().lookupField("tablename")] = tableName

                if self.tools.setEditable(self.layerLayer, True, self.iface):
                    if self.layerLayer.addFeature(newFeat):
                        self.app.xpManager.showFeatureForm(
                            self.layerLayer, newFeat, askForSave = False)

        self.app.xpManager.addAction(layer, actionName = "XP_Sachdaten",
            ddManagerName = "xpManager")

    def layerMultiEditSlot(self):
        layer = self.iface.activeLayer()

        if layer != None:
            sel = layer.selectedFeatures()

            if len(sel) > 0:
                self.app.xpManager.showFeatureForm(layer, sel[0], multiEdit = True)

    def layerStyleSlot(self):
        layer = self.iface.activeLayer()

        if layer != None:

            if self.db == None:
                self.initialize(False)

            if self.layerInitialize(layer):
                stil = self.tools.chooseStyle(layer)

                if stil != None:
                    self.tools.useStyle(layer, stil)

    def getLayerForTable(self, schemaName, tableName,
        geomColumn = None, showMsg = True):
        '''Den Layer schemaName.tableName finden bzw. laden.
        Wenn geomColumn == None wird geoemtrielos geladen'''

        ddTable = self.app.xpManager.createDdTable(
            self.db, schemaName, tableName,
            withOid = False, withComment = False)

        if ddTable != None:
            layer = self.app.xpManager.findPostgresLayer(
                self.db, ddTable)

            if layer == None:
                layer = self.loadTable(schemaName, tableName,
                    geomColumn = geomColumn)[0]

                if layer == None:
                    if showMsg:
                        XpError(u"Kann Tabelle %(schema)s.%(table)s nicht laden!" % \
                            {"schema":schemaName, "table":tableName},
                            self.iface)
                    return None
                else:
                    return layer
            else:
                return layer
        else:
            if showMsg:
                XpError(u"Kann ddTable %(schema)s.%(table)s nicht erzeugen!" % \
                    {"schema":schemaName, "table":tableName},
                    self.iface)
            return None

    def layerInitialize(self,  layer,  msg = False,  layerCheck = True):
        '''einen XP_Layer initialisieren, gibt Boolschen Wert zurück'''
        ddInit = False

        if 0 == layer.type(): # Vektorlayer
            layerRelation = self.tools.getPostgresRelation(layer)

            if layerRelation != None: # PostgreSQL-Layer
                schema = layerRelation[0]
                table = layerRelation[1]

                if table[:3] in ["XP_", "BP_", "FP_", "LP_", "RP_", "SO_"]:
                    if layer.name().find("(editierbar)") != -1:
                        try:
                            return self.xpLayers[layer.id()] != None
                        except:
                            pass
                    elif layer.name().find("(Darst.)") != -1:
                        try:
                            return self.displayLayers[layer.id()] != None
                        except:
                            pass
                    else:
                        return False

                    if table[len(table) -3:] != "_qv":
                        try:
                            self.app.xpManager.ddLayers[layer.id()] # bereits initialisiert
                            ddInit = True
                        except KeyError:
                            ddInit = self.app.xpManager.initLayer(layer,  skip = [], createAction = False,  db = self.db)

                        if layerRelation[2]: # Layer hat Geometrien
                            schemaTyp = schema[:2]

                            if table != schemaTyp + "_Plan" and table != schemaTyp + "_Bereich":
                                if schema != "XP_Praesentationsobjekte":
                                    if self.implementedSchemas.count(schemaTyp) > 0:
                                        if layerCheck:
                                            self.aktiverBereichLayerCheck(layer)

                                # disconnect slots in case they are already connected
                                try:
                                    layer.committedFeaturesAdded.disconnect(self.onCommitedFeaturesAdded)
                                except:
                                    pass

                                try:
                                    layer.editingStopped.disconnect(self.onEditingStopped)
                                except:
                                    pass

                                try:
                                    layer.editingStarted.disconnect(self.onEditingStarted)
                                except:
                                    pass

                                try:
                                    layer.destroyed.disconnect(self.onLayerDestroyed)
                                except:
                                    pass

                                layer.committedFeaturesAdded.connect(self.onCommitedFeaturesAdded)
                                layer.editingStopped.connect(self.onEditingStopped)
                                layer.editingStarted.connect(self.onEditingStarted)
                                layer.destroyed.connect(self.onLayerDestroyed)
                                self.xpLayers[layer.id()] = [layer, None, False, False]
                    else:
                        self.displayLayers[layer.id()] = [layer,  None, None, False]
            else:
                if msg:
                    XpError("Der Layer " + layer.name() + " ist kein PostgreSQL-Layer!",
                        self.iface)
        else: # not a vector layer
            if msg:
                XpError("Der Layer " + layer.name() + " ist kein VektorLayer!",
                    self.iface)

        return ddInit

    def layerFilterBereich(self, layer, bereiche):
        ''' wende einen Filter auf layer an, so dass nur Objekte in bereiche dargestellt werden'''

        if len(bereiche) > 0:
            relation = self.tools.getPostgresRelation(layer)

            if relation != None:
                schemaName = relation[0]
                relName = relation[1]
                filter = self.getBereichFilter(schemaName, relName, bereiche)

                if layer.setSubsetString(filter):
                    layer.reload()
                    layerId = layer.id()

                    try:
                        self.xpLayers[layerId][3] = True
                    except:
                        self.displayLayers[layerId][3] = True

    def layerFilterRemove(self, layer):

        layerId = layer.id()

        if layer.setSubsetString(""):
            layer.reload()

            try:
                self.xpLayers[layerId][3] = False
            except:
                self.displayLayers[layerId][3] = False

            return True
        else:
            return False

    def aktiverBereichLayerCheck(self,  layer):
        '''
        Prüfung, ob übergebener Layer Präsentationsobjekt oder XP_Objekt ist und ob es aktive Bereiche gibt
        0 = kein passender Layer oder kein aktiver Bereich
        1 = XP_Objekt und aktiver Bereich
        2 = Päsentationsobjekt
        '''

        retValue = 0
        layerRelation = self.tools.getPostgresRelation(layer)

        if layerRelation != None: #  PostgreSQL-Layer
            if layerRelation[2]: # Geometrielayer
                schema = layerRelation[0]

                while(True):
                    if len(self.aktiveBereiche) == 0 and self.willAktivenBereich:
                        thisChoice = QtWidgets.QMessageBox.question(None, "Keine aktiven Bereiche",
                            u"Wollen Sie aktive Bereiche festlegen? ",
                            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)

                        if thisChoice == QtWidgets.QMessageBox.Yes:
                            self.aktiveBereicheFestlegen()
                        else:
                            self.willAktivenBereich = False
                            break

                    if len(self.aktiveBereiche) > 0:
                        if schema == "XP_Praesentationsobjekte":
                            retValue = 2
                        else:
                            retValue = 1

                        break

        return retValue

    def createBereichZuordnungsLayer(self):
        self.gehoertZuLayer = self.getLayerForTable(
            "XP_Basisobjekte", "XP_Objekt_gehoertZuBereich")

        if self.gehoertZuLayer != None:
            self.gehoertZuLayer.destroyed.connect(self.onGehoertZuLayerDeleted)

    def bereichsmanagerStartenSlot(self):
        if self.db == None:
            self.initialize(False)

        self.willAktivenBereich = False
         # Nicht unterwegs nach aktiven Bereichen fragen, sondern nur den Bereichsmanager starten
        self.initializeAllLayers(layerCheck = False)
        dlg = BereichsmanagerDialog(self)
        dlg.show()
        dlg.exec_()

    def aktiveBereicheFiltern(self, layer):
        layerCheck = self.aktiverBereichLayerCheck(layer)

        if layerCheck >= 1: # XP_Objekt und aktiver Bereich oder Präsentationsobjekt
            bereiche = self.aktiveBereicheGids()
            self.layerFilterBereich(layer, bereiche)

    def aktivenBereichenZuordnenSlot(self):
        layer = self.iface.activeLayer()

        if layer == None:
            self.tools.noActiveLayerWarning()
        else:
            self.willAktivenBereich = True
            self.aktivenBereichenZuordnen(layer)

    def aktivenBereichenZuordnen(self,  layer):
        '''fügt alle ausgewählten Features im übergebenen Layer den aktiven Bereichen zu
        Rückgabe: Bool (Erfolg)'''
        if self.db == None:
            self.initialize()

        if self.db:
            checkResult = self.aktiverBereichLayerCheck(layer)

            if checkResult == 1:
                if not self.tools.setEditable(self.gehoertZuLayer, True, self.iface):
                    return False

                if len(layer.selectedFeatureIds()) == 0:
                    XpError(u"Bereichszuordnung: Der Layer " + layer.name() + u" hat keine Auswahl!",
                        self.iface)
                    return False

                bereichFld = self.gehoertZuLayer.fields().lookupField("gehoertZuBereich")
                objektFld = self.gehoertZuLayer.fields().lookupField("XP_Objekt_gid")

                gids = self.tools.getSelectedFeaturesGids(layer)

                if gids == []:
                    return False
                else:
                    bereitsZugeordnet = self.tools.getBereicheFuerFeatures(self.db,  gids)

                self.gehoertZuLayer.beginEditCommand(
                    u"Ausgewählte Features von " + layer.name() + u" den aktiven Bereichen zugeordnet.")
                newFeat = None #ini
                zugeordnet = 0 # Zähler

                for aGid in gids:
                    for aBereichGid in list(self.aktiveBereiche.keys()):
                        doInsert = True
                        #prüfen, ob dieses XP_Objekt bereits diesem XP_Bereich zugewiesen ist
                        try:
                            objektBereiche = bereitsZugeordnet[aGid]
                        except KeyError:
                            objektBereiche = []

                        for objektBereich in objektBereiche:
                            if objektBereich == aBereichGid:
                                doInsert = False
                                break

                        if doInsert:
                            newFeat = self.tools.createFeature(self.gehoertZuLayer)
                            self.gehoertZuLayer.addFeature(newFeat)
                            self.gehoertZuLayer.changeAttributeValue(newFeat.id(),  bereichFld, aBereichGid)
                            self.gehoertZuLayer.changeAttributeValue(newFeat.id(),  objektFld, aGid)
                            zugeordnet += 1

                if newFeat == None: # keine neuen Einträge
                    self.gehoertZuLayer.destroyEditCommand()
                    self.gehoertZuLayer.rollBack()

                    if aGid < 0:
                        return False
                    else:
                        self.tools.showInfo(u"Alle Objekte waren bereits zugeordnet")
                        return True
                else:
                    self.gehoertZuLayer.endEditCommand()

                    if not self.gehoertZuLayer.commitChanges():
                        self.tools.showError(u"Konnte Änderungen an " + self.gehoertZuLayer.name() + " nicht speichern!")
                        return False
                    else:
                        if zugeordnet == 1:
                            infoMsg = u"Ein Objekt "
                        else:
                            infoMsg = str(zugeordnet) + u" Objekte "

                        infoMsg += "im Layer " + layer.name() + " "

                        if len(self.aktiveBereiche) == 1:
                            infoMsg += u"dem Bereich " + self.aktiveBereiche[aBereichGid]
                        else:
                            infoMsg += str(len(self.aktiveBereiche)) + u" Bereichen"

                        infoMsg += u" zugeordnet"
                        self.tools.showInfo(infoMsg)
                        return True
            elif checkResult == 2: # Präsentationsobjekt
                return self.apoGehoertZuBereichFuellen(layer)
            else:
                return False
        else:
                return False

    def apoGehoertZuBereichFuellen(self, layer):
        '''
        Präsentationsobjekte können nur in einem Bereich sein, dafür gibt es das Feld
        XP_AbstraktesPraesentationsobjekt.gehoertZuBereich; es wird hier gefüllt,
        wenn aktive Bereiche festgelegt wurden.
        '''

        if len(self.aktiveBereiche) == 0:
            self.tools.showWarning(u"Keine aktiven Bereiche festgelegt")
            return False
        elif len(self.aktiveBereiche) > 1:
            self.tools.showError(u"Präsentationsobjekte können nur einem Bereich zugeordnet werden!")
            return False
        else:
            for k in list(self.aktiveBereiche.keys()):
                bereichGid = k

            apoLayer = self.getLayerForTable("XP_Praesentationsobjekte",
                "XP_AbstraktesPraesentationsobjekt")

            if apoLayer != None:
                if not self.tools.setEditable(apoLayer, True):
                    return False
                else:
                    fldIdx = apoLayer.fields().lookupField("gehoertZuBereich")
                    gids = self.tools.intListToString(self.tools.getSelectedFeaturesGids(layer))
                    request = QgsFeatureRequest()
                    request.setFilterExpression("gid IN (" + gids + ")")
                    zugeordnet = 0

                    for aFeat in apoLayer.getFeatures(request):
                        if apoLayer.changeAttributeValue(aFeat.id(), fldIdx, bereichGid):
                            zugeordnet += 1
                        else:
                            self.tools.showError(u"Konnte XP_AbstraktesPraesentationsobjekt.gehoertZuBereich nicht ändern!")
                            apoLayer.rollBack()
                            return False

                    if not apoLayer.commitChanges():
                        self.tools.showError(u"Konnte Layer XP_AbstraktesPraesentationsobjekt nicht speichern")
                        return False
                    else:
                        if zugeordnet == 1:
                            infoMsg = u"Ein Objekt "
                        else:
                            infoMsg = str(zugeordnet) + u" Objekte "

                        infoMsg += "im Layer " + layer.name() + " "
                        infoMsg += u"dem Bereich " + self.aktiveBereiche[bereichGid]
                        infoMsg += u" zugeordnet"
                        self.tools.showInfo(infoMsg)
                        return True
            else:
                return False

    def getBereichFilter(self, aSchemaName, aRelName, bereiche):
        ''' einen passenden Filter für aSchemaName.aRelName machen,
        der nur Objekte aus bereiche lädt'''
        sBereiche = self.tools.intListToString(bereiche)

        if aSchemaName == "XP_Praesentationsobjekte":
            filter = "gid IN (SELECT \"gid\" " + \
                    "FROM \"XP_Praesentationsobjekte\".\"XP_AbstraktesPraesentationsobjekt\" " + \
                    "WHERE \"gehoertZuBereich\" IN (" + sBereiche + "))"
        else:
            if aRelName[3:] == "Bereich":
                filter = "gid IN (" + sBereiche + ")"
            else:
                filter = "gid IN (SELECT \"XP_Objekt_gid\" " + \
                    "FROM \"XP_Basisobjekte\".\"XP_Objekt_gehoertZuBereich\" " + \
                    "WHERE \"gehoertZuBereich\" IN (" + sBereiche + "))"

        return filter

    def bereichLaden(self):
        '''Laden aller Layer, die Elemente in einem auszuwählenden Bereich haben'''
        if self.db == None:
            self.db = self.dbHandler.dbConnect()

        if self.db:
            bereichDict = self.tools.chooseBereich(self.db)

            if len(bereichDict) > 0:
                for k in list(bereichDict.keys()):
                    bereich = k
                    break

                if bereich >= 0:
                    bereichTyp = self.tools.getBereichTyp(self.db,  bereich)
                    # rausbekommen, welche Layer Elemente im Bereich haben, auch nachrichtlich
                    layers = self.tools.getLayerInBereich(self.db, [bereich])

                    if len(layers) == 0:
                        self.tools.showWarning(
                            u"In diesem Bereich sind keine Objekte vorhanden!")
                        return None
                    else: # den Bereich selbst reintun
                        layers[2][bereichTyp + "_Basisobjekte"] = [bereichTyp + "_Bereich"]

                    # Layer in die Gruppe laden und features entsprechend einschränken
                    for aLayerType in layers:
                        for aKey in list(aLayerType.keys()):
                            for aRelName in aLayerType[aKey]:
                                filter = self.getBereichFilter(aKey, aRelName, [bereich])

                                # lade view, falls vorhanden
                                if aRelName == bereichTyp + "_Bereich":
                                    geomFld = "geltungsbereich"
                                else:
                                    geomFld = "position"

                                displayName = aRelName + " (" + bereichDict[bereich] + ")"
                                aLayer, isView = self.loadTable(aKey, aRelName + "_qv",  geomFld,
                                    displayName = displayName, filter = filter)

                                if aLayer == None:
                                    # lade Tabelle
                                    aLayer, isView = self.loadTable(aKey, aRelName,  geomFld,
                                        displayName = displayName, filter = filter)

                                if aLayer != None:
                                    # Stil des Layers aus der DB holen und anwenden
                                    stile = self.tools.getLayerStyles(self.db,
                                        aLayer, aKey, aRelName)

                                    if stile != None:
                                        self.tools.applyStyles(aLayer, stile)
                                        self.tools.useStyle(aLayer, bereichDict[bereich])

                                    self.app.xpManager.moveLayerToGroup(aLayer, bereichDict[bereich])
                                    self.tools.setLayerVisible(aLayer,  True)
            self.iface.mapCanvas().refresh() # neuzeichnen

    def onEditingStarted(self):
        if len(self.aktiveBereiche) > 0:
            for aLayerTreeLayer in QgsProject.instance().layerTreeRoot().findLayers():
                layer = aLayerTreeLayer.layer()
                layerId = layer.id()

                try:
                    self.xpLayers[layerId]
                except:
                    continue

                layerRelation = self.tools.getPostgresRelation(layer)

                if layerRelation != None: # PostgreSQL-Layer
                    schema = layerRelation[0]
                    table = layerRelation[1]
                    maxGid = self.tools.getMaxGid(self.db, schema, table)
                    self.xpLayers[layerId][1] = maxGid
                    self.xpLayers[layerId][2] = False

    def onEditingStopped(self):
        if len(self.aktiveBereiche) > 0:
            for aLayerTreeLayer in QgsProject.instance().layerTreeRoot().findLayers():
                layer = aLayerTreeLayer.layer()
                layerId = layer.id()

                try:
                    hasChanges = self.xpLayers[layerId][2]

                    if hasChanges and not layer.isEditable():
                        # layer.isEditable() = True für diesen Layer wurde das Editieren nicht beendet
                        maxGid = self.xpLayers[layerId][1]

                        if maxGid == None: # Fehler bei Ermittlung der maxGid
                            continue

                        layerFilter = layer.subsetString()

                        if layerFilter != "":
                            layer.setSubsetString("")
                            # Filter ausschalten, denn sonst werden ja nicht alle Objekte geladen

                        layer.reload() # damit alle Objekte und neue gids geladen werden
                        newIds = []
                        request = QgsFeatureRequest()
                        request.setFilterExpression("gid > " + str(maxGid))

                        for aNewFeat in layer.getFeatures(request):
                            newIds.append(aNewFeat.id())

                        layer.select(newIds)

                        if layer.selectedFeatureCount() > 0:
                            if not self.aktivenBereichenZuordnen(layer):
                                if self.gehoertZuLayer == None:
                                    XpError("Layer XP_Objekt_gehoertZu_XP_Bereich nicht (mehr) vorhanden",
                                        self.iface)

                            layer.removeSelection()

                        layer.setSubsetString(layerFilter) # Filter wieder aktivieren
                except:
                    continue

        self.iface.mapCanvas().refresh() # neuzeichnen

    def onGehoertZuLayerDeleted(self): # Slot
        self.gehoertZuLayer = None

    def onCommitedFeaturesAdded(self,  layerId,  featureList):
        '''
        Slot der aufgerufen wird, wenn neue Features in einen XP-Layer eingefügt werden
        wird vor editingStopped aufgerufen
        '''

        try:
            self.xpLayers[layerId][2] = True
        except:
            XpError(u"Fehler in xpLayers, layerId " + layerId + " nicht gefunden!",
                self.iface)

    def showQueryError(self, query):
        self.tools.showQueryError(query)
