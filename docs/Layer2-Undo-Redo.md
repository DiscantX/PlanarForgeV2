# Layer 2: Undo, Redo and Commands

Every change a user makes in the editor is represented as a *command* object that knows how to apply itself and how to reverse itself. This is the classic Command pattern, and it gives undo and redo without the editing widgets needing to know anything about history. This page describes the commands, how a single user action can span several resources, and the moment at which a viewed resource becomes part of the project.

## Command pattern

Every user action is a command object with `apply()` and `undo()` methods. A stack of
commands on the session object provides undo history. History is not persisted between
sessions.

```python
class FieldEditCommand:
    def __init__(self, resource, field_name, old_value, new_value):
        self.resource = resource
        self.field_name = field_name
        self.old_value = old_value
        self.new_value = new_value

    def apply(self):
        self.resource.set(self.field_name, self.new_value)

    def undo(self):
        self.resource.set(self.field_name, self.old_value)
```

## Compound commands

Operations that span multiple resources (e.g. resref rename propagation) are wrapped
in a compound command that applies and undoes as a single unit:

```python
class CompoundCommand:
    def __init__(self, commands):
        self.commands = commands

    def apply(self):
        for cmd in self.commands:
            cmd.apply()

    def undo(self):
        for cmd in reversed(self.commands):
            cmd.undo()
```

## Session as mediator

The UI layer never writes directly to resource objects. Instead it creates a command
and pushes it to the session's undo stack, which applies it:

```python
widget.on_change(lambda v, f=field:
    session.execute(FieldEditCommand(resource, f.name, resource.get(f.name), v))
)
```

This means the **session object must exist before the UI layer is built**.

## Dirty state on first edit

When a command is applied to an ephemeral node for the first time, the session:
1. Marks the resource as dirty
2. Determines the output file path
3. Writes the project file to disk
4. Promotes the node from ephemeral to persisted in the graph

## See also

* [Layer 2 Overview](Layer2-Overview.md)
* [Project Model and Session](Layer2-Project-Model.md): the session object that owns the undo stack
* [Widget Descriptors](Layer2-Widget-Descriptors.md): the inspector code that issues these commands
