"""Comprehensive independent tests for Entity Hierarchy, Queries, and Spawning.

Derives tests from observable user requirements and kernel contracts:
1. Hierarchy Linking & Unlinking (add/remove child, parent/children properties, restart persistence).
2. Child Queries on EntityProxy (query_children with components, find_child by name, recursive traversal, cycle protection).
3. World Queries (kernel.query and entity.world.query with component filtering).
4. Entity Spawning (spawning from dict, cloning entities, unique StorageIDs, deep copy isolation, as_child=True).
5. Script Integration with Hierarchy & Queries (script querying children, script spawning during tick).
"""

import pytest

from LBE import (
    EntityProxy,
    Error,
    Kernel,
    WorldProxy,
)
from LBE.types import (
    EntityTypeMismatchError,
    InvalidResourceDataError,
    RuntimeIDNotFoundOnMemoryError,
)


class TestHierarchyLinkingAndUnlinking:
    """Tests for parent-child relationship management on Kernel and EntityProxy."""

    def test_add_and_remove_child_via_proxy(self, tmp_path):
        kernel = Kernel(tmp_path)
        parent = kernel.get_entity_proxy(kernel.create_entity(name="Parent"))
        child = kernel.get_entity_proxy(kernel.create_entity(name="Child"))

        assert parent.children == []
        assert child.parent is None

        # Add child via proxy
        parent.add_child(child)
        assert len(parent.children) == 1
        assert parent.children[0].id == child.id
        assert child.parent is not None
        assert child.parent.id == parent.id
        assert kernel.is_dirty(parent.id)
        assert kernel.is_dirty(child.id)

        # Remove child via proxy
        parent.remove_child(child)
        assert len(parent.children) == 0
        assert child.parent is None

    def test_parent_property_assignment_and_reparenting(self, tmp_path):
        kernel = Kernel(tmp_path)
        p1 = kernel.get_entity_proxy(kernel.create_entity(name="Parent1"))
        p2 = kernel.get_entity_proxy(kernel.create_entity(name="Parent2"))
        child = kernel.get_entity_proxy(kernel.create_entity(name="Child"))

        # Attach via property assignment
        child.parent = p1
        assert child.parent.id == p1.id
        assert len(p1.children) == 1

        # Re-parent to Parent2 (must automatically detach from Parent1)
        child.parent = p2
        assert child.parent.id == p2.id
        assert len(p2.children) == 1
        assert len(p1.children) == 0

        # Detach via assigning None
        child.parent = None
        assert child.parent is None
        assert len(p2.children) == 0

    def test_hierarchy_persistence_roundtrip(self, tmp_path):
        kernel = Kernel(tmp_path)
        p_id = kernel.create_entity(name="RootNode", components={"Transform": {"x": 0}})
        c_id = kernel.create_entity(name="ChildNode", components={"Transform": {"x": 5}})
        parent = kernel.get_entity_proxy(p_id)
        child = kernel.get_entity_proxy(c_id)

        parent.add_child(child)
        p_sid = parent.storage_id
        c_sid = child.storage_id

        assert kernel.save_dirty_resources() is None
        assert not kernel.is_dirty(p_id)
        assert not kernel.is_dirty(c_id)

        # Reload in a completely fresh Kernel session
        fresh = Kernel(tmp_path)
        loaded_p = fresh.load_entity(p_sid)
        assert not isinstance(loaded_p, Error)

        fresh_parent = fresh.get_entity_proxy(loaded_p)
        assert len(fresh_parent.children) == 1
        fresh_child = fresh_parent.children[0]
        assert fresh_child.name == "ChildNode"
        assert fresh_child.transform.x == 5
        assert fresh_child.parent.id == fresh_parent.id

    def test_invalid_hierarchy_operations_return_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        e = kernel.create_entity()

        # Non-existent parent/child
        err1 = kernel.add_entity_child(999999, e)
        assert isinstance(err1, Error)
        assert err1.code == RuntimeIDNotFoundOnMemoryError

        err2 = kernel.add_entity_child(e, 999999)
        assert isinstance(err2, Error)
        assert err2.code == RuntimeIDNotFoundOnMemoryError

        # Non-entity resource
        config_res = kernel.create_resource(resource_type=99, resource_data={"test": 1})
        err3 = kernel.add_entity_child(config_res, e)
        assert isinstance(err3, Error)
        assert err3.code == EntityTypeMismatchError

    def test_ancestor_cycle_detection_prevents_cyclic_graphs(self, tmp_path):
        kernel = Kernel(tmp_path)
        a = kernel.create_entity(name="A")
        b = kernel.create_entity(name="B")
        c = kernel.create_entity(name="C")

        # Link A -> B and B -> C
        assert kernel.add_entity_child(a, b) is None
        assert kernel.add_entity_child(b, c) is None

        # Direct cycle: B -> A
        err1 = kernel.add_entity_child(b, a)
        assert isinstance(err1, Error)
        assert err1.code == InvalidResourceDataError
        assert "cyclic hierarchy" in err1.message.lower() or "cycle" in str(err1).lower()

        # Transitive cycle: C -> A
        err2 = kernel.add_entity_child(c, a)
        assert isinstance(err2, Error)
        assert err2.code == InvalidResourceDataError
        assert "cyclic hierarchy" in err2.message.lower() or "cycle" in str(err2).lower()

        # Self-cycle: A -> A
        err3 = kernel.add_entity_child(a, a)
        assert isinstance(err3, Error)
        assert err3.code == InvalidResourceDataError

    def test_mismatched_parent_remove_does_not_clear_child_parent(self, tmp_path):
        kernel = Kernel(tmp_path)
        p1 = kernel.create_entity(name="Parent1")
        p2 = kernel.create_entity(name="Parent2")
        child = kernel.create_entity(name="Child")

        # Attach child to P1
        kernel.add_entity_child(p1, child)
        assert kernel.get_entity_parent(child) == p1

        # Mismatched remove: caller tries to remove child from P2
        res = kernel.remove_entity_child(p2, child)
        assert res is None

        # Child's parent must still be P1
        assert kernel.get_entity_parent(child) == p1
        child_proxy = kernel.get_entity_proxy(child)
        assert child_proxy.parent.id == p1

    def test_reparenting_detaches_unloaded_old_parent(self, tmp_path):
        # Session 1: create P1 and C, link C to P1, save to disk
        k1 = Kernel(tmp_path)
        p1 = k1.create_entity(name="OldParent")
        c = k1.create_entity(name="Child")
        k1.add_entity_child(p1, c)
        p1_sid = k1.get_storage_id(p1)
        c_sid = k1.get_storage_id(c)
        k1.save_dirty_resources()

        # Session 2: fresh kernel, create P2, load ONLY C (P1 is not loaded into memory)
        k2 = Kernel(tmp_path)
        p2 = k2.create_entity(name="NewParent")
        # Load only C without loading children/dependencies
        c_rid = k2.load_resource(c_sid, load_dependencies=0, load_children=0)
        assert not isinstance(c_rid, Error)
        assert p1_sid not in k2.resource_runtime_ids, "P1 must not be loaded yet"

        # Attach C to P2 (reparenting should locate and detach C from unloaded P1)
        k2.add_entity_child(p2, c_rid)
        k2.save_dirty_resources()

        # Session 3: fresh kernel, load P1 from disk, verify C is NOT in P1's children
        k3 = Kernel(tmp_path)
        loaded_p1 = k3.load_entity(p1_sid)
        assert not isinstance(loaded_p1, Error)
        assert k3.get_entity_children(loaded_p1) == []
        assert c_sid.hex() not in k3.resources[loaded_p1]["data"].get("children", [])


