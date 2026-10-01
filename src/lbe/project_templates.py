"""Provenance and explicit upgrades for editable application templates."""

from hashlib import sha256
import json
from pathlib import Path
import shutil

from .project import write_json

MANIFEST = '.lbe-template.json'
JOURNAL = '.lbe-template-upgrade.json'


def recover_template_upgrade(directory):
    directory = Path(directory).resolve()
    journal = directory / JOURNAL
    if not journal.exists():
        return
    record = json.loads(journal.read_text(encoding='utf-8'))
    if record.get('phase') not in ('prepared', 'committed'):
        raise ValueError('Invalid template recovery record')
    backup = (directory / record['backup']).resolve()
    if not backup.is_relative_to(directory):
        raise ValueError('Invalid template backup path')
    if record['phase'] == 'prepared':
        for name, status in record['files'].items():
            if Path(name).name != name:
                raise ValueError('Invalid template source path')
            original = backup / name
            if original.exists():
                shutil.copyfile(original, directory / name)
            elif status == 'new':
                (directory / name).unlink(missing_ok=True)
            (directory / ('.' + name + '.upgrade')).unlink(missing_ok=True)
        shutil.copyfile(backup / MANIFEST, directory / MANIFEST)
    journal.unlink()


def _hash(path):
    return sha256(path.read_bytes()).hexdigest()


def initialize_template(directory, template, *, entry='app.py'):
    directory, template = Path(directory), Path(template)
    if (directory / entry).exists():
        return
    managed = {}
    for source in sorted(template.glob('*.py')):
        destination = directory / source.name
        if not destination.exists():
            shutil.copyfile(source, destination)
            managed[source.name] = _hash(source)
    write_json(directory / MANIFEST, dict(version=1, template=template.name, files=managed))


def template_updates(directory, template):
    """Describe updates without touching user files; customized files are never overwritten."""
    directory, template = Path(directory).resolve(), Path(template).resolve()
    manifest = directory / MANIFEST
    if not manifest.exists():
        return {'unmanaged': 'Existing project has no template provenance; upgrade files manually.'}
    baseline = json.loads(manifest.read_text(encoding='utf-8'))
    if baseline.get('version') != 1 or baseline.get('template') != template.name:
        raise ValueError('Template manifest version/name does not match')
    result = {}
    for source in sorted(template.glob('*.py')):
        destination = directory / source.name
        expected = baseline['files'].get(source.name)
        if expected is None:
            result[source.name] = 'new' if not destination.exists() else 'customized'
        elif not destination.exists():
            result[source.name] = 'customized'
        elif _hash(destination) != expected:
            result[source.name] = 'customized'
        else:
            result[source.name] = 'current' if _hash(source) == expected else 'update'
    return result


def upgrade_template(directory, template):
    """Upgrade managed, unchanged files explicitly, retaining a recoverable backup."""
    directory, template = Path(directory).resolve(), Path(template).resolve()
    recover_template_upgrade(directory)
    result = template_updates(directory, template)
    if 'unmanaged' in result:
        raise ValueError(result['unmanaged'])
    manifest_path = directory / MANIFEST
    baseline = json.loads(manifest_path.read_text(encoding='utf-8'))
    paths = [name for name, status in result.items() if status in ('new', 'update')]
    if not paths:
        return result
    revision = sha256(json.dumps(baseline, sort_keys=True).encode()).hexdigest()[:16]
    backup = directory / '.lbe-template-backups' / revision
    backup.mkdir(parents=True, exist_ok=True)
    # Backups and provenance are durable before the first replacement. A failed upgrade
    # rolls back; startup also recovers interrupted upgrades from this directory.
    shutil.copyfile(manifest_path, backup / MANIFEST)
    for name in paths:
        if (directory / name).exists():
            shutil.copyfile(directory / name, backup / name)
    record = dict(phase='prepared', backup=backup.relative_to(directory).as_posix(),
                  files={name: result[name] for name in paths})
    write_json(directory / JOURNAL, record)
    try:
        for name in paths:
            destination = directory / name
            temporary = directory / ('.' + name + '.upgrade')
            shutil.copyfile(template / name, temporary)
            temporary.replace(destination)
        updated = dict(baseline, files=dict(baseline['files']))
        updated['files'].update({name: _hash(template / name) for name in paths})
        write_json(manifest_path, updated)
        write_json(directory / JOURNAL, dict(record, phase='committed'))
    except Exception:
        recover_template_upgrade(directory)
        raise
    recover_template_upgrade(directory)
    return result
