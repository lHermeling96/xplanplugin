﻿# -*- coding: utf-8 -*-
"""
/***************************************************************************
XPlan
A QGIS plugin
Fachschale XPlan für XPlanung
                             -------------------
begin                : 2011-03-08
copyright            : (C) 2011 by Bernhard Stroebl, KIJ/DV
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
# Import the PyQt and QGIS libraries
from PyQt4 import QtCore, QtGui, QtSql,  QtXml
# Initialize Qt resources from file resources.py
from qgis.core import *
from qgis.gui import *
from XPlanDialog import BereichsauswahlDialog

class XPTools():
    def __init__(self,  iface):
        self.iface = iface
    
    def chooseBereich(self,  db):
        '''Starte Dialog zur Bereichsauswahl'''
        dlg = BereichsauswahlDialog(self.iface,  db)
        dlg.show()
        return dlg.exec_()
        
    def getBereichTyp(self,  db,  bereichGid):
        '''gibt den Typ (FP, BP etc) des Bereichs mit der übergebenen gid zurück'''
        sel = "SELECT substring(\"Objektart\",1,2) FROM \"XP_Basisobjekte\".\"XP_Bereiche\" WHERE gid = :bereichGid"
        query = QtSql.QSqlQuery(db)
        query.prepare(sel)
        query.bindValue(":bereichGid", QtCore.QVariant(bereichGid))
        query.exec_()

        if query.isActive():

            while query.next(): # returns false when all records are done
                bereichTyp = query.value(0).toString()
            
            query.finish()
            return bereichTyp
        else:
            self.showQueryError(query)
            query.finish()
            return None
        
    def getLayerStyle(self,  db,  layer,  bereichGid = -9999):
        '''gibt den Style für einen Layers für den Bereich mit der übergebenen gid zurück,
        wenn es für diesen Bereich keinen Stil gibt, wird der allgemeine Stil zurückgegeben
        (XP_Bereich_gid = NULL), falls es den auch nicht gibt wird None zurückgegeben'''
        
        relation = self.getPostgresRelation(layer)
        style = None
        
        if relation: 
            sel = "SELECT style \
            FROM \"QGIS\".\"layer\" \
            WHERE schemaname = \':schema\' \
                AND tablename = \':table\' \
                AND (\"XP_Bereich_gid\" = :bereichGid \
                     OR \"XP_Bereich_gid\" IS NULL) \
             ORDER BY \"XP_Bereich_gid\" NULLS LAST" 
            query = QtSql.QSqlQuery(db)
            query.prepare(sel)
            query.bindValue(":schema", QtCore.QVariant(relation[0]))
            query.bindValue(":table", QtCore.QVariant(relation[1]))
            query.bindValue(":bereichGid", QtCore.QVariant(bereichGid))
            query.exec_()

            if query.isActive():

                while query.next(): # returns false when all records are done
                    style = query.value(0).toString()
                    break
                query.finish()
            else:
                self.showQueryError(query)
                query.finish()
        
        return style
    
    def getPostgresRelation(self,  layer):
        '''gibt die Relation [schema, relation] eines PostgreSQL-Layers zurück'''
        retValue = None

        if isinstance(layer, QgsVectorLayer):
            if layer.dataProvider().storageType().contains(QtCore.QString("PostgreSQL")):
                
                for s in ayer.source().split(" "):
                    if s.startsWith("table="):
                        retValue = s.remove("table=").split(".")
                        break
        
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
            END as typ FROM ( \
            SELECT DISTINCT \"Objektart\" \
            FROM \"" + bereichTyp +"_Basisobjekte\".\"" + bereichTyp + "_Objekte\" \
            WHERE \"XP_Bereich_gid\" = :bereichGid) foo"
            query = QtSql.QSqlQuery(db)
            query.prepare(sel)
            query.bindValue(":bereichGid", QtCore.QVariant(bereichGid))
            query.exec_()

            if query.isActive():
                punktLayer = []
                linienLayer = []
                flaechenLayer = []

                while query.next(): # returns false when all records are done
                    layer = query.value(0).toString()
                    art = query.value(1).toString()
                    
                    if art == QtCore.QString("Punkt"):
                        punktLayer.append(layer)
                    elif art == QtCore.QString("Linie"):
                        linienLayer.append(layer)
                    elif art == QtCore.QString("Flaeche"):
                        flaechenLayer.append(layer)
                
                query.finish()
                return [punktLayer,  linienLayer,  flaechenLayer]
        else:
            self.showQueryError(query)
            query.finish()
            return None                                         
    
    def findPostgresLayer(self, tableName, dbName, dbServer, aliasName = None):
        '''Finde einen PostgreSQL-Layer, mit Namen aliasName (optional)'''
        
        layerList = self.iface.legendInterface().layers()
        procLayer = None # ini

        for layer in layerList:
            if isinstance(layer, QgsVectorLayer):
                if layer.dataProvider().storageType().contains(QtCore.QString("PostgreSQL")):
                    src = layer.source()

                    if src.contains(tableName) and \
                        src.contains(dbName) and \
                        src.contains(dbServer):
                        
                        if aliasName:
                            if QtCore.QString(aliasName) != layer.name():
                                continue
                                
                        procLayer = layer
                        break
        
        return procLayer
    
    def loadPostGISLayer(self,  db, schemaName, tableName, displayName = None,
        geomColumn = QtCore.QString(), whereClause = None, keyColumn = None):
        '''Lade einen PostGIS-Layer aus der Datenbank db'''
        
        if not displayName:
            displayName = schemaName + "." + tableName

        uri = QgsDataSourceURI()
        thisPort = db.port()

        if thisPort == -1:
            thisPort = 5432

        # set host name, port, database name, username and password
        uri.setConnection(db.hostName(), str(thisPort), db.databaseName(), db.userName(), db.password())
        # set database schema, table name, geometry column and optionaly subset (WHERE clause)
        uri.setDataSource(schemaName, tableName, geomColumn)

        if whereClause:
            uri.setSql(whereClause)

        if keyColumn:
            uri.setKeyColumn(keyColumn)

        vlayer = QgsVectorLayer(uri.uri(), displayName, "postgres")
        QgsMapLayerRegistry.instance().addMapLayers([vlayer])
        return vlayer
    
    def styleLayer(self,  layer,  xmlStyle):
        '''wende den übergebenen Stil auf den übergebenen Layer an'''
        doc = QtXml.QDomDocument()

        if doc.setContent(xmlStyle):
            rootNode = doc.firstChildElement()
            if layer.readSymbology(rootNode, QtCore.QString("Fehler beim Anwenden")):

                if rootNode.hasAttributes():
                    attrs = rootNode.attributes()

                    if attrs.contains(QtCore.QString("minimumScale")):
                        minScaleAttr = attrs.namedItem(QtCore.QString("minimumScale"))
                        layer.setMinimumScale(float(minScaleAttr.nodeValue()))

                    if attrs.contains(QtCore.QString("maximumScale")):
                        maxScaleAttr = attrs.namedItem(QtCore.QString("maximumScale"))
                        layer.setMaximumScale(float(maxScaleAttr.nodeValue()))

                    if attrs.contains(QtCore.QString("hasScaleBasedVisibilityFlag")):
                        scaleBasedVisAttr = attrs.namedItem(QtCore.QString("hasScaleBasedVisibilityFlag"))
                        layer.toggleScaleBasedVisibility(scaleBasedVisAttr.nodeValue() == "1")
                return True
            else:
                return False
    
    def showQueryError(self, query):
        QtGui.QMessageBox.warning(None, "Database Error", \
            QtCore.QString("%1 \n %2").arg(query.lastError().text()).arg(query.lastQuery()))
