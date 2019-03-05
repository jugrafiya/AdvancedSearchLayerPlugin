import os
import csv

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from PyQt5.QtCore  import Qt

from .searchDialog import LayerSearchDialog

class SearchLayers:
    def __init__(self, iface):
        self.iface = iface
        self.searchDialog = None

    def initGui(self):
        # Create the menu items in the Plugin menu and attach the icon to the toolbar
        icon = QIcon(os.path.dirname(__file__) + "/icon.png")
        self.searchAction = QAction(icon, "NGSC Search", self.iface.mainWindow())
        self.searchAction.setObjectName('searchLayers')
        self.searchAction.triggered.connect(self.showSearchDialog)
        self.iface.addToolBarIcon(self.searchAction)
        self.iface.addPluginToMenu("NGSC Search", self.searchAction)

    def unload(self):
        self.iface.removePluginMenu('NGSC Search', self.searchAction)
        self.iface.removeToolBarIcon(self.searchAction)

    def showSearchDialog(self):
        if self.searchDialog is None:
            # All the work is done in the LayerSearchDialog
            self.searchDialog = LayerSearchDialog(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget( Qt.RightDockWidgetArea, self.searchDialog )
        self.searchDialog.show()