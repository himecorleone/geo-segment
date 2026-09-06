"""Real satellite → UI action → QProcess → building polygons → GeoPackage."""
import gc
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qgis.core import (QgsApplication, QgsProject, QgsRasterLayer, QgsVectorLayer,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsReferencedRectangle, QgsFillSymbol)
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtWidgets import QMainWindow
from qgis.PyQt.QtCore import QEventLoop, QCoreApplication, QEvent
from geo_segment.plugin import GeoSegmentPlugin

class Interface:
    def __init__(self):
        self.window=QMainWindow(); self.window.resize(1180,900)
        self.canvas=QgsMapCanvas(); self.window.setCentralWidget(self.canvas); self.window.show()
    def mainWindow(self): return self.window
    def mapCanvas(self): return self.canvas
    def addPluginToRasterMenu(self,*args): pass
    def addToolBarIcon(self,*args): pass
    def removePluginRasterMenu(self,*args): pass
    def removeToolBarIcon(self,*args): pass
    def setActiveLayer(self,layer): self.active=layer
    def addDockWidget(self,area,dock): self.window.addDockWidget(area,dock)
    def removeDockWidget(self,dock): self.window.removeDockWidget(dock)

def wait_until(predicate, timeout=120):
    start=time.monotonic()
    while not predicate():
        app.processEvents(QEventLoop.AllEvents,50)
        if time.monotonic()-start > timeout: raise AssertionError('QGIS job timed out')
        time.sleep(.01)

root=Path(__file__).resolve().parents[1]
output=Path(os.environ.get('GEO_SEGMENT_TEST_OUTPUT', root/'dist/optimised-test'))
output.mkdir(parents=True, exist_ok=True)
app=QgsApplication([],False); app.initQgis()
iface=Interface(); project=QgsProject.instance()
raster=QgsRasterLayer(str(root/'dist/satellite-test/spacenet-vegas-img10-rgb8.tif'),'SpaceNet Vegas img10')
assert raster.isValid()
project.addMapLayer(raster); project.setCrs(raster.crs())
iface.canvas.setDestinationCrs(raster.crs()); iface.canvas.setLayers([raster]); iface.canvas.setExtent(raster.extent())
plugin=GeoSegmentPlugin(iface); plugin.initGui(); plugin.show(); plugin.save_settings=lambda:None
plugin.layer_combo.setLayer(raster)
plugin.python_path.setText(str(root/'.venv/bin/python'))
plugin.building_model.setText(str(root/'models/ramp_XUnet_256.onnx'))
plugin.min_area.setValue(10)
app.processEvents()
assert plugin.frame is None  # Building mode does not depend on a SAM capture.
start=time.perf_counter(); plugin.detect_buildings(); wait_until(lambda:not plugin.busy)
seconds=time.perf_counter()-start
layer=plugin.result_layer
assert layer is not None,plugin.log.toPlainText()
assert layer.crs().authid()=='EPSG:32611'
assert layer.featureCount()>0
assert all(f['class_name']=='building' and f['review']=='unreviewed' and f['area_m2']>0 and f.geometry().isGeosValid() for f in layer.getFeatures())
assert plugin.result_pixel_size==.5
assert not plugin.write_geopackage(layer,output/'buildings.gpkg')
loaded=QgsVectorLayer(str(output/'buildings.gpkg'),'Geo Segment building regions','ogr')
assert loaded.isValid() and loaded.featureCount()==layer.featureCount()
loaded.renderer().setSymbol(layer.renderer().symbol().clone())
assert loaded.fields().indexOf('class_name')>=0
project.addMapLayer(loaded)
project.removeMapLayer(layer.id())
truth=QgsVectorLayer(str(root/'dist/satellite-test/spacenet-vegas-img10-buildings.geojson'),'Reference buildings: 28','ogr')
truth.renderer().setSymbol(QgsFillSymbol.createSimple({'style':'no','outline_color':'255,215,0,255','outline_width':'0.4'}))
project.addMapLayer(truth)
transform=QgsCoordinateTransform(truth.crs(),loaded.crs(),project)
references=[]
for f in truth.getFeatures():
    g=QgsGeometry(f.geometry()); g.transform(transform); references.append(g)
predictions=[f.geometry() for f in loaded.getFeatures()]
edges=[]
for p in predictions:
    matches=[]
    for j,t in enumerate(references):
        inter=p.intersection(t).area()
        if inter/(p.area()+t.area()-inter)>=.5: matches.append(j)
    edges.append(matches)
owners={}
def match(i,seen):
    for j in edges[i]:
        if j in seen: continue
        seen.add(j)
        if j not in owners or match(owners[j],seen): owners[j]=i; return True
    return False
for i in range(len(predictions)): match(i,set())
count=len(predictions); tp=len(owners); n=len(references)
metrics=dict(count=count,reference=n,matched=tp,unmatched=count-tp,missed=n-tp,
             precision=tp/count,recall=tp/n,f1=2*tp/(count+n),end_to_end_seconds=seconds)
(output/'metrics.json').write_text(json.dumps(metrics,indent=2))
print('PASS: building inference via QGIS, classification metadata, valid UTM polygons and export',json.dumps(metrics),flush=True)
iface.canvas.setLayers([loaded,raster]); iface.canvas.refresh(); app.processEvents()
wait_until(lambda:not iface.canvas.isDrawing()); app.processEvents()
project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(iface.canvas.extent(),iface.canvas.mapSettings().destinationCrs()))
assert project.write(str(output/'Geo-Segment-Satellite.qgz'))
iface.window.grab().save(str(output/'qgis-buildings-preview.png'))
# A running building job must not add orphaned results after source removal.
plugin.detect_buildings(); assert plugin.process.waitForStarted(3000)
scratch=Path(plugin.temp.name)/'buildings-cancel-test'
scratch.mkdir(); (scratch/'partial.npy').write_bytes(b'cancelled job')
project.removeMapLayer(raster.id()); wait_until(lambda:not plugin.busy)
assert 'Cancelled' in plugin.status.text(),plugin.log.toPlainText()
assert plugin.result_layer is None
assert not list(Path(plugin.temp.name).glob('buildings-*'))
print('PASS: removing the input cancels building inference without orphaned results',flush=True)
iface.canvas.setLayers([]); plugin.unload(); project.clear(); iface.window.close()
iface.active=None
del raster,layer,loaded,truth,plugin
iface.window.deleteLater(); QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
del iface; gc.collect(); app.exitQgis()
