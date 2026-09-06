"""Geo Segment QGIS entry point. Heavy AI dependencies run outside QGIS."""


def classFactory(iface):
    from .plugin import GeoSegmentPlugin
    return GeoSegmentPlugin(iface)
