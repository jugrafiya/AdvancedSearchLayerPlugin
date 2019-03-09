import os, re, csv

from qgis.PyQt.uic import loadUiType
from qgis.PyQt.QtWidgets import QDialog, QAbstractItemView, QTableWidgetItem
from qgis.PyQt.QtCore import QThread

from qgis.core import QgsVectorLayer, Qgis, QgsProject, QgsMapLayer, QgsExpression, QgsFeatureRequest
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtWidgets import QDockWidget

from .searchWorker import Worker


FORM_CLASS, _ = loadUiType(os.path.join(
    os.path.dirname(__file__), 'Search_Custom_dockwidget_base.ui'))


class LayerSearchDialog(QDockWidget, FORM_CLASS):
    def __init__(self, iface, parent):
        '''Initialize the LayerSearch dialog box'''
        super(LayerSearchDialog, self).__init__(parent)
        self.setupUi(self)
        self.iface = iface
        self.canvas = iface.mapCanvas()

        # Notify us when vector items ared added and removed in QGIS
        QgsProject.instance().layersAdded.connect(self.updateLayers)
        QgsProject.instance().layersRemoved.connect(self.updateLayers)

        self.doneButton.clicked.connect(self.closeDialog)
        self.stopButton.clicked.connect(self.killWorker)
        self.searchButton.clicked.connect(self.runSearch)
        self.clearButton.clicked.connect(self.clearResults)
        self.layerListComboBox.activated.connect(self.layerSelected)
        self.searchFieldComboBox.addItems(['<All Fields>'])
        self.maxResults = 1500
        self.resultsTable.setSortingEnabled(False)
        self.resultsTable.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.comparisonItems=['Like','Equals','Starts With']
        self.comparisonComboBox.addItems(self.comparisonItems)
        self.resultsTable.itemSelectionChanged.connect(self.select_feature)
        self.worker = None
        self.findStringEdit.textChanged.connect(self.setSuggestionsSearch)
        self.autocompleteComboBox.setVisible(False)
        self.chooseType.addItems(['Predefined NGSC search','Choose from the Layer Panel'])
        self.chooseType.currentIndexChanged.connect(self.populateLayerListComboBox)  # populating information in the layer list from csv
        self.autocompleteComboBox.currentTextChanged.connect(self.setValueToSearch)  # event connected for setting value from drop down
        self.layerListComboBox.currentTextChanged.connect(self.selectedCSVLayerChange)   # call to method for loading the layer, only at drop down

    """
        The method set value to the search string text box,
        while selecting from Combbox
    """
    def setValueToSearch(self,ind):
        if self.changeTextInSuggestion:
            self.findStringEdit.setText(self.autocompleteComboBox.currentText())

    """
        This method set suggestions for drop down based
        on value from the search string.
    """

    def setSuggestionsSearch(self,text):

        # if string is empty or check box is not checked then the suggestion will be hidden
        if text=='' or not self.suggestionsChecked.isChecked():
            self.autocompleteComboBox.clear()
            self.autocompleteComboBox.setVisible(False)
        else:
            # get all distinct names from the data and display them in suggestions list
            self.changeTextInSuggestion=False;
            self.autocompleteComboBox.clear()
            self.autocompleteComboBox.setVisible(True)
            fieldName= self.searchFieldComboBox.currentText()
            expr = QgsExpression('"'+str(fieldName)+'" ilike \'%%%s%%\'' %text)  #expression to perform like operatore from column.
            # selectedLayer = self.layerListComboBox.currentIndex()
            selectedLayer = self.layerListComboBox.currentText()
            layers = [self.searchLayers[selectedLayer]]
            it = layers[0].getFeatures(QgsFeatureRequest(expr))
            ids = [i[fieldName] for i in it]
            self.autocompleteComboBox.addItems(set(ids))
            self.changeTextInSuggestion=True;


    def closeDialog(self):
        '''Close the dialog box when the Close button is pushed'''
        self.hide()

    def updateLayers(self):
        '''Called when a layer has been added or deleted in QGIS.
        It forces the dialog to reload.'''
        # Stop any existing search

        self.killWorker()
        if self.isVisible() and self.chooseType.currentIndex()==1:
            self.populateLayerListComboBox()
            self.clearResults()

    def select_feature(self):
        '''A feature has been selected from the list so we need to select
        and zoom to it'''
        if self.noSelection:
            # We do not want this event while data is being changed
            return
        # Deselect all selections
        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if layer.type() == QgsMapLayer.VectorLayer:
                layer.removeSelection()


        # Find the layer that was selected and select the feature in the layer
        selectedRow = self.resultsTable.currentRow()
        selectedLayer = self.results[selectedRow][0]
        selectedFeature = self.results[selectedRow][1]
        selectedLayer.selectByIds( [selectedFeature.id()] )
        selectedLayer.select(selectedFeature.id())
        # Zoom to the selected feature
        self.canvas.zoomToSelected(selectedLayer)

        # Checking, if the layer operational is not already in the layer panel. If it is not there,
        # then it will be added.
        all_layers=[layer.name() for layer in layers]
        if selectedLayer.name() not in all_layers:
            QgsProject.instance().addMapLayer(selectedLayer)


    def layerSelected(self):
        '''The user has made a selection so we need to initialize other
        parts of the dialog box'''
        self.initFieldList()


    def showEvent(self, event):
        '''The dialog is being shown. We need to initialize it.'''
        super(LayerSearchDialog, self).showEvent(event)
        self.populateLayerListComboBox()

    """
        This method is invoked in event, this prevents loading of all layers from csv at once
        and loads only layers that are required at that time.
    """
    def selectedCSVLayerChange(self,text):
        print (text)
        # iterating through csv to get path, and load only vector layer that is required
        with open(os.path.join(os.path.dirname(__file__), 'data.csv')) as csvfile:
            reader= csv.reader(csvfile,delimiter=",")
            for i,row in enumerate(reader):
                    if row[0]==text:

                        # index based searching and accessing of data for vector layer.
                        qgisveclayer=QgsVectorLayer(os.path.normpath(row[3]), 'NGSC Search - ' + row[1].strip(), "ogr")
                        if row[0] not in self.searchLayers:
                            self.searchLayers[row[0]]= qgisveclayer
                        # print (self.searchLayers)

    def populateLayerListComboBox(self):
        '''Find all the vector layers and add them to the layer list
        that the user can select. In addition the user can search on all
        layers or all selected layers.'''
        # layerlist = ['<All Layers>','<Selected Layers>']
        layerlist=[]
        self.searchLayers = {} # This is same size as layerlist

        # getting current index from choices, if type index=0 that means, it is
        # refering to the data from csv else from layer panel
        type_index=self.chooseType.currentIndex() # get current index from comboBox
        if type_index==0:
            with open(os.path.join(os.path.dirname(__file__), 'data.csv')) as csvfile:
                reader= csv.reader(csvfile,delimiter=",")
                for i,row in enumerate(reader):
                    #if row[3].endswith(".shp") : # restricts search to shp data only
                        layerlist.append(row[0])

        else:

            # reading through all the layers in the layer panel
            layers = QgsProject.instance().mapLayers().values()
            for layer in layers:
                if layer.type() == QgsMapLayer.VectorLayer:
                    layerlist.append(layer.name())
                    # self.searchLayers.append(layer)
                    self.searchLayers[layer.name()]= layer


        self.layerListComboBox.clear()
        self.layerListComboBox.addItems(layerlist)
        self.initFieldList()

    """
        This method updates the structure of the plugin, and
        defines the number of columns and header values for the columns,
        from the values in data.csv provided.

    """
    def updateTableStructure(self, display_field):

        type_index=self.chooseType.currentIndex() # get current index from type of search
        if display_field=="":  # if no value is given then it will use default behavior
            self.resultsTable.setHorizontalHeaderLabels(['Value','Layer','Field','Feature Id'])
            self.display_field_list=[]
            return
        if type_index==0:  # show column from the csv's column

            self.display_field_list=display_field.split("^^") #use ^^ as seperator as failsafe
            self.resultsTable.setColumnCount(len(self.display_field_list))
            self.resultsTable.setHorizontalHeaderLabels(self.display_field_list)
        else:  # for layers from layer panel, it will show all the columns.
            # selectedLayer = self.layerListComboBox.currentIndex()
            selectedLayer = self.layerListComboBox.currentText()
            self.searchFieldComboBox.setEnabled(True)
            for field in self.searchLayers[selectedLayer].fields():
                self.searchFieldComboBox.addItem(field.name())
            self.display_field_list=[field.name() for field in self.searchLayers[selectedLayer].fields()]
            self.resultsTable.setColumnCount(len(self.display_field_list))
            self.resultsTable.setHorizontalHeaderLabels(self.display_field_list)



    def initFieldList(self):

        self.searchFieldComboBox.clear()
        type_index=self.chooseType.currentIndex()

        if type_index==0:
            self.display_field_list_temp=[]
            selectedLayer = self.layerListComboBox.currentText()
            with open(os.path.join(os.path.dirname(__file__), 'data.csv')) as csvfile:
                reader= csv.reader(csvfile,delimiter=",")
                for row in reader:
                    if row[0]==selectedLayer:
                        self.searchFieldComboBox.addItem(row[2])
                        self.searchString.setText(row[4])
                        self.display_field_list_temp=row[5].split(",")
                        # self.updateTableStructure(row[5])

                        # setting default index for the comparison from csv
                        for i,comItemms in enumerate(self.comparisonItems):
                            if comItemms==row[6]:
                                self.comparisonComboBox.setCurrentIndex(i)


        else:
            self.display_field_list_temp=[]
            # selectedLayer = self.layerListComboBox.currentIndex()
            selectedLayer = self.layerListComboBox.currentText()
            # self.searchString.setVisible(False)
            self.searchString.setText("Note")
            self.searchFieldComboBox.addItem('<All Fields>')
            if  self.layerListComboBox.currentIndex() >= 0:
                self.searchFieldComboBox.setEnabled(True)
                for field in self.searchLayers[selectedLayer].fields():
                    # self.searchFieldComboBox.addItem(field.name())
                    self.display_field_list_temp.append(field.name())

            else:
                self.searchFieldComboBox.setCurrentIndex(0)
                self.searchFieldComboBox.setEnabled(False)
            # self.updateTableStructure(",".join(display_field_list_temp))

    def runSearch(self):
        '''Called when the user pushes the Search button'''
        # selectedLayer = self.layerListComboBox.currentIndex()
        self.updateTableStructure(",".join(self.display_field_list_temp))


        selectedLayer = self.layerListComboBox.currentText()
        comparisonMode = self.comparisonComboBox.currentIndex()
        self.noSelection = True
        try:
            sstr = self.findStringEdit.text().strip()
        except:
            self.showErrorMessage('Invalid Search String')
            return

        type_index=self.chooseType.currentIndex()

            # Only search on the selected vector layer
        layers = [self.searchLayers[selectedLayer]]
        self.vlayers=[]
        # Find the vector layers that are to be searched
        for layer in layers:
            if isinstance(layer, QgsVectorLayer):
                self.vlayers.append(layer)
        if len(self.vlayers) == 0:
            self.showErrorMessage('Please add respective layers')
            return

        # vlayers contains the layers that we will search in
        self.searchButton.setEnabled(False)
        self.stopButton.setEnabled(True)
        self.doneButton.setEnabled(False)
        self.clearButton.setEnabled(False)
        self.clearResults()
        self.resultsLabel.setText('')

        selectedField = self.searchFieldComboBox.currentText()
        if 'all field'  in selectedField.lower() or 'all fields'  in selectedField.lower():
                infield = self.searchFieldComboBox.currentIndex() >= 1
        else:
            infield = self.searchFieldComboBox.currentIndex() >= 0

        # Because this could take a lot of time, set up a separate thread
        # for a worker function to do the searching.
        thread = QThread()
        worker = Worker(self.vlayers, infield, sstr, comparisonMode, selectedField, self.maxResults)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self.workerFinished)
        worker.foundmatch.connect(self.addFoundItem)
        worker.error.connect(self.workerError)
        self.thread = thread
        self.worker = worker
        self.noSelection = False

        thread.start()

    def workerFinished(self, status):
        '''Clean up the worker and thread'''
        self.worker.deleteLater()
        self.thread.quit()
        self.thread.wait()
        self.thread.deleteLater()
        self.worker = None
        self.resultsLabel.setText('(number of matches: ' + str(self.found) + ')')

        self.vlayers = []
        self.searchButton.setEnabled(True)
        self.clearButton.setEnabled(True)
        self.stopButton.setEnabled(False)
        self.doneButton.setEnabled(True)

    def workerError(self, exception_string):
        '''An error occurred so display it.'''
        #self.showErrorMessage(exception_string)
        print(exception_string)

    def killWorker(self):
        '''This is initiated when the user presses the Stop button
        and will stop the search process'''
        if self.worker is not None:
            self.worker.kill()

    def clearResults(self):
        '''Clear all the search results.'''
        self.noSelection = True
        self.found = 0
        self.results = []
        self.resultsTable.setRowCount(0)  # This removes the results from the table of records
        self.noSelection = False

    def addFoundItem(self, layer, feature, attrname, value):
        '''We found an item so add it to the found list.'''
        self.resultsTable.insertRow(self.found)
        self.results.append([layer, feature])
        # if columns are specified for display in csv file, then it will get their values in loop and assign them
        if len(self.display_field_list)>0:
            for index, field_name in enumerate(self.display_field_list):
                # print (type(feature[field_name]))
                field_value=str(feature[field_name])
                if 'QDate' in field_value:
                    field_value=feature[field_name].toString('MMMM d, yyyy')

                self.resultsTable.setItem(self.found, index, QTableWidgetItem(field_value)) # iterate through feature and get it's attributes
        else:
            # setting default values if no display columns are specified
            self.resultsTable.setItem(self.found, 0, QTableWidgetItem(value))
            self.resultsTable.setItem(self.found, 1, QTableWidgetItem(layer.name()))
            self.resultsTable.setItem(self.found, 2, QTableWidgetItem(attrname))
            self.resultsTable.setItem(self.found, 3, QTableWidgetItem((str(feature.id()))))

        self.found += 1

    def showErrorMessage(self, message):
        '''Display an error message.'''
        self.iface.messageBar().pushMessage("", message, level=Qgis.Warning, duration=2)
