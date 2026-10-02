#!/usr/bin/env python3
"""Publish immutable addon packages plus all declared artwork to a Kodi feed."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import shutil
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ART_TYPES = {'icon', 'fanart', 'banner', 'clearlogo', 'screenshot'}


def asset_paths(addon):
    """Only package-relative image paths may be copied to the public feed."""
    assets = addon.find("extension[@point='xbmc.addon.metadata']/assets")
    if assets is None:
        return []
    result = []
    for node in assets:
        value = (node.text or '').strip()
        if node.tag not in ART_TYPES or not value:
            continue
        path = PurePosixPath(value)
        if (path.is_absolute() or '..' in path.parts or '\\' in value
                or ':' in value or path.suffix.lower() not in ('.png', '.jpg', '.jpeg')):
            raise ValueError('Artwork must use safe, relative image paths')
        if value not in result:
            result.append(value)
    return result


def build(package, output):
    package, output = Path(package), Path(output)
    with zipfile.ZipFile(package) as archive:
        addon = ET.fromstring(archive.read('script.stremioelec/addon.xml'))
        expected = 'script.stremioelec-{}.zip'.format(addon.attrib['version'])
        if addon.attrib['id'] != 'script.stremioelec' or package.name != expected:
            raise ValueError('Released package identity/version does not match filename')
        if archive.testzip() is not None:
            raise ValueError('Corrupt addon ZIP')
        # Read declared artwork from the exact release, not the mutable worktree.
        art = {name: archive.read('script.stremioelec/' + name)
               for name in asset_paths(addon)}
    repo_source = ROOT / 'repository/repository.stremioforkodi'
    connector_source = ROOT / 'service.mkga.connector'
    connector = ET.parse(connector_source / 'addon.xml').getroot()
    if connector.attrib.get('id') != 'service.mkga.connector':
        raise ValueError('Invalid MKGA Connector identity')
    repo = ET.parse(repo_source / 'addon.xml').getroot()
    repo_art = {name: (repo_source / name).read_bytes() for name in asset_paths(repo)}
    repo_dir = output / repo.attrib['id']
    addon_dir = output / addon.attrib['id']
    connector_dir = output / connector.attrib['id']
    repo_dir.mkdir(parents=True, exist_ok=True)
    addon_dir.mkdir(parents=True, exist_ok=True)
    connector_dir.mkdir(parents=True, exist_ok=True)
    repo_zip = repo_dir / '{}-{}.zip'.format(repo.attrib['id'], repo.attrib['version'])
    with zipfile.ZipFile(repo_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(repo_source.rglob('*')):
            rel = source.relative_to(repo_source)
            if (not source.is_file() or source.is_symlink()
                    or any(p.startswith('.') or p == '__pycache__' for p in rel.parts)):
                continue
            archive.write(source, str(PurePosixPath(repo.attrib['id']) / rel.as_posix()))
    shutil.copyfile(package, addon_dir / package.name)
    connector_zip = connector_dir / '{}-{}.zip'.format(connector.attrib['id'], connector.attrib['version'])
    with zipfile.ZipFile(connector_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(connector_source.rglob('*')):
            rel = source.relative_to(connector_source)
            if (not source.is_file() or source.is_symlink()
                    or any(p.startswith('.') or p == '__pycache__' for p in rel.parts)):
                continue
            archive.write(source, str(PurePosixPath(connector.attrib['id']) / rel.as_posix()))
    (connector_dir / 'addon.xml').write_bytes(ET.tostring(connector, encoding='utf-8', xml_declaration=True))
    for directory, images in ((addon_dir, art), (repo_dir, repo_art)):
        for name, data in images.items():
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    # Publish both manifests and previews beside the original immutable ZIP.
    (addon_dir / 'addon.xml').write_bytes(ET.tostring(addon, encoding='utf-8', xml_declaration=True))
    (repo_dir / 'addon.xml').write_bytes((repo_source / 'addon.xml').read_bytes())
    index = ET.Element('addons')
    index.extend([addon, connector, repo])
    data = ET.tostring(index, encoding='utf-8', xml_declaration=True)
    (output / 'addons.xml').write_bytes(data)
    (output / 'addons.xml.sha256').write_text(hashlib.sha256(data).hexdigest() + '\n')
    (output / 'README.md').write_text(
        '# MKGA Repository\n\n'
        'Install {}/{} in Kodi, then choose Install from repository > '
        'MKGA Repository > Program add-ons. It contains Stremio for Kodi and MKGA Connector.\n'.format(repo.attrib['id'], repo_zip.name))
    return repo_zip


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(build(args.package, args.output))
