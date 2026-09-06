"""Real QGIS integration smoke: render, prompts, vector creation, refine, export."""
import json
import gc
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qgis.core import QgsApplication, QgsProject, QgsRasterLayer, QgsRectangle, QgsCoordinateReferenceSystem, QgsPointXY, QgsVectorLayer
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtWidgets import QMainWindow
from qgis.PyQt.QtCore import QEventLoop
from qgis.PyQt.QtCore import QCoreApplication, QEvent
from osgeo import gdal, osr
import numpy as np
from geo_segment.plugin import GeoSegmentPlugin

gdal.UseExceptions()


def wait_until(predicate, timeout=15):
    start = time.monotonic()
    while not predicate():
        app.processEvents(QEventLoop.AllEvents, 50)
        if time.monotonic() - start > timeout:
            raise AssertionError('Timed out waiting for QGIS')
        time.sleep(0.01)


class Interface:
    def __init__(self):
        self.window = QMainWindow()
        self.window.resize(1100, 900)
        self.canvas = QgsMapCanvas()
        self.window.setCentralWidget(self.canvas)
        self.window.show()
    def mainWindow(self): return self.window
    def mapCanvas(self): return self.canvas
    def addPluginToRasterMenu(self, *args): pass
    def addToolBarIcon(self, *args): pass
    def removePluginRasterMenu(self, *args): pass
    def removeToolBarIcon(self, *args): pass
    def setActiveLayer(self, layer): self.active = layer
    def addDockWidget(self, area, dock): self.window.addDockWidget(area, dock)
    def removeDockWidget(self, dock): self.window.removeDockWidget(dock)


