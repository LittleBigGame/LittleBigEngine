"""Validated file operations shared by project tools, with recovery across interrupted writes."""

import json
from pathlib import Path
import shutil
import tempfile

from .project import restoration, write_json
from .events import Diagnostic

JOURNAL = '.lbe-file-operation.json'


def recover_file_operation(directory):
    directory = Path(directory).resolve()
    journal = directory / JOURNAL
    if not journal.exists():
        return
    record = json.loads(journal.read_text(encoding='utf-8'))
    if record.get('phase') not in ('prepared', 'committed') or record.get('operation') not in ('relocate', 'delete'):
        raise ValueError('Invalid file-operation recovery record')
    source, destination = (directory / record[key] for key in ('source', 'destination'))
    if any(not path.resolve().is_relative_to(directory) for path in (source, destination)):
        raise ValueError('Invalid file-operation recovery path')
    if record['phase'] == 'prepared':
        if destination.exists() and not source.exists():
            destination.rename(source)
        project = directory / 'project.json'
        if record['project'] is None:
            project.unlink(missing_ok=True)
        else:
            write_json(project, record['project'])
    elif record['operation'] == 'delete' and destination.exists():
        shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
    journal.unlink()


class ProjectFiles:
    def __init__(self, runtime, directory):
        self.runtime = runtime
        self.directory = Path(directory).resolve()

    def _path(self, path):
        path = Path(path)
        path = path.resolve() if path.is_absolute() else (self.directory / path).resolve()
        if not path.is_relative_to(self.directory) or path == self.directory:
            raise ValueError('File operation must stay inside the project')
        if path == self.directory / 'app.py' or path == self.directory / 'project.json':
            raise ValueError('The application entry point and project state cannot be relocated or deleted')
        return path

    def relocate(self, source, destination, *, save):
        source, destination = self._path(source), self._path(destination)
        if source == destination:
            return destination
        if not source.exists():
            raise FileNotFoundError(source)
        if destination.exists():
            raise FileExistsError(destination)
        if destination.is_relative_to(source) or not destination.parent.is_dir():
            raise ValueError('Invalid destination directory')
        registry = self.runtime.assets.registry
        before = registry.to_dict()
        candidate = type(registry)(self.directory)
        candidate.from_dict(before)
        candidate.relocate(source, destination)
        changes = []
        for entity in self.runtime.entities:
            for name, instance in entity.systems.items():
                path = Path(instance.definition.path).resolve()
                if path == source or path.is_relative_to(source):
                    new_path = destination / path.relative_to(source) if path != source else destination
                    new_name = new_path.stem if name == path.stem else name
                    if new_name != name and new_name in entity.systems:
                        raise ValueError(f'System name collision: {new_name}')
                    changes.append((entity, name, new_name, path, new_path))
        pending = restoration(self.runtime)
        declarations = {eid: {name: dict(data) for name, data in systems.items()}
                        for eid, systems in pending.systems.items()}
        journal = self._prepare(source, destination, 'relocate')
        try:
            source.rename(destination)
            registry.from_dict(candidate.to_dict())
            for entity, name, new_name, _, path in changes:
                entity.systems.relocate(name, path, new_name=new_name)
            for systems in pending.systems.values():
                for declaration in systems.values():
                    if 'source' not in declaration and declaration.get('path'):
                        path = (self.directory / declaration['path']).resolve()
                        if path == source or path.is_relative_to(source):
                            path = destination / path.relative_to(source) if path != source else destination
                            declaration['path'] = path.relative_to(self.directory).as_posix()
            save()
            self._commit(journal)
        except Exception:
            for entity, name, new_name, path, _ in reversed(changes):
                if entity.alive and new_name in entity.systems:
                    entity.systems.relocate(new_name, path, new_name=name)
            registry.from_dict(before)
            pending.systems = declarations
            recover_file_operation(self.directory)
            raise
        for _, _, _, old_path, new_path in changes:
            self.runtime.assets.invalidate(old_path)
            self.runtime.assets.invalidate(new_path)
        return destination

    def delete(self, path, *, save):
        source = self._path(path)
        if not source.exists():
            raise FileNotFoundError(source)
        # Keep UUID declarations for references to missing files; replacing the file recovers them.
        with tempfile.TemporaryDirectory(prefix='.lbe-delete-', dir=self.directory) as scratch:
            destination = Path(scratch) / source.name
            journal = self._prepare(source, destination, 'delete')
            try:
                source.rename(destination)
                save()
                self._commit(journal)
            except Exception:
                recover_file_operation(self.directory)
                raise

    def _prepare(self, source, destination, operation):
        recover_file_operation(self.directory)
        project = self.directory / 'project.json'
        record = dict(source=source.relative_to(self.directory).as_posix(),
                      destination=destination.relative_to(self.directory).as_posix(),
                      operation=operation, phase='prepared',
                      project=json.loads(project.read_text(encoding='utf-8')) if project.exists() else None)
        write_json(self.directory / JOURNAL, record)
        return record

    def _commit(self, record):
        record['phase'] = 'committed'
        write_json(self.directory / JOURNAL, record)
        try:
            recover_file_operation(self.directory)
        except OSError as error:
            # The operation is committed. Retain its journal for cleanup on restart.
            restoration(self.runtime).diagnostics.append(Diagnostic('project.files', f'Cleanup deferred: {error}'))
