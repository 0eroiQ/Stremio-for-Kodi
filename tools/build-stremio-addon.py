#!/usr/bin/env python3
"""Build the single installable Stremio for Kodi ZIP from checked-in sources."""
import argparse
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT


def build(output):
    addon = ET.parse(SOURCE / 'addon.xml').getroot()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{addon.attrib['id']}-{addon.attrib['version']}.zip"
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(SOURCE.rglob('*')):
            relative = path.relative_to(SOURCE)
            if relative.parts[0] in {'.git', '.github', 'tools', 'tests', 'dist', '.venv'}:
                continue
            if relative.parts[0] in {'README.md', '.gitignore'}:
                continue
            if not path.is_file() or '__pycache__' in relative.parts or path.name.startswith('.') or path.suffix == '.pyc':
                continue
            archive.write(path, str(Path(addon.attrib['id']) / relative))
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='Directory for the installable ZIP')
    print(build(parser.parse_args().output))