class TestChildQueriesOnEntityProxy:
    """Tests for query_children, find_child, recursive traversal, and cycle protection."""

    def test_query_children_by_component(self, tmp_path):
        kernel = Kernel(tmp_path)
        parent = kernel.get_entity_proxy(kernel.create_entity(name="Character"))

        c1 = kernel.get_entity_proxy(kernel.create_entity(
            name="Sword",
            components={"Weapon": {"damage": 10}, "Transform": {"x": 1}},
        ))
        c2 = kernel.get_entity_proxy(kernel.create_entity(
            name="Shield",
            components={"Defense": {"armor": 5}, "Transform": {"x": -1}},
        ))
        c3 = kernel.get_entity_proxy(kernel.create_entity(
            name="Light",
            components={"LightSource": {"radius": 10}},
        ))

        parent.add_child(c1)
        parent.add_child(c2)
        parent.add_child(c3)

        # Query for Weapon and Transform
        weapons = parent.query_children("Weapon", "Transform")
        assert len(weapons) == 1
        assert weapons[0].id == c1.id

        # Query for Transform only
        transformed = parent.query_children("Transform")
        assert len(transformed) == 2
        transformed_ids = {t.id for t in transformed}
        assert transformed_ids == {c1.id, c2.id}

    def test_find_child_by_name_and_recursive_search(self, tmp_path):
        kernel = Kernel(tmp_path)
        root = kernel.get_entity_proxy(kernel.create_entity(name="Root"))
        arm = kernel.get_entity_proxy(kernel.create_entity(name="LeftArm"))
        hand = kernel.get_entity_proxy(kernel.create_entity(name="Hand"))
        finger = kernel.get_entity_proxy(kernel.create_entity(name="Finger"))

        root.add_child(arm)
        arm.add_child(hand)
        hand.add_child(finger)

        # Shallow find
        assert root.find_child("LeftArm") is not None
        assert root.find_child("LeftArm").id == arm.id
        assert root.find_child("Hand", recursive=False) is None
        assert root.find_child("Finger", recursive=False) is None

        # Recursive find
        found_finger = root.find_child("Finger", recursive=True)
        assert found_finger is not None
        assert found_finger.id == finger.id

        # Non-existent child
        assert root.find_child("NonExistent", recursive=True) is None

    def test_recursive_query_with_cycle_protection(self, tmp_path):
        kernel = Kernel(tmp_path)
        p1 = kernel.get_entity_proxy(kernel.create_entity(
            name="NodeA",
            components={"Tag": {"val": "A"}},
        ))
        p2 = kernel.get_entity_proxy(kernel.create_entity(
            name="NodeB",
            components={"Tag": {"val": "B"}},
        ))

        p1.add_child(p2)

        # Manually introduce circular reference in children list to test cycle safety
        p1_sid_hex = p1.storage_id.hex()
        p2_data = kernel.resources[p2.id]["data"]
        p2_data.setdefault("children", []).append(p1_sid_hex)

        # Must not raise RecursionError and must terminate safely
        results = p1.query_children("Tag", recursive=True)
        assert len(results) == 2
        assert {r.id for r in results} == {p1.id, p2.id}

        # find_child with recursive=True must also terminate safely without infinite recursion
        found = p1.find_child("NonExistent", recursive=True)
        assert found is None


