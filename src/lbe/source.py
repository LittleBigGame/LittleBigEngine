"""Recoverable source activation across every attachment of a project file."""

import base64
from dataclasses import replace
import json
from pathlib import Path
import tempfile

from .checkpoint import RuntimeCheckpoint
from .project import write_json
from .systems import SystemDefinition

JOURNAL = '.lbe-source-operation.json'


class SourceActivationError(RuntimeError):
    pass


def write_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, suffix='.tmp') as stream:
            temporary = Path(stream.name)
            stream.write(content)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _saved(path):
    return base64.b64encode(path.read_bytes()).decode('ascii') if path.exists() else None


def recover_source_operation(directory):
    """Restore source and project bytes after an interrupted, uncommitted save."""
    directory = Path(directory).resolve()
    journal = directory / JOURNAL
    if not journal.exists():
        return
    record = json.loads(journal.read_text(encoding='utf-8'))
    relative = Path(record['path'])
    source = (directory / relative).resolve()
    if relative.is_absolute() or not source.is_relative_to(directory) or source.suffix != '.py':
        raise ValueError('Invalid source recovery path')
    if record.get('phase') not in ('prepared', 'committed'):
        raise ValueError('Invalid source recovery phase')
    if record['phase'] == 'prepared':
        # Decode both records before changing either file.
        records = [(source, record['source']), (directory / 'project.json', record['project'])]
        decoded = [(path, base64.b64decode(data, validate=True) if data is not None else None)
                   for path, data in records]
        for path, data in decoded:
            if data is None:
                path.unlink(missing_ok=True)
            else:
                write_bytes(path, data)
    journal.unlink()


def activate_source(runtime, directory, path, source, *, save):
    """Compile, activate all matching attachments, and save as one recovery unit.

    A failed edit is retained under .lbe-drafts with the original relative path.
    Managed runtime state, active source, and project bytes return to their prior
    versions. External Python side effects remain outside the recovery boundary.
    """
    directory = Path(directory).resolve()
    path = Path(path).resolve()
    if not path.is_relative_to(directory) or path.suffix != '.py':
        raise ValueError('Source must be a .py file inside the project')
    relative = path.relative_to(directory)
    draft = directory / '.lbe-drafts' / relative
    try:
        definition = SystemDefinition(source, str(path))
    except Exception as error:
        write_bytes(draft, source.encode('utf-8'))
        raise SourceActivationError(f'{type(error).__name__}: {error}; draft saved to {draft}') from error
    recover_source_operation(directory)
    attachments = [(collection, name, instance)
                   for entity in runtime.entities for collection in (entity.systems, entity.scripts)
                   for name, instance in tuple(collection.items())
                   if Path(instance.definition.path).resolve() == path]
    checkpoint = RuntimeCheckpoint(runtime)
    record = dict(phase='prepared', path=relative.as_posix(), source=_saved(path),
                  project=_saved(directory / 'project.json'))
    write_json(directory / JOURNAL, record)
    try:
        write_bytes(path, source.encode('utf-8'))
        runtime.assets.invalidate(path)
        for collection, name, previous in attachments:
            candidate = replace(definition, asset_id=previous.definition.asset_id)
            active = collection.reload(name, candidate)
            if active is previous or not active.running:
                detail = active.errors[-1].message if active.errors else 'activation failed'
                raise SourceActivationError(f'{name}: {detail}')
        save()
        write_json(directory / JOURNAL, dict(record, phase='committed'))
    except Exception as error:
        checkpoint.restore()
        recover_source_operation(directory)
        write_bytes(draft, source.encode('utf-8'))
        raise SourceActivationError(f'{type(error).__name__}: {error}; draft saved to {draft}') from error
    recover_source_operation(directory)
    return len(attachments)