app = QgsApplication([], False)
app.initQgis()
iface = Interface()
plugin = GeoSegmentPlugin(iface)
with tempfile.TemporaryDirectory() as directory:
    path = str(Path(directory) / 'imagery.tif')
    image = gdal.GetDriverByName('GTiff').Create(path, 100, 100, 3, gdal.GDT_Byte)
    image.SetGeoTransform((500000, 1, 0, 5100100, 0, -1))
    crs = osr.SpatialReference()
    crs.ImportFromEPSG(32632)
    image.SetProjection(crs.ExportToWkt())
    for i in range(1, 4):
        pixels = np.full((100, 100), 40 * i, dtype=np.uint8)
        pixels[20:70, 30:80] = 240
        image.GetRasterBand(i).WriteArray(pixels)
    image = None
    raster = QgsRasterLayer(path, 'Test orthophoto')
    assert raster.isValid()
    QgsProject.instance().addMapLayer(raster)
    iface.canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:32632'))
    iface.canvas.setLayers([raster])
    iface.canvas.setExtent(QgsRectangle(500000, 5100000, 500100, 5100100))
    plugin.initGui()
    plugin.show()
    plugin.layer_combo.setLayer(raster)
    app.processEvents()
    iface.canvas.refresh()
    plugin.capture()
    wait_until(lambda: not plugin.busy)
    assert plugin.frame, plugin.log.toPlainText()
    assert Path(plugin.frame['image']).exists()
    plugin.add_point(QgsPointXY(500050, 5100050), 1)
    plugin.add_point(QgsPointXY(500055, 5100055), 0)
    assert plugin.labels == [1, 0]
    plugin.undo_point()
    assert plugin.labels == [1]
    plugin.add_box(QgsRectangle(500030, 5100030, 500070, 5100070))
    assert plugin.box is not None
    result = dict(protocol=1, crs_wkt=plugin.frame['crs_wkt'], features=[{
        'geometry': {'type': 'MultiPolygon', 'coordinates': [[
            [[500030,5100030],[500070,5100030],[500070,5100070],[500030,5100070],[500030,5100030]],
            [[500040,5100040],[500040,5100060],[500060,5100060],[500060,5100040],[500040,5100040]]
        ]]}, 'properties': dict(object_id=1, score=0.95, pixels=1200)}])
    plugin.load_result(result, plugin.frame)
    original = plugin.result_layer
    assert original.crs().authid() == 'EPSG:32632'
    assert original.featureCount() == 1
    assert abs(next(original.getFeatures()).geometry().area() - 1200) < 0.001
    plugin.fill_holes.setChecked(True)
    plugin.refine()
    assert plugin.result_layer.id() != original.id()
    assert abs(next(plugin.result_layer.getFeatures()).geometry().area() - 1600) < 0.001
    assert abs(next(original.getFeatures()).geometry().area() - 1200) < 0.001
    output = Path(directory) / 'segments.gpkg'
    assert not plugin.write_geopackage(plugin.result_layer, output)
    reloaded = QgsVectorLayer(str(output) + '|layername=segments', 'Export', 'ogr')
    assert reloaded.isValid() and reloaded.featureCount() == 1
    assert reloaded.crs().authid() == 'EPSG:32632'
    assert abs(next(reloaded.getFeatures()).geometry().area() - 1600) < 0.001
    print('PASS: raster capture, include/exclude prompts, undo, box, CRS, polygon holes, refinement preservation, GeoPackage round trip')
    root = Path(__file__).resolve().parents[1]
    (root / 'dist').mkdir(exist_ok=True)
    plugin.set_busy(False)
    iface.window.grab().save(str(root / 'dist' / 'qgis-preview.png'))
    if os.environ.get('GEO_SEGMENT_AI_PYTHON'):
        plugin.python_path.setText(os.environ['GEO_SEGMENT_AI_PYTHON'])
        # launch directly so tests do not persist user settings
        plugin.launch(['--check'], 'check')
        wait_until(lambda: not plugin.busy, timeout=120)
        assert 'AI runtime is ready' in plugin.status.text(), plugin.log.toPlainText()
        print('PASS: QProcess launches isolated AI runtime from QGIS')
        # Kill the actual runtime check while its imports are starting, then reuse UI.
        plugin.launch(['--check'], 'check')
        assert plugin.process.waitForStarted(3000)
        plugin.cancel()
        wait_until(lambda: not plugin.busy)
        assert 'Cancelled' in plugin.status.text()
        assert plugin.result_layer.featureCount() == 1
        print('PASS: cancellation returns control and preserves existing result')
        if os.environ.get('GEO_SEGMENT_CHECKPOINT'):
            plugin.checkpoint.setText(os.environ['GEO_SEGMENT_CHECKPOINT'])
            # Avoid changing the user's QSettings in this integration test.
            plugin.save_settings = lambda: None
            plugin.device.setCurrentText('cpu')
            plugin.threshold.setValue(0.0)
            plugin.grid.setValue(4)
            plugin.min_pixels.setValue(4)
            previous_id = plugin.result_layer.id()
            plugin.segment('prompt')
            wait_until(lambda: not plugin.busy, timeout=240)
            assert plugin.result_layer.id() != previous_id, plugin.log.toPlainText()
            assert plugin.result_layer.featureCount() >= 1
            assert plugin.result_layer.crs().authid() == 'EPSG:32632'
            prompt_feature = next(plugin.result_layer.getFeatures())
            assert prompt_feature.geometry().contains(QgsPointXY(500050, 5100050))
            print('PASS: real SAM point+box inference through QGIS render → QProcess → mapped polygons')
            prompt_geometry = bytes(prompt_feature.geometry().asWkb())
            previous_id = plugin.result_layer.id()
            plugin.segment('prompt')
            wait_until(lambda: not plugin.busy, timeout=240)
            assert plugin.result_layer.id() != previous_id, plugin.log.toPlainText()
            assert 'Reusing this capture' in plugin.process_output, plugin.log.toPlainText()
            assert bytes(next(plugin.result_layer.getFeatures()).geometry().asWkb()) == prompt_geometry
            print('PASS: real SAM embedding reuse produces identical geometry on repeated prompts')
            previous_id = plugin.result_layer.id()
            plugin.segment('automatic')
            wait_until(lambda: not plugin.busy, timeout=240)
            assert plugin.result_layer.id() != previous_id, plugin.log.toPlainText()
            assert plugin.result_layer.featureCount() >= 1
            print('PASS: real SAM automatic inference through QGIS; objects:', plugin.result_layer.featureCount())
            assert not plugin.write_geopackage(plugin.result_layer, Path(directory) / 'ai-segments.gpkg')
            iface.canvas.setLayers([plugin.result_layer, raster])
            iface.canvas.refresh()
            wait_until(lambda: not iface.canvas.isDrawing())
            app.processEvents()
            iface.window.grab().save(str(root / 'dist' / 'qgis-preview.png'))
    previous_result = plugin.result_layer
    plugin.load_result(dict(protocol=1, crs_wkt=plugin.frame['crs_wkt'], features=[]), plugin.frame)
    assert plugin.result_layer is None and not plugin.export_button.isEnabled()
    assert QgsProject.instance().mapLayer(previous_result.id()) is previous_result
    print('PASS: empty jobs disable stale export while preserving earlier layers')
    # Verify removal invalidates the capture without leaving a deleted layer reference.
    QgsProject.instance().removeMapLayer(raster.id())
    assert plugin.frame is None and plugin.points == []
    print('PASS: source removal invalidates capture and prompts')
    iface.canvas.setLayers([])
    plugin.unload()
    QgsProject.instance().clear()
    iface.window.close()
    del reloaded, raster, original, plugin
    iface.active = None
    iface.window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    del iface
    gc.collect()
print('PASS: clean plugin unload')
# Release layer/provider references before shutting down QGIS/GDAL registries.
app.exitQgis()