class TestWorldQueries:
    """Tests for world-level component filtering via kernel.query and entity.world.query."""

    def test_world_query_filtering(self, tmp_path):
        kernel = Kernel(tmp_path)
        e1 = kernel.create_entity(name="E1", components={"Position": {"x": 0}, "Velocity": {"vx": 1}})
        e2 = kernel.create_entity(name="E2", components={"Position": {"x": 10}})
        e3 = kernel.create_entity(name="E3", components={"Position": {"x": 20}, "Velocity": {"vx": -1}, "AI": {}})
        e4 = kernel.create_entity(name="E4", components={"Other": {}})

        # Query via Kernel
        matching_ids = kernel.query("Position", "Velocity")
        assert set(matching_ids) == {e1, e3}

        # Query via WorldProxy on an entity
        proxy1 = kernel.get_entity_proxy(e1)
        assert isinstance(proxy1.world, WorldProxy)

        proxies = proxy1.world.query("Position", "Velocity")
        assert len(proxies) == 2
        assert {p.id for p in proxies} == {e1, e3}
        assert all(isinstance(p, EntityProxy) for p in proxies)

        # Non-matching query returns empty list
        assert kernel.query("NonExistent") == []
        assert proxy1.world.query("NonExistent") == []


class TestEntitySpawning:
    """Tests for spawning entities from dict templates and cloning existing entities."""

    def test_spawn_from_dict_template(self, tmp_path):
        kernel = Kernel(tmp_path)
        template = {
            "name": "Goblin",
            "components": {
                "Health": {"current": 30, "max": 30},
                "Combat": {"damage": 5},
            },
        }

        spawned_id = kernel.spawn(template)
        assert not isinstance(spawned_id, Error)

        proxy = kernel.get_entity_proxy(spawned_id)
        assert proxy.name == "Goblin"
        assert proxy.health.current == 30
        assert proxy.combat.damage == 5

    def test_spawn_clone_from_existing_entity_deep_copies(self, tmp_path):
        kernel = Kernel(tmp_path)
        orig_id = kernel.create_entity(
            name="Warrior",
            components={"Health": {"current": 100}, "Inventory": {"bag": ["sword", "shield"]}},
        )
        orig_proxy = kernel.get_entity_proxy(orig_id)

        # Clone from runtime ID
        clone_id = kernel.spawn(orig_id, name="WarriorClone")
        clone_proxy = kernel.get_entity_proxy(clone_id)

        # Clone has distinct identity
        assert clone_proxy.id != orig_proxy.id
        assert clone_proxy.storage_id != orig_proxy.storage_id
        assert clone_proxy.name == "WarriorClone"

        # Modifying clone must NOT mutate the original template
        clone_proxy.health.current = 20
        clone_proxy.inventory.bag.append("potion")

        assert orig_proxy.health.current == 100
        assert orig_proxy.inventory.bag == ["sword", "shield"]

    def test_spawn_with_as_child_attaches_to_spawner(self, tmp_path):
        kernel = Kernel(tmp_path)
        spawner = kernel.get_entity_proxy(kernel.create_entity(name="Spawner"))

        bullet_template = {
            "name": "Bullet",
            "components": {"Damage": {"amount": 25}},
        }

        bullet = spawner.spawn(bullet_template, as_child=True)
        assert isinstance(bullet, EntityProxy)
        assert bullet.parent.id == spawner.id
        assert len(spawner.children) == 1
        assert spawner.children[0].id == bullet.id
        assert bullet.damage.amount == 25


