## Mandatory ValueExpression and reference-kind compatibility

`referenceKind` belongs to each action parameter definition in the embedded action
catalog. It is not a property to copy into a `ValueExpression`. Choose the expression's
`source` according to the parameter's `referenceKind` using this mandatory matrix:

| Expression `source` | Required expression fields | Compatible parameter `referenceKind` |
|---|---|---|
| `activity_location` | `index` | `location` or `none` |
| `activity_resource` | `index` | `resource` or `none` |
| `actor` | no other fields | `resident` or `none` |
| `activity_intent` | no other fields | normally `none` |
| `literal` | `value` | every kind, subject to the rules below |
| `variable` | `variableId` | only when the variable and parameter value types are compatible |

Apply these additional rules:

1. For a literal parameter with `referenceKind = location`, `resource`, `resident` or
   `external_person`, the value must be the identifier of an entity declared in the
   generated scenario.
2. For `referenceKind = capability` or `environment_entity`, use a meaningful symbolic
   literal role that Milestone 4 can bind, such as `coffee_preparation_item`,
   `cooking_appliance`, `medication_storage`, `laundry_appliance` or `cleaning_tool`.
   Do not use `activity_resource` for these parameters.
3. Use `activity_resource` only when the action parameter itself declares
   `referenceKind = resource` or `none`. A scenario resource is not automatically a
   capability or environment-entity role.
4. Use `activity_location` only when the action parameter declares
   `referenceKind = location` or `none`, and always supply a valid zero-based `index` into
   the activity's `locationIds`.
5. Use `actor` only for `resident` or `none` parameters.
6. Literal values must still match `valueType` and any `allowedValues` in the catalog.
7. Use stable semantic roles consistently across take/use/put or
   open/activate/deactivate/close actions that concern the same object. Do not generate
   meaningless placeholders such as `item_1`, `generic_target` or `unknown_role`.

Examples:

Valid movement to the activity's first declared location:

```json
{
  "actionType": "move_to",
  "arguments": {
    "destination": {"source": "activity_location", "index": 0}
  }
}
```

Valid symbolic item role for `take_item`, whose `itemRole` parameter has
`referenceKind = capability`:

```json
{
  "actionType": "take_item",
  "arguments": {
    "itemRole": {"source": "literal", "value": "coffee_preparation_item"}
  }
}
```

Valid symbolic appliance role for `activate`, whose `target` parameter has
`referenceKind = environment_entity`:

```json
{
  "actionType": "activate",
  "arguments": {
    "target": {"source": "literal", "value": "cooking_appliance"}
  }
}
```

Invalid — `activity_resource` resolves a concrete scenario resource and is incompatible
with the capability parameter `take_item.itemRole`:

```json
{
  "actionType": "take_item",
  "arguments": {
    "itemRole": {"source": "activity_resource", "index": 0}
  }
}
```

Before returning the bundle, inspect every action argument against the corresponding
parameter definition. There must be zero `ACTION_ARGUMENT_TYPE_MISMATCH` possibilities.
