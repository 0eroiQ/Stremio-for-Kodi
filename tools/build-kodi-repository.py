#!/usr/bin/env python3
"""Publish a released addon ZIP and repository installer to a Kodi feed folder."""
import argparse
import hashlib
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(package, output):
    package, output = Path(package), Path(output)
    with zipfile.ZipFile(package) as archive:
        addon = ET.fromstring(archive.read('script.stremioelec/addon.xml'))
        expected = f"script.stremioelec-{addon.attrib['version']}.zip"
        if addon.attrib['id'] != 'script.stremioelec' or package.name != expected:
            raise ValueError('Released package identity/version does not match its filename')
        if archive.testzip() is not None:
            raise ValueError('Corrupt addon ZIP')
    repo_source = ROOT / 'repository/repository.stremioforkodi'
    repo = ET.parse(repo_source / 'addon.xml').getroot()
    repo_dir = output / repo.attrib['id']
    addon_dir = output / addon.attrib['id']
    repo_dir.mkdir(parents=True, exist_ok=True)
    addon_dir.mkdir(parents=True, exist_ok=True)
    repo_zip = repo_dir / f"{repo.attrib['id']}-{repo.attrib['version']}.zip"
    with zipfile.ZipFile(repo_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(repo_source.iterdir()):
            if source.is_file():
                archive.write(source, f"{repo.attrib['id']}/{source.name}")
    shutil.copyfile(package, addon_dir / package.name)
    # Preserve the exact published addon package; never rebuild release contents.
    index = ET.Element('addons')
    index.extend([addon, repo])
    data = ET.tostring(index, encoding='utf-8', xml_declaration=True)
    (output / 'addons.xml').write_bytes(data)
    (output / 'addons.xml.sha256').write_text(hashlib.sha256(data).hexdigest() + '\n')
    (output / 'README.md').write_text(
        '# Stremio for Kodi repository\n\n'
        'Install repository.stremioforkodi/repository.stremioforkodi-1.0.0.zip in Kodi, '
        'then choose Install from repository > Stremio for Kodi Repository > Program add-ons.\n')
    return repo_zip


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(build(args.package, args.output))
