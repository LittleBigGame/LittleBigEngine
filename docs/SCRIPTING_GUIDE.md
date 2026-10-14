# LittleBigEngine Scripting Guide

Welcome to gameplay scripting in **LittleBigEngine (LBE)**. This guide covers how to write, configure, and execute Python scripts attached to entities within the engine.

---

## 1. Core Architecture Overview

In LittleBigEngine:
- **Entities** are lightweight runtime identifiers ([`RuntimeID`](file:///f:/ModEngine/LBE/types.py#L6)) backed by persistent JSON envelopes ([`StorageID`](file:///f:/ModEngine/LBE/types.py#L5)).
- **Components** are pure dictionary data structures attached to entities.
- **Scripts** are first-class engine resources ([`Script = 1`](file:///f:/ModEngine/LBE/types.py#L34)) containing Python code.
- **Proxies** ([`EntityProxy`](file:///f:/ModEngine/LBE/proxy.py#L167-L279) and [`ComponentProxy`](file:///f:/ModEngine/LBE/proxy.py#L12-L165)) wrap entity state to provide transparent mutation tracking, automatic dirty flagging, and ergonomic dot-access.

---

## 2. Writing Entity Scripts

Every script attached to an entity is executed within an execution environment pre-populated with:
- `self`: An [`EntityProxy`](file:///f:/ModEngine/LBE/proxy.py#L167-L279) representing the entity the script is attached to.
- `dt`: The frame delta time (in seconds) passed to the game loop.
- `kernel`: The active [`Kernel`](file:///f:/ModEngine/LBE/kernel.py#L14-L37) instance.
- Any resolved cross-resource references declared via `<|ResourceType|StorageID.hex|>`.

### The `update` Hook

Scripts define an `update` function called on every engine tick. Several signature conventions are supported:

```python
# Style A: Parameterless or dt only (recommended for concise scripts)
def update(dt):
    self.transform.x += 10.0 * dt

# Style B: Explicit self and dt parameters
def update(self, dt):
    self.transform.x += 10.0 * dt

# Style C: Parameterless using self from script globals
def update():
    self.stats.ticks_lived += 1
```

---

## 3. Component Access & Tracked Mutations

LittleBigEngine transparently tracks state changes. You do not need to call `kernel.set_component(...)` manually after changing properties.

### Dot-Access and Dict-Access

Components can be accessed using either attribute notation or dictionary indexing:

```python
def update(dt):
    # Dot-access (case-insensitive component lookup)
    self.transform.x += self.velocity.vx * dt
    self.transform.y += self.velocity.vy * dt

    # Equivalent dictionary access
    self["Transform"]["x"] += self["Velocity"]["vx"] * dt
```

### Deeply Nested Structures

Nested dictionaries within components are recursively wrapped in [`ComponentProxy`](file:///f:/ModEngine/LBE/proxy.py#L12-L165) instances. In-place mutations on nested structures automatically dirty the root entity:

```python
def update(dt):
    # Deeply nested field modification
    self.stats.health.current -= 5.0 * dt
    self.config.audio.settings.volume = 0.8
```

When [`Kernel.save_dirty_resources()`](file:///f:/ModEngine/LBE/kernel.py#L275-L278) is invoked, all modified components are persisted to disk automatically. Non-mutating reads do not dirty entities.

### Dynamic Component Operations

The [`EntityProxy`](file:///f:/ModEngine/LBE/proxy.py#L167-L279) provides helper methods to inspect and modify components dynamically:

```python
def update(dt):
    # Check if a component exists
    if self.has("Shield") or "Shield" in self:
        self.shield.power -= 2.0 * dt
        if self.shield.power <= 0:
            # Remove component dynamically
            self.remove("Shield")  # or: del self.shield

    # Add a new component dynamically
    if self.stats.level > 10 and not self.has("Flight"):
        self.set("Flight", {"speed": 25.0, "altitude": 100.0})
```

---

## 4. Static Cross-Resource References

To reference other entities or resources (such as prefabs, enemy targets, audio clips, or configuration tables) from script source code, use the static reference syntax:

$$\text{\texttt{<|ResourceType|StorageID.hex|>}}$$

- `ResourceType`: Integer enum (`0` for [`Entity`](file:///f:/ModEngine/LBE/types.py#L33), `1` for [`Script`](file:///f:/ModEngine/LBE/types.py#L34)).
- `StorageID.hex`: 32-character hexadecimal string representing the 16-byte persistent StorageID.

### Reference Syntax Example

```python
# The ReferencePreprocessor transforms this reference into a module variable
# and binds the live target EntityProxy before execution.
target = <|0|0123456789abcdef0123456789abcdef|>

def update(dt):
    # Interact with the target entity
    damage = self.stats.attack_power * dt
    target.health.current -= damage
```

### Preprocessor Guarantees

1. **1:1 Line Number Preservation:** Replacements never alter line counts or newline positioning, ensuring Python runtime tracebacks and syntax errors report exact line numbers matching your source code.
2. **Comment and String Literal Escaping:** Brackets located within comments (`# <|0|...|>`) or string literals (`"<|0|...|>"` or `"""<|0|...|>"""`) are ignored.
3. **Syntax Validation:** Malformed brackets raise an explicit [`LBEReferenceSyntaxError`](file:///f:/ModEngine/LBE/preprocessor.py#L13-L25) during compilation.

---

## 5. Script Resources & Lifecycle

### Creating a Script Resource

Scripts can be defined inline or linked to external Python source files using [`Kernel.create_script_resource`](file:///f:/ModEngine/LBE/kernel.py#L1001-L1023):

```python
from LBE import Kernel

kernel = Kernel(folder_location=project_path)

# Create an inline script resource
script_id = kernel.create_script_resource(
    name="HealthRegenScript",
    code="""
def update(dt):
    if self.health.current < self.health.max:
        self.health.current = min(self.health.max, self.health.current + 5 * dt)
""",
    requires=["Health"],  # Declared component requirements
)
```

### Declaring Component Requirements

The `requires` parameter declares components that an entity must possess for the script to run safely. 

If an entity lacks any required component when [`Kernel.tick()`](file:///f:/ModEngine/LBE/kernel.py#L1296-L1307) runs, script execution halts with a [`MissingComponentRequirementError`](file:///f:/ModEngine/LBE/types.py#L28) instead of failing with an uncaught `AttributeError`.

### Attaching and Detaching Scripts

Attach or detach scripts to entities using their RuntimeID or StorageID:

```python
# Create an entity
player_id = kernel.create_entity(
    name="Player",
    components={"Health": {"current": 50, "max": 100}},
)

# Attach the script
kernel.attach_script(player_id, script_id)

# Inspect attached scripts
attached = kernel.get_entity_scripts(player_id)
assert script_id in attached

# Detach when no longer needed
kernel.detach_script(player_id, script_id)
```

Attached script associations are stored in the entity's JSON resource definition as canonical hexadecimal Storage IDs and persist across sessions.

---

## 6. Game Loop Execution (`kernel.tick`)

The primary simulation loop advances by calling [`Kernel.tick(dt)`](file:///f:/ModEngine/LBE/kernel.py#L1296-L1307):

```python
import time

last_time = time.perf_counter()

while game_running:
    now = time.perf_counter()
    dt = now - last_time
    last_time = now

    # Run one frame update across all entities with attached scripts
    errors = kernel.tick(dt=dt)

    if errors:
        for err in errors:
            print(f"[Error in script {err.data.get('script_id')}]: {err.message} - {err.description}")

    # Persist modifications if desired (e.g. at checkpoints or frame ends)
    kernel.save_dirty_resources()
```

### Error Isolation & Resilience
If a script attached to Entity A raises an exception (e.g., division by zero), [`Kernel.tick`](file:///f:/ModEngine/LBE/kernel.py#L1296-L1307) catches the error, packages it into an [`Error`](file:///f:/ModEngine/LBE/types.py#L10-L15) object, and continues running scripts for Entity B and Entity C.

### Compilation Caching
The kernel caches compiled script bytecode and AST structures in [`Kernel._script_cache`](file:///f:/ModEngine/LBE/kernel.py#L1215-L1222). Multiple entities sharing the same script resource reuse the cached bytecode, ensuring high execution performance.

---

## 7. Entity Queries & Hierarchy / Child Management

### Querying Entities

You can inspect and filter all active entities loaded into the [`Kernel`](file:///f:/ModEngine/LBE/kernel.py#L14-L37):

```python
# Find all entities with a Transform and Health component
for entity_id in list(kernel.resources.keys()):
    if kernel.is_entity(entity_id):
        if kernel.has_component(entity_id, "Transform") and kernel.has_component(entity_id, "Health"):
            proxy = kernel.get_entity_proxy(entity_id)
            print(f"Entity {proxy.id}: HP={proxy.health.current}, Position=({proxy.transform.x}, {proxy.transform.y})")
```

### Hierarchy & Child Resources

Resources support hierarchical parent-child relationships and dependency declarations:
- When creating resources with [`Kernel.create_resource`](file:///f:/ModEngine/LBE/kernel.py#L442-L548), you can specify `children=[child_storage_id_1, ...]` and `dependencies=[dep_storage_id_1, ...]`.
- When loading an entity using [`Kernel.load_entity(storage_id, load_depth=-1)`](file:///f:/ModEngine/LBE/kernel.py#L588-L615), child resources are loaded recursively according to the requested depth (`load_depth=-1` loads the entire descendant graph).
- Referenced resources on entities can also be inspected and added using [`Kernel.get_entity_resources`](file:///f:/ModEngine/LBE/kernel.py#L834-L856) and [`Kernel.add_entity_resource`](file:///f:/ModEngine/LBE/kernel.py#L857-L894).

---

## 8. Complete Example: Turret AI & Target Tracking

Here is a complete, self-contained example demonstrating all scripting features working together:

```python
from pathlib import Path
from LBE import Kernel

# Initialize kernel
kernel = Kernel(Path("./game_world"))

# 1. Create Player entity
player_id = kernel.create_entity(
    name="Player",
    components={
        "Transform": {"x": 100.0, "y": 50.0},
        "Health": {"current": 100.0, "max": 100.0},
    },
)
player_sid_hex = kernel.get_storage_id(player_id).hex()

# 2. Create Turret AI Script with static reference to Player
turret_script_code = f"""
player = <|0|{player_sid_hex}|>

def update(dt):
    # Turret rotates towards player and fires
    dx = player.transform.x - self.transform.x
    dy = player.transform.y - self.transform.y
    distance = (dx**2 + dy**2) ** 0.5

    if distance < self.turret.range:
        # Damage the player
        damage = self.turret.dps * dt
        player.health.current -= damage
        self.turret.shots_fired += 1
"""

turret_script_id = kernel.create_script_resource(
    name="TurretAI",
    code=turret_script_code,
    requires=["Transform", "Turret"],
)

# 3. Create Turret entity and attach script
turret_id = kernel.create_entity(
    name="DefenseTurret",
    components={
        "Transform": {"x": 80.0, "y": 50.0},
        "Turret": {"range": 50.0, "dps": 10.0, "shots_fired": 0},
    },
)
kernel.attach_script(turret_id, turret_script_id)

# 4. Advance simulation
kernel.tick(dt=1.0)

# 5. Check updated tracked states
player_proxy = kernel.get_entity_proxy(player_id)
turret_proxy = kernel.get_entity_proxy(turret_id)

print(f"Player Health: {player_proxy.health.current}")  # 90.0
print(f"Turret Shots Fired: {turret_proxy.turret.shots_fired}")  # 1

# 6. Save dirty state to disk
kernel.save_dirty_resources()
```