class TestScriptIntegrationWithHierarchyAndQueries:
    """Tests executing scripts that interact with hierarchy and world queries during tick()."""

    def test_script_queries_and_updates_children_during_tick(self, tmp_path):
        kernel = Kernel(tmp_path)
        parent = kernel.get_entity_proxy(kernel.create_entity(name="SquadLeader"))

        soldier1 = kernel.get_entity_proxy(kernel.create_entity(
            name="Soldier1",
            components={"Health": {"current": 50}},
        ))
        soldier2 = kernel.get_entity_proxy(kernel.create_entity(
            name="Soldier2",
            components={"Health": {"current": 70}},
        ))
        drone = kernel.get_entity_proxy(kernel.create_entity(
            name="Drone",
            components={"Battery": {"level": 100}},
        ))

        parent.add_child(soldier1)
        parent.add_child(soldier2)
        parent.add_child(drone)

        script_code = """
def update(dt):
    for member in self.query_children("Health"):
        member.health.current += 10 * dt
"""
        s_id = kernel.create_script_resource(name="HealSquad", code=script_code)
        kernel.attach_script(parent.id, s_id)

        kernel.tick(dt=2.0)

        # Both soldiers healed (+20), drone unaffected
        assert soldier1.health.current == 70
        assert soldier2.health.current == 90
        assert drone.battery.level == 100

    def test_script_spawns_child_entity_during_tick(self, tmp_path):
        kernel = Kernel(tmp_path)
        turret = kernel.get_entity_proxy(kernel.create_entity(
            name="Turret",
            components={"TurretState": {"ammo": 5}},
        ))

        script_code = """
def update(dt):
    if len(self.children) == 0 and self.turretstate.ammo > 0:
        self.spawn(
            {"name": "Projectile", "components": {"Damage": {"amount": 100}}},
            as_child=True,
        )
        self.turretstate.ammo -= 1
"""
        s_id = kernel.create_script_resource(name="TurretAI", code=script_code)
        kernel.attach_script(turret.id, s_id)

        # First tick spawns bullet
        kernel.tick(dt=1.0)

        assert len(turret.children) == 1
        assert turret.turretstate.ammo == 4
        bullet = turret.children[0]
        assert bullet.name == "Projectile"
        assert bullet.damage.amount == 100

        # Second tick does not spawn extra bullet because len(self.children) == 1
        kernel.tick(dt=1.0)
        assert len(turret.children) == 1
        assert turret.turretstate.ammo == 4