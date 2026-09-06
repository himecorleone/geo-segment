"""QGIS UI and rendering. All model work runs in a cancellable QProcess."""
import json
from pathlib import Path
import tempfile

from qgis.PyQt.QtCore import Qt, QSize, QProcess, QProcessEnvironment, QSettings
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import (
    QAction, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget,
)
from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsDistanceArea, QgsFeature, QgsField, QgsFillSymbol, QgsGeometry,
    QgsMapLayerProxyModel, QgsMapRendererParallelJob, QgsMapSettings, QgsPointXY,
    QgsProject, QgsRectangle, QgsVectorFileWriter, QgsVectorLayer, QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant
from qgis.gui import QgsMapLayerComboBox, QgsMapTool, QgsRubberBand, QgsVertexMarker

from .spatial import map_to_pixel, map_box_to_pixel

ROOT = Path(__file__).resolve().parent


class PromptTool(QgsMapTool):
    def __init__(self, canvas, owner, box=False):
        super().__init__(canvas)
        self.owner = owner
        self.box_mode = box
        self.start = None
        self.band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self.band.setColor(QColor(255, 184, 64, 180))
        self.band.setWidth(2)
        self.setCursor(Qt.CrossCursor)

    def canvasPressEvent(self, event):
        if self.box_mode and event.button() == Qt.LeftButton:
            self.start = self.toMapCoordinates(event.pos())

    def canvasMoveEvent(self, event):
        if self.start is not None:
            self.band.setToGeometry(QgsGeometry.fromRect(
                QgsRectangle(self.start, self.toMapCoordinates(event.pos()))), None)

    def canvasReleaseEvent(self, event):
        point = self.toMapCoordinates(event.pos())
        if self.box_mode:
            if self.start is not None:
                rectangle = QgsRectangle(self.start, point)
                self.start = None
                self.owner.add_box(rectangle)
                self.band.reset(QgsWkbTypes.PolygonGeometry)
        elif event.button() in (Qt.LeftButton, Qt.RightButton):
            self.owner.add_point(point, 1 if event.button() == Qt.LeftButton else 0)

    def deactivate(self):
        self.start = None
        self.band.reset(QgsWkbTypes.PolygonGeometry)
        super().deactivate()

    def dispose(self):
        self.canvas().scene().removeItem(self.band)


class GeoSegmentPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.dock = None
        self.action = None
        self.process = None
        self.renderer = None
        self.temp = None
        self.frame = None
        self.points = []
        self.labels = []
        self.box = None
        self.markers = []
        self.tools = []
        self.previous_tool = None
        self.result_layer = None
        self.result_pixel_size = None
        self.cancelled = False
        self.busy = False

    def initGui(self):
        self.action = QAction(QIcon(str(ROOT / "icon.svg")), "Geo Segment", self.iface.mainWindow())
        self.action.triggered.connect(self.show)
        self.iface.addPluginToRasterMenu("Geo Segment", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.dock:
            self.cancel()
            if self.process:
                self.process.waitForFinished(3000)
            if self.renderer:
                self.renderer.cancel()
            self.restore_tool()
            self.clear_prompts()
            self.canvas.scene().removeItem(self.capture_band)
            self.canvas.scene().removeItem(self.box_band)
            for tool in self.tools:
                tool.dispose()
            QgsProject.instance().layersWillBeRemoved.disconnect(self.layers_removed)
            self.canvas.destinationCrsChanged.disconnect(self.crs_changed)
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.action:
            self.iface.removePluginRasterMenu("Geo Segment", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
        if self.temp:
            self.temp.cleanup()

    def button(self, text, callback, layout):
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def show(self):
        if self.dock is None:
            self.build_ui()
        self.dock.show()
        self.dock.raise_()

    def build_ui(self):
        self.temp = tempfile.TemporaryDirectory(prefix="geo-segment-")
        self.dock = QDockWidget("Geo Segment", self.iface.mainWindow())
        self.dock.setObjectName("GeoSegmentDock")
        self.dock.setMinimumWidth(340)
        self.dock.visibilityChanged.connect(self.visibility_changed)
        outer = QWidget()
        layout = QVBoxLayout(outer)
        intro = QLabel("<b>Imagery → object polygons</b><br>Local building detection · interactive SAM")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        work = QWidget()
        work_layout = QVBoxLayout(work)
        capture_group = QGroupBox("1 · Choose imagery")
        capture_layout = QVBoxLayout(capture_group)
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.layer_combo.layerChanged.connect(self.source_changed)
        capture_layout.addWidget(self.layer_combo)
        self.resolution = QComboBox()
        for value in (512, 1024, 2048):
            self.resolution.addItem(str(value) + " px longest side", value)
        self.resolution.setCurrentIndex(1)
        capture_layout.addWidget(self.resolution)
        self.capture_button = self.button("Capture current view", self.capture, capture_layout)
        self.capture_label = QLabel("Zoom to your area, choose a raster, then capture.")
        self.capture_label.setWordWrap(True)
        capture_layout.addWidget(self.capture_label)
        work_layout.addWidget(capture_group)
        prompt_group = QGroupBox("2 · Segment objects")
        prompt_layout = QVBoxLayout(prompt_group)
        self.points_button = self.button("Add points · left include / right exclude", lambda: self.activate_tool(False), prompt_layout)
        self.box_button = self.button("Draw an object box", lambda: self.activate_tool(True), prompt_layout)
        row = QHBoxLayout()
        self.undo_button = self.button("Undo point", self.undo_point, row)
        self.clear_button = self.button("Clear prompts", self.clear_prompts, row)
        prompt_layout.addLayout(row)
        self.prompt_label = QLabel("No prompts")
        prompt_layout.addWidget(self.prompt_label)
        self.prompt_button = self.button("Segment prompted object", lambda: self.segment("prompt"), prompt_layout)
        self.auto_button = self.button("Find unlabelled masks in capture", lambda: self.segment("automatic"), prompt_layout)
        note = QLabel("Automatic mode finds unlabelled masks. It does not search by object name. Add or remove points and run again to refine an object.")
        note.setWordWrap(True)
        prompt_layout.addWidget(note)
        work_layout.addWidget(prompt_group)
        building_group = QGroupBox("Detect buildings")
        building_layout = QVBoxLayout(building_group)
        area_form = QFormLayout()
        self.min_area = QDoubleSpinBox()
        self.min_area.setRange(0.25, 1000000)
        self.min_area.setValue(float(QSettings().value("GeoSegment/min_area", 10)))
        self.min_area.setSuffix(" m²")
        area_form.addRow("Minimum building area", self.min_area)
        building_layout.addLayout(area_form)
        self.building_button = self.button("Detect buildings in current view", self.detect_buildings, building_layout)
        building_note = QLabel("Uses the selected local raster's first three RGB bands at 0.5 m resolution. No capture needed. Results are building regions: touching buildings may merge and counts need review.")
        building_note.setWordWrap(True)
        building_layout.addWidget(building_note)
        work_layout.insertWidget(1, building_group)
        output_group = QGroupBox("3 · Refine and export")
        output_layout = QVBoxLayout(output_group)
        form = QFormLayout()
        self.simplify = QDoubleSpinBox()
        self.simplify.setRange(0, 50)
        self.simplify.setSingleStep(0.5)
        form.addRow("Simplify (result pixels)", self.simplify)
        self.buffer = QDoubleSpinBox()
        self.buffer.setRange(-100, 100)
        self.buffer.setSingleStep(0.5)
        form.addRow("Expand / shrink (pixels)", self.buffer)
        self.fill_holes = QCheckBox("Fill polygon holes")
        form.addRow(self.fill_holes)
        output_layout.addLayout(form)
        self.refine_button = self.button("Create refined copy of result", self.refine, output_layout)
        self.export_button = self.button("Export result to GeoPackage…", self.export, output_layout)
        work_layout.addWidget(output_group)
        work_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(work)
        tabs.addTab(scroll, "Segment")
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        settings_form = QFormLayout()
        saved = QSettings()
        self.python_path = QLineEdit(saved.value("GeoSegment/python", ""))
        self.checkpoint = QLineEdit(saved.value("GeoSegment/checkpoint", ""))
        self.building_model = QLineEdit(saved.value("GeoSegment/building_model", ""))
        for label, field in (("AI Python executable", self.python_path), ("SAM checkpoint (.pth)", self.checkpoint),
                             ("RAMP building model (.onnx)", self.building_model)):
            row = QHBoxLayout()
            row.addWidget(field)
            self.button("Browse…", lambda checked=False, f=field: self.browse(f), row)
            settings_form.addRow(label, row)
        self.model_type = QComboBox()
        self.model_type.addItems(["vit_b", "vit_l", "vit_h"])
        self.model_type.setCurrentText(saved.value("GeoSegment/model", "vit_b"))
        settings_form.addRow("Checkpoint model", self.model_type)
        self.device = QComboBox()
        self.device.addItems(["auto", "cpu", "cuda", "mps"])
        self.device.setCurrentText(saved.value("GeoSegment/device", "auto"))
        settings_form.addRow("Compute device", self.device)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0, 1)
        self.threshold.setSingleStep(0.05)
        self.threshold.setValue(0.8)
        settings_form.addRow("Minimum mask quality", self.threshold)
        self.min_pixels = QSpinBox()
        self.min_pixels.setRange(1, 1000000)
        self.min_pixels.setValue(32)
        settings_form.addRow("Minimum object pixels", self.min_pixels)
        self.grid = QSpinBox()
        self.grid.setRange(4, 64)
        self.grid.setValue(16)
        settings_form.addRow("Automatic grid per side", self.grid)
        settings_layout.addLayout(settings_form)
        self.check_button = self.button("Save settings and check AI runtime", self.check_runtime, settings_layout)
        help_label = QLabel("Use a separate Python environment with requirements-ai.txt and a matching SAM checkpoint. Building detection also needs requirements-buildings.txt and the tested RAMP model linked in README.md.\n\nSAM auto uses CUDA when available, otherwise CPU. Buildings run on CPU. Imagery stays local during inference. Online basemaps still contact their normal tile provider.\n\nRepeated SAM prompts reuse the current image embedding. Models load per job. Start with 1024 px and ViT-B.")
        help_label.setWordWrap(True)
        settings_layout.addWidget(help_label)
        settings_layout.addStretch()
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(settings_widget)
        tabs.addTab(settings_scroll, "Settings")
        self.status = QLabel("Ready — capture imagery to begin")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        self.cancel_button = self.button("Cancel", self.cancel, layout)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(200)
        self.log.setMaximumHeight(100)
        layout.addWidget(self.log)
        self.dock.setWidget(outer)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.iface.mainWindow().resizeDocks([self.dock], [420], Qt.Horizontal)
        self.capture_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        self.capture_band.setColor(QColor(25, 180, 170, 160))
        self.capture_band.setFillColor(QColor(0, 0, 0, 0))
        self.capture_band.setWidth(2)
        self.box_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        self.box_band.setColor(QColor(255, 184, 64, 180))
        self.box_band.setFillColor(QColor(0, 0, 0, 0))
        self.tools = [PromptTool(self.canvas, self), PromptTool(self.canvas, self, True)]
        QgsProject.instance().layersWillBeRemoved.connect(self.layers_removed)
        self.canvas.destinationCrsChanged.connect(self.crs_changed)
        self.set_busy(False)

    def message(self, text):
        self.status.setText(text)
        self.log.appendPlainText(text)

    def set_busy(self, busy):
        self.busy = busy
        for button in (self.capture_button, self.check_button):
            button.setEnabled(not busy)
        for control in (self.layer_combo, self.resolution, self.python_path, self.checkpoint,
                        self.building_model, self.min_area, self.model_type, self.device,
                        self.threshold, self.min_pixels, self.grid):
            control.setEnabled(not busy)
        for button in (self.points_button, self.box_button, self.prompt_button,
                       self.auto_button, self.undo_button, self.clear_button):
            button.setEnabled(not busy and self.frame is not None)
        self.building_button.setEnabled(not busy and self.layer_combo.currentLayer() is not None)
        has_result = self.result_layer is not None and self.result_layer.isValid()
        self.refine_button.setEnabled(not busy and has_result)
        self.export_button.setEnabled(not busy and has_result)
        self.cancel_button.setEnabled(busy)
        self.progress_bar.setRange(0, 0 if busy else 1)
        self.progress_bar.setValue(0)

    def browse(self, field):
        title = "Python executable" if field is self.python_path else ("RAMP building model" if field is self.building_model else "SAM checkpoint")
        path, _ = QFileDialog.getOpenFileName(self.dock, "Choose " + title)
        if path:
            field.setText(path)

    def save_settings(self):
        saved = QSettings()
        for key, value in (("python", self.python_path.text().strip()),
                           ("checkpoint", self.checkpoint.text().strip()),
                           ("building_model", self.building_model.text().strip()), ("min_area", self.min_area.value()),
                           ("model", self.model_type.currentText()), ("device", self.device.currentText())):
            saved.setValue("GeoSegment/" + key, value)

    def capture(self):
        if self.busy:
            return
        layer = self.layer_combo.currentLayer()
        if layer is None or not layer.isValid():
            self.message("Choose a valid raster layer first.")
            return
        extent = QgsRectangle(self.canvas.extent())
        if extent.isEmpty() or not self.canvas.mapSettings().destinationCrs().isValid():
            self.message("Set a valid project CRS and zoom to a non-empty raster area.")
            return
        self.restore_tool()
        self.clear_prompts()
        self.frame = None
        longest = self.resolution.currentData()
        scale = longest / max(extent.width(), extent.height())
        width, height = max(1, round(extent.width() * scale)), max(1, round(extent.height() * scale))
        settings = QgsMapSettings()
        settings.setLayers([layer])
        settings.setDestinationCrs(self.canvas.mapSettings().destinationCrs())
        settings.setTransformContext(QgsProject.instance().transformContext())
        settings.setOutputSize(QSize(width, height))
        settings.setOutputDpi(96)
        settings.setRotation(0)
        settings.setBackgroundColor(QColor(0, 0, 0, 0))
        settings.setExtent(extent)
        actual = settings.visibleExtent()
        self.pending_frame = {"bounds": [actual.xMinimum(), actual.yMinimum(), actual.xMaximum(), actual.yMaximum()],
                              "width": width, "height": height,
                              "crs_wkt": settings.destinationCrs().toWkt(), "source_id": layer.id(),
                              "image": str(Path(self.temp.name) / "capture.png")}
        self.cancelled = False
        self.set_busy(True)
        self.message("Rendering the selected raster…")
        self.renderer = QgsMapRendererParallelJob(settings)
        self.renderer.finished.connect(self.capture_finished)
        self.renderer.start()

    def capture_finished(self):
        job = self.renderer
        self.renderer = None
        try:
            if self.cancelled:
                self.message("Capture cancelled.")
                return
            errors = job.errors()
            if errors:
                raise ValueError("Raster rendering failed: " + "; ".join(e.message for e in errors))
            image = job.renderedImage()
            if image.isNull() or not image.save(self.pending_frame["image"], "PNG"):
                raise ValueError("Could not save the raster capture.")
            self.frame = self.pending_frame
            self.capture_band.setToGeometry(QgsGeometry.fromRect(QgsRectangle(*self.frame["bounds"])), None)
            self.capture_label.setText("Captured {width} × {height} px. Teal outline marks the area. Recapture after changing imagery or zoom.".format(**self.frame))
            self.message("Capture ready. Add points, draw a box, or find objects automatically.")
        except Exception as error:
            self.message(str(error))
        finally:
            job.deleteLater()
            self.set_busy(False)

    def activate_tool(self, box):
        if self.busy or not self.frame:
            return
        if self.canvas.mapTool() not in self.tools:
            self.previous_tool = self.canvas.mapTool()
        self.canvas.setMapTool(self.tools[1 if box else 0])

    def restore_tool(self):
        if self.canvas.mapTool() in self.tools:
            current = self.canvas.mapTool()
            self.canvas.unsetMapTool(current)
            if self.previous_tool:
                self.canvas.setMapTool(self.previous_tool)
        self.previous_tool = None

    def add_point(self, point, label):
        if self.busy or not self.frame:
            return
        try:
            pixel = map_to_pixel(point.x(), point.y(), self.frame["bounds"], self.frame["width"], self.frame["height"])
        except ValueError as error:
            self.message(str(error))
            return
        self.points.append(pixel)
        self.labels.append(label)
        marker = QgsVertexMarker(self.canvas)
        marker.setCenter(point)
        marker.setColor(QColor("#16a085" if label else "#e24b4b"))
        marker.setIconType(QgsVertexMarker.ICON_CROSS if label else QgsVertexMarker.ICON_X)
        marker.setIconSize(12)
        marker.setPenWidth(3)
        self.markers.append(marker)
        self.update_prompt_label()

    def add_box(self, rectangle):
        if self.busy or not self.frame:
            return
        try:
            box = [rectangle.xMinimum(), rectangle.yMinimum(), rectangle.xMaximum(), rectangle.yMaximum()]
            self.box = map_box_to_pixel(box, self.frame["bounds"], self.frame["width"], self.frame["height"])
        except ValueError as error:
            self.message(str(error))
            return
        self.box_band.setToGeometry(QgsGeometry.fromRect(rectangle), None)
        self.update_prompt_label()

    def undo_point(self):
        if self.points:
            self.points.pop()
            self.labels.pop()
            self.canvas.scene().removeItem(self.markers.pop())
        self.update_prompt_label()

    def clear_prompts(self):
        self.points = []
        self.labels = []
        self.box = None
        for marker in self.markers:
            self.canvas.scene().removeItem(marker)
        self.markers = []
        if hasattr(self, "box_band"):
            self.box_band.reset(QgsWkbTypes.PolygonGeometry)
        if hasattr(self, "prompt_label"):
            self.update_prompt_label()

    def update_prompt_label(self):
        self.prompt_label.setText("{} include · {} exclude{}".format(self.labels.count(1), self.labels.count(0), " · box" if self.box else ""))

    def invalidate_frame(self):
        if self.busy:
            self.cancel()
        self.restore_tool()
        self.clear_prompts()
        self.frame = None
        self.capture_band.reset(QgsWkbTypes.PolygonGeometry)
        self.capture_label.setText("Capture again to use the current raster and CRS.")
        self.set_busy(self.busy)

    def source_changed(self, layer):
        if self.dock and hasattr(self, "capture_band"):
            self.invalidate_frame()

    def crs_changed(self):
        self.invalidate_frame()

    def layers_removed(self, ids):
        if self.result_layer and self.result_layer.id() in ids:
            self.result_layer = None
            self.set_busy(self.busy)
        source_id = self.frame["source_id"] if self.frame else getattr(self, "pending_frame", {}).get("source_id")
        if self.busy and getattr(self, "purpose", "") == "buildings":
            source_id = self.run_frame["source_id"]
        if source_id in ids:
            self.invalidate_frame()

    def visibility_changed(self, visible):
        if not visible:
            self.restore_tool()

    def check_runtime(self):
        self.save_settings()
        self.launch(["--check"], "check")

    def detect_buildings(self):
        if self.busy:
            return
        layer = self.layer_combo.currentLayer()
        if layer is None or not layer.isValid() or not Path(layer.source()).is_file():
            self.message("Building detection needs a local georeferenced RGB raster. Select a local file layer first.")
            return
        model_path = Path(self.building_model.text().strip()).expanduser()
        if not model_path.is_file():
            self.message("Choose the RAMP building model (.onnx) in Settings. The download link is in README.md.")
            return
        try:
            project = QgsProject.instance()
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            centre = QgsCoordinateTransform(layer.crs(), wgs84, project).transform(layer.extent().center())
            if not -80 <= centre.y() <= 84:
                raise ValueError("Building detection currently supports areas between 80°S and 84°N.")
            zone = min(60, max(1, int((centre.x()+180)/6)+1))
            target = QgsCoordinateReferenceSystem("EPSG:" + str((32600 if centre.y() >= 0 else 32700)+zone))
            extent = QgsCoordinateTransform(self.canvas.mapSettings().destinationCrs(), target, project).transformBoundingBox(self.canvas.extent())
            request = dict(mode="buildings", source=layer.source(), source_id=layer.id(),
                           building_model=str(model_path), min_area_m2=self.min_area.value(),
                           crs_wkt=target.toWkt(),
                           bounds=[extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()])
            self.restore_tool()
            self.save_settings()
            self.submit(request, "buildings")
        except Exception as error:
            self.message("Could not prepare building detection: " + str(error))

    def segment(self, mode):
        if self.busy or not self.frame:
            return
        if mode == "prompt" and not self.box and 1 not in self.labels:
            self.message("Add at least one include point or draw an object box.")
            return
        if not Path(self.checkpoint.text().strip()).is_file():
            self.message("Choose your downloaded SAM checkpoint in Settings first.")
            return
        self.restore_tool()
        self.save_settings()
        request = dict(self.frame, mode=mode, checkpoint=self.checkpoint.text().strip(),
                       model_type=self.model_type.currentText(), device=self.device.currentText(),
                       points=self.points if mode == "prompt" else [],
                       labels=self.labels if mode == "prompt" else [],
                       box=self.box if mode == "prompt" else None,
                       score_threshold=self.threshold.value(), min_pixels=self.min_pixels.value(),
                       points_per_side=self.grid.value(),
                       embedding_cache=str(Path(self.temp.name) / "sam-embedding.npz"))
        self.submit(request, "segment")

    def submit(self, request, purpose):
        self.request_path = Path(self.temp.name) / "request.json"
        self.output_path = Path(self.temp.name) / "result.json"
        self.output_path.unlink(missing_ok=True)
        self.request_path.write_text(json.dumps(request), encoding="utf-8")
        self.run_frame = dict(request)
        self.launch(["--request", str(self.request_path), "--output", str(self.output_path)], purpose)

    def launch(self, args, purpose):
        if self.busy:
            return
        executable = Path(self.python_path.text().strip()).expanduser()
        if not executable.is_file():
            self.message("Choose the AI environment's Python executable in Settings.")
            return
        self.cancelled = False
        self.purpose = purpose
        self.process_output = ""
        self.process = QProcess(self.dock)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        environment = QProcessEnvironment.systemEnvironment()
        # QGIS bundles Python/Qt/GDAL paths which can break an independent interpreter.
        for key in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
                    "GDAL_DATA", "PROJ_LIB", "PROJ_DATA", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH"):
            environment.remove(key)
        environment.insert("PYTHONNOUSERSITE", "1")
        environment.insert("PYTHONUNBUFFERED", "1")
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(ROOT))
        self.process.readyReadStandardOutput.connect(self.read_process)
        self.process.finished.connect(self.process_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.set_busy(True)
        self.message("Checking AI runtime…" if purpose == "check" else "Starting local segmentation…")
        self.process.start(str(executable), [str(ROOT / "worker.py")] + args)

    def read_process(self):
        if self.process:
            text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
            self.process_output = (self.process_output + text)[-12000:]
            if text.strip():
                self.message(text.strip())

    def process_error(self, error):
        if error == QProcess.FailedToStart and self.process:
            self.message("Could not start the AI Python executable: " + self.process.errorString())
            self.process.deleteLater()
            self.process = None
            self.set_busy(False)

    def process_finished(self, exit_code, exit_status):
        if not self.process:
            return
        self.read_process()
        process = self.process
        self.process = None
        try:
            if self.cancelled:
                self.message("Cancelled. Existing result layers are preserved.")
            elif exit_code != 0 or exit_status != QProcess.NormalExit:
                self.message("AI job failed. Check the log and runtime settings. " + self.process_output[-1200:])
            elif self.purpose == "check":
                runtime = json.loads(self.process_output.strip().splitlines()[-1])
                building_status = "Building dependencies are ready." if runtime.get("buildings") else "Install requirements-buildings.txt to enable building detection."
                self.message("AI runtime is ready. " + building_status)
            else:
                result = json.loads(self.output_path.read_text(encoding="utf-8"))
                self.load_result(result, self.run_frame)
        except Exception as error:
            self.message("Could not load the result: " + str(error))
        finally:
            process.deleteLater()
            self.set_busy(False)

    def cancel(self):
        self.cancelled = True
        if self.process:
            self.process.kill()
        if self.renderer:
            self.renderer.cancelWithoutBlocking()

    def new_layer(self, name, crs_wkt):
        layer = QgsVectorLayer("MultiPolygon", name, "memory")
        layer.setCrs(QgsCoordinateReferenceSystem.fromWkt(crs_wkt))
        layer.dataProvider().addAttributes([QgsField("object_id", QVariant.Int),
                                            QgsField("score", QVariant.Double),
                                            QgsField("pixels", QVariant.Int),
                                            QgsField("class_name", QVariant.String), QgsField("model", QVariant.String),
                                            QgsField("score_type", QVariant.String), QgsField("area_m2", QVariant.Double),
                                            QgsField("review", QVariant.String)])
        layer.updateFields()
        layer.renderer().setSymbol(QgsFillSymbol.createSimple({"color": "32,190,157,55", "outline_color": "15,110,95,255", "outline_width": "0.4"}))
        return layer

    def load_result(self, result, frame):
        if result.get("protocol") != 1 or result.get("crs_wkt") != frame["crs_wkt"]:
            raise ValueError("Worker result does not match the capture coordinate system.")
        if not result["features"]:
            self.result_layer = None
            self.result_pixel_size = None
            self.set_busy(self.busy)
            self.message("No regions met the settings. Previous layers are preserved; there is no new result to export.")
            return
        buildings = frame.get("mode") == "buildings"
        if buildings and (result.get("mode") != "buildings" or result.get("pixel_size") != 0.5):
            raise ValueError("Building output does not match this job.")
        layer = self.new_layer("Geo Segment · " + ("building regions" if buildings else "unlabelled masks"), result["crs_wkt"])
        measure = QgsDistanceArea()
        measure.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
        measure.setEllipsoid("WGS84")
        features = []
        for record in result["features"]:
            polygons = [[[QgsPointXY(float(x), float(y)) for x, y in ring] for ring in polygon]
                        for polygon in record["geometry"]["coordinates"]]
            geometry = QgsGeometry.fromMultiPolygonXY(polygons)
            if not geometry.isGeosValid():
                geometry = geometry.makeValid()
            if geometry.isEmpty() or geometry.type() != QgsWkbTypes.PolygonGeometry:
                continue
            geometry.convertToMultiType()
            feature = QgsFeature(layer.fields())
            feature.setGeometry(geometry)
            p = record["properties"]
            feature.setAttributes([p["object_id"], p["score"], p["pixels"],
                                   p.get("class_name", "unlabelled"), p.get("model", "SAM"),
                                   p.get("score_type", "predicted mask IoU"),
                                   measure.measureArea(geometry), p.get("review", "unreviewed")])
            features.append(feature)
        if not features:
            raise ValueError("No valid polygon geometry was returned.")
        ok, _ = layer.dataProvider().addFeatures(features)
        if not ok:
            raise ValueError("QGIS could not create the result features.")
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        self.result_layer = layer
        bounds = frame["bounds"]
        self.result_pixel_size = 0.5 if buildings else (bounds[2] - bounds[0]) / frame["width"]
        self.iface.setActiveLayer(layer)
        label = "building regions" if buildings else "unlabelled masks"
        self.message("{} {} added, all unreviewed. {} Export to keep them.".format(
            len(features), label, "Touching buildings may be merged." if buildings else "This is not a class-specific object count."))

    def refine(self):
        if not self.result_layer or self.busy:
            return
        layer = self.new_layer("Geo Segment · refined", self.result_layer.crs().toWkt())
        features = []
        skipped = 0
        measure = QgsDistanceArea()
        measure.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
        measure.setEllipsoid("WGS84")
        for source in self.result_layer.getFeatures():
            geometry = QgsGeometry(source.geometry())
            if self.buffer.value():
                geometry = geometry.buffer(self.buffer.value() * self.result_pixel_size, 8)
            if self.simplify.value():
                geometry = geometry.simplify(self.simplify.value() * self.result_pixel_size)
            if self.fill_holes.isChecked():
                geometry = geometry.removeInteriorRings()
            if not geometry.isGeosValid():
                geometry = geometry.makeValid()
            if geometry.isEmpty() or geometry.type() != QgsWkbTypes.PolygonGeometry:
                skipped += 1
                continue
            geometry.convertToMultiType()
            feature = QgsFeature(layer.fields())
            feature.setAttributes(source.attributes())
            feature["area_m2"] = measure.measureArea(geometry)
            feature.setGeometry(geometry)
            features.append(feature)
        if not features:
            self.message("Refinement removed all objects. Reduce the shrink distance.")
            return
        ok, _ = layer.dataProvider().addFeatures(features)
        if not ok:
            self.message("Could not create the refined layer.")
            return
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        self.result_layer = layer
        self.iface.setActiveLayer(layer)
        self.message("Refined copy added; previous layer preserved. {} empty objects removed. Pixel counts and scores refer to the original mask.".format(skipped))

    def export(self):
        if not self.result_layer or self.busy:
            return
        path, _ = QFileDialog.getSaveFileName(self.dock, "Export Geo Segment polygons", "geo-segment.gpkg", "GeoPackage (*.gpkg)")
        if not path:
            return
        if not path.lower().endswith(".gpkg"):
            path += ".gpkg"
        # A fresh file avoids replacing unrelated layers in an existing GeoPackage.
        if Path(path).exists():
            self.message("Choose a new GeoPackage filename to preserve existing data.")
            return
        error = self.write_geopackage(self.result_layer, path)
        if error:
            self.message("Export failed: " + error)
        else:
            self.message("Saved polygons to " + path)

    @staticmethod
    def write_geopackage(layer, path):
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "segments"
        options.fileEncoding = "UTF-8"
        result = QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(path), QgsProject.instance().transformContext(), options)
        return "" if result[0] == QgsVectorFileWriter.NoError else str(result[1])
