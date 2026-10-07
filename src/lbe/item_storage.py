"""Native UUID item documents; no named-collection projections or migrations."""
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from uuid import UUID


ITEM_TYPES = {}


def register_item_type(item_type, *, name=None):
    """Opt in an application dataclass codec without modifying Entity or Core."""
    name = name or item_type.__name__
    if not is_dataclass(item_type) or not {'id', 'name'} <= {field.name for field in fields(item_type)}:
        raise TypeError('Persistent item types must be dataclasses with id and name fields')
    if not isinstance(name, str) or not name or name in ('Component', 'InheritedComponent', 'Tag', 'Relation', 'Parent', 'System', 'Script'):
        raise ValueError('Choose a distinct persistent type name')
    if name in ITEM_TYPES and ITEM_TYPES[name] is not item_type:
        raise ValueError('Persistent type name is already registered')
    ITEM_TYPES[name] = item_type
    return item_type


@dataclass(frozen=True)
class StoredSource:
    """An authoring declaration not yet compiled/linked for execution."""
    path: str
    asset_id: UUID | None = None
    source: str | None = None
    references: tuple = ()
    components: tuple = ()


def validate_record(record):
    if not isinstance(record, dict) or set(record) != {'id', 'items'}:
        raise ValueError('Entity documents require only id and UUID-keyed items; legacy fields are not supported')
    UUID(record['id'])
    if not isinstance(record['items'], dict):
        raise ValueError('Entity items must be a UUID-keyed dictionary')
    seen = set()
    fields = {'Component': {'value'}, 'InheritedComponent': {'source', 'patch'},
              'Tag': set(), 'Relation': {'target'}, 'Parent': {'target', 'position'},
              'System': {'definition'}, 'Script': {'definition'}}
    fields.update({name: {'data'} for name in ITEM_TYPES})
    for identity, item in record['items'].items():
        UUID(identity)
        if not isinstance(item, dict) or item.get('type') not in fields:
            raise ValueError('Unknown persistent item type')
        kind, name = item['type'], item.get('name')
        if set(item) != {'type', 'name'} | fields[kind]:
            raise ValueError(f'Invalid {kind} fields')
        if not isinstance(name, str) or not name:
            raise ValueError('Item names must be nonempty strings')
        from .items import Component
        category = ('Component' if kind == 'InheritedComponent' or kind in ITEM_TYPES
                    and issubclass(ITEM_TYPES[kind], Component) else kind)
        if (category, name) in seen:
            raise ValueError(f'Duplicate {category} name: {name}')
        seen.add((category, name))
        if kind == 'InheritedComponent':
            UUID(item['source'])
        if kind in ('Relation', 'Parent'):
            UUID(item['target'])
        if kind == 'Parent':
            if name != 'parent' or type(item['position']) is not int or item['position'] < 0:
                raise ValueError('Invalid parent declaration or sibling position')
        if kind in ('System', 'Script'):
            definition = item['definition']
            if not isinstance(definition, dict) or set(definition) - {'path', 'source', 'asset_id'} or 'path' not in definition:
                raise ValueError('Invalid behaviour source declaration')
            if not isinstance(definition['path'], str):
                raise ValueError('Behaviour path must be a string')
            if 'source' in definition and not isinstance(definition['source'], str):
                raise ValueError('Inline source must be text')
            if definition.get('asset_id') is not None:
                UUID(definition['asset_id'])
    return record


def encode_definition(definition, project_dir):
    path = definition.path
    declaration = {'path': path, 'asset_id': str(definition.asset_id) if definition.asset_id else None}
    if project_dir is not None and not path.startswith('<'):
        try:
            declaration['path'] = (Path(project_dir) / path).resolve().relative_to(Path(project_dir).resolve()).as_posix()
        except ValueError:
            pass
    if isinstance(definition, StoredSource):
        if definition.source is not None:
            declaration['source'] = definition.source
        return declaration
    if project_dir is not None and not path.startswith('<'):
        try:
            declaration['path'] = (Path(project_dir) / path).resolve().relative_to(Path(project_dir).resolve()).as_posix()
            return declaration
        except ValueError:
            pass
    declaration['source'] = definition.source
    return declaration


def encode_items(entity, *, encode, project_dir=None, known_ids=None, transient_relations=(), on_unsupported='error'):
    from .items import Component, InheritedComponent, Tag, Relation, Parent
    from .systems import SystemInstance
    from .scripts import ScriptInstance
    result = {}
    for item in entity.items.values():
        record = {'type': type(item).__name__, 'name': item.name}
        registered = next((name for name, item_type in ITEM_TYPES.items() if type(item) is item_type), None)
        if registered is not None:
            record['type'] = registered
            record['data'] = encode({field.name: getattr(item, field.name) for field in fields(item)
                                     if field.init and field.name not in ('id', 'name')})
        elif type(item) is Component:
            try:
                value = encode(item.value)
            except (TypeError, ValueError) as error:
                raise type(error)(f'Component {item.name!r} on entity {entity.id} cannot be serialized: {error}') from None
            if item.value is not None and value is None and on_unsupported == 'skip':
                continue
            record['value'] = value
        elif type(item) is InheritedComponent:
            record.update(source=str(item.source), patch=encode(item.patch))
        elif type(item) is Tag:
            pass
        elif type(item) is Relation:
            if item.name in transient_relations:
                continue
            if known_ids is not None and item.target in entity.runtime._entities and item.target not in known_ids:
                raise ValueError(f'Relation {item.name!r} targets an entity outside the saved project')
            record['target'] = str(item.target)
        elif type(item) is Parent:
            parent = entity.parent
            while parent is not None and known_ids is not None and parent.id not in known_ids:
                parent = parent.parent
            if parent is None and item.target in entity.runtime._entities:
                continue
            record.update(target=str(parent.id if parent else item.target),
                          position=entity.parent.children.index(entity) if entity.parent else 0)
        elif isinstance(item, SystemInstance):
            record['type'] = 'Script' if isinstance(item, ScriptInstance) else 'System'
            record['definition'] = encode_definition(item.definition, project_dir)
        else:
            raise TypeError(f'Unsupported persistent item: {type(item).__name__}')
        result[str(item.id)] = record
    return result


def compile_source(declaration, runtime, project_dir):
    from .systems import SystemDefinition
    source, path = declaration.source, declaration.path
    if source is None:
        if project_dir is None:
            raise ValueError('A project directory is required for file-backed behaviours')
        path = (Path(project_dir) / path).resolve()
        if not path.is_relative_to(Path(project_dir).resolve()):
            raise ValueError('Behaviour path must stay inside the project')
        source = path.read_text(encoding='utf-8')
    return SystemDefinition(source, str(path), declaration.asset_id)
