"""LittleBigEngine: generic entities and independent script systems."""

from .core import Entity, Query, Runtime
from .events import Change, Diagnostic, Events
from .scripts import ScriptInstance
from .systems import Assets, SystemDefinition, SystemInstance
from .items import Component, InheritedComponent, Tag, Relation, Parent, compose
from .linker import Handle, Linker
from .item_storage import register_item_type
System = SystemInstance
Script = ScriptInstance

__all__ = [
    "Assets", "Change", "Diagnostic", "Entity", "Events", "Query", "Runtime",
    "SystemDefinition", "SystemInstance", "ScriptInstance",
    "Component", "InheritedComponent", "Tag", "Relation", "Parent", "compose", "Handle", "Linker",
    "System", "Script", "register_item_type",
]
