"""Runtime log presentation composed with the public entity UI API."""

from lbe.ui import put, FIELD, ACCENT, MUTED


def start():
    ui = entity.root.components['ui']
    log.exclude(entity)
    entity.components['log'] = log
    entity.components['offset'] = 0
    entity.components['selected_record'] = None
    entity.components['on_scroll'] = scroll
    entity.components['on_click'] = press
    entity.components['on_drag'] = move
    entity.components['on_release'] = release
    for name, text, callback in (
        ('PauseLog', 'Pause', toggle_pause), ('ClearLog', 'Clear', clear),
        ('CallsLog', 'Calls', toggle_calls), ('EditorLog', 'Editor', toggle_editor),
        ('CloseLog', 'X', lambda: setattr(entity, 'visible', False)),
    ):
        ui.button(entity, name, text, callback, h=26, layer=entity.layer+1)
    ui.field(entity, 'FilterLog', '', hint='Filter kind, target, source or value', h=26, layer=entity.layer+1)
    ui.create(entity, 'LogSummary', 'label', text='', h=20, ink=MUTED, layer=entity.layer+1)
    for i in range(8):
        ui.button(entity, f'LogRow{i}', '', lambda: None, h=22, layer=entity.layer+1, row_index=i)
    for name in ('LogTarget', 'LogSource', 'LogDetail'):
        ui.create(entity, name, 'label', text='', h=20, ink=MUTED, layer=entity.layer+1)
    ui.splitter(entity, 'LogResize', axis='x', on_drag=resize, layer=entity.layer+2)


def press(control, event):
    if event[3] == 1 and event[2] < entity.y+28:
        entity.drag_offset = (event[1]-entity.x, event[2]-entity.y)
        entity.root.relations['active_drag'] = entity
        return True
    return False


def move(control, event):
    offset = entity.components.get('drag_offset')
    if offset:
        put(entity, x=max(0, min(window.width-80, event[1]-offset[0])),
            y=max(0, min(window.height-28, event[2]-offset[1])))
    return True


def release(control, event):
    entity.components.pop('drag_offset', None)


def resize(control, event):
    put(entity, w=max(480, min(window.width-entity.x, event[1]-entity.x+8)),
        h=max(360, min(window.height-entity.y, event[2]-entity.y+8)))
    return True


def toggle_pause():
    log.paused = not log.paused


def clear():
    log.clear()
    entity.selected_record = None
    entity.offset = 0


def toggle_calls():
    log.frame_calls = not log.frame_calls


def toggle_editor():
    log.include_editor = not log.include_editor


def scroll(control, event):
    entity.offset = max(0, entity.offset + int(event[4])*3)
    return True


def update(dt):
    if not entity.visible:
        return
    put(entity, w=min(entity.w, window.width), h=min(entity.h, window.height))
    put(entity, x=max(0, min(entity.x, window.width-entity.w)),
        y=max(0, min(entity.y, window.height-entity.h)))
    controls = {child.name: child for child in entity.children}
    put(controls['LogResize'], x=entity.x+entity.w-12, y=entity.y+entity.h-12, w=12, h=12)
    x, y, width = entity.x+8, entity.y+30, max(0, entity.w-16)
    for name, w in (('PauseLog', 64), ('ClearLog', 58), ('CallsLog', 64), ('EditorLog', 64), ('CloseLog', 28)):
        control = controls[name]
        put(control, x=x, y=y, w=w, text=('Resume' if log.paused else 'Pause') if name=='PauseLog' else control.text,
            color=ACCENT if (name=='CallsLog' and log.frame_calls) or (name=='EditorLog' and log.include_editor) else FIELD)
        x += w+4
    put(controls['FilterLog'], x=x, y=y, w=max(0, entity.x+entity.w-8-x))
    records = log.view(include_editor=log.include_editor, text=controls['FilterLog'].buffer.text)
    row_count = max(0, min(8, int((entity.h-160)//22)))
    entity.offset = min(entity.offset, max(0, len(records)-row_count))
    end = len(records)-entity.offset
    displayed = records[max(0, end-row_count):end] if row_count else ()
    summary = controls['LogSummary']
    put(summary, x=entity.x+8, y=y+30, w=width,
        text=f'{len(records)} matching / {len(log.records)} retained | wheel: history | click: details | capture: {"paused" if log.paused else "live"}')
    for i in range(8):
        row = controls[f'LogRow{i}']
        record = displayed[i] if i < len(displayed) else None
        put(row, x=entity.x+8, y=y+54+i*22, w=width, visible=record is not None,
            text=f'#{record.sequence} {record.time:.2f}s {record.kind} | {record.target}' if record else '',
            action=lambda r=record: setattr(entity, 'selected_record', r))
    record = entity.selected_record or (displayed[-1] if displayed else None)
    for i, (name, text) in enumerate((('LogTarget', 'Target: '+record.target if record else ''),
                                      ('LogSource', 'Source: '+record.source if record else ''),
                                      ('LogDetail', record.detail if record else ''))):
        put(controls[name], x=entity.x+8, y=y+60+row_count*22+i*22, w=width, text=text,
            visible=entity.h >= 160)
