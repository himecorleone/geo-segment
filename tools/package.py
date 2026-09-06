"""Build a QGIS-installable ZIP containing only the plugin source."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import configparser

root = Path(__file__).resolve().parents[1]
source = root / 'geo_segment'
config = configparser.ConfigParser()
config.read(source / 'metadata.txt', encoding='utf-8')
version = config['general']['version']
output = root / 'dist' / ('geo_segment-' + version + '.zip')
output.parent.mkdir(exist_ok=True)
with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
    for path in sorted(source.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            archive.write(path, path.relative_to(root))
with ZipFile(output) as archive:
    assert archive.testzip() is None
    assert 'geo_segment/__init__.py' in archive.namelist()
    assert 'geo_segment/metadata.txt' in archive.namelist()
print(output)
