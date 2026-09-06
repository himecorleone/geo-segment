#!/bin/sh
set -eu
QGIS_BUNDLE=/Applications/QGIS.app/Contents
export QT_QPA_PLATFORM=offscreen
export PYTHONHOME="$QGIS_BUNDLE/Resources"
export PYTHONPATH="$QGIS_BUNDLE/Resources/python3.12:$QGIS_BUNDLE/Resources/python3.12/lib-dynload:$QGIS_BUNDLE/Resources/python3.12/site-packages:$QGIS_BUNDLE/Resources/qgis/python"
exec "$QGIS_BUNDLE/MacOS/python3.12" tests/qgis_smoke.py
