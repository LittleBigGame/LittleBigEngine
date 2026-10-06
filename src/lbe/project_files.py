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
    if record.get('phase') not in ('prepared', 'committed') or record.get('operation') not in ('relocate', 'delete', 'import'):
        raise ValueError('Invalid file-operation recovery record')
    source, destination = (directory / record[key] for key in ('source', 'destination'))
    if any(not path.resolve().is_relative_to(directory) for path in (source, destination)):
        raise ValueError('Invalid file-operation recovery path')
    if record['operation'] == 'import' and (source.relative_to(directory).parts[0] != '.lbe-import' or source == destination):
        raise ValueError('Invalid import staging path')
    if record['phase'] == 'prepared':
        if destination.exists() and not source.exists():
            destination.rename(source)
        project = directory / 'project.json'
        if record['project'] is None:
            project.unlink(missing_ok=True)
        else:
            write_json(project, record['project'])
    elif record['operation'] == 'delete' and not record.get('retain') and destination.exists():
        shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
    if record['operation'] == 'import':
        source.unlink(missing_ok=True)
    journal.unlink()


class ProjectFiles:
    def __init__(self, runtime, directory):
        self.runtime = runtime
        self.directory = Path(directory).resolve()
        self._undo = []
        self._redo = []
        self._replaying = False
        from .history import History
        self.history = History()
        self._suspended = {}

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
            for collection in (entity.systems,entity.scripts):
              for name, instance in collection.items():
                path = Path(instance.definition.path).resolve()
                if path == source or path.is_relative_to(source):
                    new_path = destination / path.relative_to(source) if path != source else destination
                    new_name = new_path.stem if name == path.stem else name
                    if new_name != name and new_name in collection:
                        raise ValueError(f'System name collision: {new_name}')
                    changes.append((entity, collection, name, new_name, path, new_path))
        pending = restoration(self.runtime)
        script_declarations = {eid: {name: dict(data) for name,data in scripts.items()} for eid,scripts in pending.scripts.items()}
        declarations = {eid: {name: dict(data) for name, data in systems.items()}
                        for eid, systems in pending.systems.items()}
        journal = self._prepare(source, destination, 'relocate')
        try:
            source.rename(destination)
            registry.from_dict(candidate.to_dict())
            for entity, collection, name, new_name, _, path in changes:
                collection.relocate(name, path, new_name=new_name)
            for systems in tuple(pending.systems.values())+tuple(pending.scripts.values()):
                for declaration in systems.values():
                    if 'source' not in declaration and declaration.get('path'):
                        path = (self.directory / declaration['path']).resolve()
                        if path == source or path.is_relative_to(source):
                            path = destination / path.relative_to(source) if path != source else destination
                            declaration['path'] = path.relative_to(self.directory).as_posix()
            save()
            self._commit(journal)
        except Exception:
            for entity, collection, name, new_name, path, _ in reversed(changes):
                if entity.alive and new_name in collection:
                    collection.relocate(new_name, path, new_name=name)
            registry.from_dict(before)
            pending.systems = declarations
            pending.scripts = script_declarations
            recover_file_operation(self.directory)
            raise
        for _, _, _, _, old_path, new_path in changes:
            self.runtime.assets.invalidate(old_path)
            self.runtime.assets.invalidate(new_path)
        self._record(('relocate', source, destination), save)
        return destination

    def import_file(self, source, destination, *, save):
        """Copy an external file into the project without overwriting existing files.

        Identity, bytes and project state commit together. Undo retains the imported
        UUID and moves the copy to recoverable project trash, never the original.
        """
        from uuid import uuid4
        source = Path(source).resolve()
        destination = self._path(destination)
        if not source.is_file():
            raise FileNotFoundError(source)
        if destination.exists():
            raise FileExistsError(destination)
        recover_file_operation(self.directory)
        registry = self.runtime.assets.registry
        before = registry.to_dict()
        staging = self.directory / '.lbe-import' / str(uuid4()) / source.name
        staging.parent.mkdir(parents=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, staging)
            journal = self._prepare(staging, destination, 'import')
            try:
                if destination.exists():
                    raise FileExistsError(destination)
                staging.rename(destination)
                registry.register(destination)
                save()
                self._commit(journal)
            except Exception:
                registry.from_dict(before)
                recover_file_operation(self.directory)
                raise
        finally:
            staging.unlink(missing_ok=True)
        self.record_create(destination, save=save)
        return registry.get_ref(destination)

    def delete(self, path, *, save):
        source = self._path(path)
        if not source.exists():
            raise FileNotFoundError(source)
        # Retain source contents outside the visible asset tree for reversible edits.
        from uuid import uuid4
        destination = self.directory / '.lbe-trash' / str(uuid4()) / source.name
        destination.parent.mkdir(parents=True)
        journal = self._prepare(source, destination, 'delete')
        journal['retain'] = True
        write_json(self.directory / JOURNAL, journal)
        try:
            source.rename(destination)
            save()
            self._commit(journal)
        except Exception:
            recover_file_operation(self.directory)
            raise
        self._sync_sources(source, restore=False)
        self._record(('delete', source, destination), save)

    def _sync_sources(self, path, *, restore):
        if not restore:
            for entity in self.runtime.entities:
              for collection in (entity.systems,entity.scripts):
                for name, instance in tuple(collection.items()):
                    source = Path(instance.definition.path).resolve() if instance.definition.path else None
                    if source is not None and (source == path or source.is_relative_to(path)) and instance.running:
                        self._suspended[(entity.id,name,id(collection))] = (collection,instance)
                        instance.stop()
                        self.runtime.assets.invalidate(source)
        else:
            for (identity,name,role), (collection,instance) in tuple(self._suspended.items()):
                source = Path(instance.definition.path).resolve()
                if source != path and not source.is_relative_to(path):
                    continue
                entity = self.runtime.resolve(identity)
                if entity is not None and collection.get(name) is instance and source.is_file():
                    collection.reload(name,self.runtime.assets.system(source))
                self._suspended.pop((identity,name,role),None)

    def _record(self, command, save):
        if not self._replaying:
            self._undo.append(command)
            self._redo.clear()
            self.history.record(lambda:self.undo(save=save), lambda:self.undo(save=save,redo=True), command[0]+" project file")

    def record_create(self, path, *, save=lambda:None):
        from uuid import uuid4
        path = self._path(path)
        destination = self.directory / '.lbe-trash' / str(uuid4()) / path.name
        self._record(('create', path, destination), save)

    def undo(self, *, save, redo=False):
        source_stack, target_stack = (self._redo,self._undo) if redo else (self._undo,self._redo)
        if not source_stack:
            return None
        command = source_stack[-1]
        kind, original, destination = command
        self._replaying = True
        try:
            if kind == 'relocate':
                self.relocate(original if redo else destination, destination if redo else original, save=save)
                result = destination if redo else original
            else:
                restore = (kind == 'delete' and not redo) or (kind == 'create' and redo)
                source, target = (destination,original) if restore else (original,destination)
                source, target = self._path(source), self._path(target)
                if target.exists():
                    raise FileExistsError(target)
                target.parent.mkdir(parents=True,exist_ok=True)
                journal = self._prepare(source,target,'relocate')
                try:
                    source.rename(target)
                    save()
                    self._commit(journal)
                except Exception:
                    recover_file_operation(self.directory)
                    raise
                self._sync_sources(original, restore=restore)
                result = original
            source_stack.pop()
            target_stack.append(command)
            return result
        finally:
            self._replaying = False

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
