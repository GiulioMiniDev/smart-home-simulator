from __future__ import annotations

from enum import StrEnum
from string import Formatter
from typing import Literal

from pydantic import ConfigDict, Field, JsonValue, model_validator

from smart_home_sim.domain.base import ContractModel
from smart_home_sim.domain.models import (
    AuthorType,
    ConditionOperator,
    DurationRange,
    EffectOperation,
    Provenance,
    StateEffect,
)


class ValueType(StrEnum):
    string = "string"
    number = "number"
    integer = "integer"
    boolean = "boolean"
    object = "object"
    array = "array"


class VariableScope(StrEnum):
    resident = "resident"
    day = "day"
    initial_state = "initial_state"
    derived_calendar = "derived_calendar"


class ReferenceKind(StrEnum):
    none = "none"
    location = "location"
    resource = "resource"
    resident = "resident"
    external_person = "external_person"
    environment_entity = "environment_entity"
    capability = "capability"


class ActivityDefinition(ContractModel):
    intent: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    category: str = Field(min_length=1)
    components: list[str] = Field(min_length=1)
    relevant_variable_ids: list[str] = Field(min_length=1)
    external_mappings: dict[str, str] = Field(default_factory=dict)


class ActivityComponentDefinition(ContractModel):
    component_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required_action_types: list[str] = Field(min_length=1)


class ActivityCatalog(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:activity-catalog:1.0.0",
            "title": "Smart Home Activity Catalog 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["activity_catalog"] = "activity_catalog"
    catalog_id: str = Field(min_length=1)
    catalog_version: str = Field(min_length=1)
    components: list[ActivityComponentDefinition] = Field(min_length=1)
    activities: list[ActivityDefinition] = Field(min_length=1)


class VariableDefinition(ContractModel):
    variable_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    value_type: ValueType
    scope: VariableScope
    source_path: str | None = None
    required: bool = False
    allowed_values: list[JsonValue] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_source(self) -> VariableDefinition:
        if self.scope is VariableScope.derived_calendar:
            if self.source_path not in {"weekday", "season"}:
                raise ValueError("derived calendar variables require sourcePath weekday or season")
        elif not self.source_path:
            raise ValueError("non-derived variables require sourcePath")
        return self


class VariableCatalog(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:variable-catalog:1.0.0",
            "title": "Smart Home Variable Catalog 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["variable_catalog"] = "variable_catalog"
    catalog_id: str = Field(min_length=1)
    catalog_version: str = Field(min_length=1)
    variables: list[VariableDefinition] = Field(min_length=1)


class ActionParameterDefinition(ContractModel):
    parameter_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    value_type: ValueType
    required: bool = True
    reference_kind: ReferenceKind = ReferenceKind.none
    allowed_values: list[JsonValue] = Field(default_factory=list)


class CapabilityRequirement(ContractModel):
    role: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    parameter_name: str | None = None


class ActionPreconditionTemplate(ContractModel):
    fact_template: str = Field(min_length=1)
    operator: Literal["exists", "not_exists", "eq", "ne"]
    value: JsonValue | None = None

    @model_validator(mode="after")
    def check_value_policy(self) -> ActionPreconditionTemplate:
        if self.operator in {"exists", "not_exists"} and self.value is not None:
            raise ValueError(f"operator '{self.operator}' does not accept a value")
        if self.operator in {"eq", "ne"} and self.value is None:
            raise ValueError(f"operator '{self.operator}' requires a value")
        return self


class ActionEffectTemplate(ContractModel):
    fact_template: str = Field(min_length=1)
    operation: EffectOperation
    value: JsonValue


class ActionDefinition(ContractModel):
    action_type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    parameters: list[ActionParameterDefinition] = Field(default_factory=list)
    required_capabilities: list[CapabilityRequirement] = Field(default_factory=list)
    preconditions: list[ActionPreconditionTemplate] = Field(default_factory=list)
    effects: list[ActionEffectTemplate] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_parameter_references(self) -> ActionDefinition:
        parameters = {item.parameter_name for item in self.parameters}
        unknown = {
            item.parameter_name
            for item in self.required_capabilities
            if item.parameter_name is not None and item.parameter_name not in parameters
        }
        if unknown:
            raise ValueError(f"capability requirements reference unknown parameters: {unknown}")
        template_fields: set[str] = set()
        templates = [item.fact_template for item in self.preconditions]
        templates.extend(item.fact_template for item in self.effects)
        templates.extend(item.value for item in self.effects if isinstance(item.value, str))
        for template in templates:
            template_fields.update(
                field_name
                for _, field_name, _, _ in Formatter().parse(template)
                if field_name is not None
            )
        if template_fields - parameters:
            raise ValueError(
                f"state templates reference unknown parameters: {template_fields - parameters}"
            )
        return self


class ActionCatalog(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:action-catalog:1.0.0",
            "title": "Smart Home Atomic Action Catalog 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["action_catalog"] = "action_catalog"
    catalog_id: str = Field(min_length=1)
    catalog_version: str = Field(min_length=1)
    actions: list[ActionDefinition] = Field(min_length=1)


class CatalogReference(ContractModel):
    catalog_id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class BehaviorCatalogReferences(ContractModel):
    activity_catalog: CatalogReference
    variable_catalog: CatalogReference
    action_catalog: CatalogReference


class ValueSource(StrEnum):
    literal = "literal"
    variable = "variable"
    activity_location = "activity_location"
    activity_resource = "activity_resource"
    activity_intent = "activity_intent"
    actor = "actor"


class ValueExpression(ContractModel):
    source: ValueSource
    value: JsonValue | None = None
    variable_id: str | None = None
    index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_source_fields(self) -> ValueExpression:
        if self.source is ValueSource.literal:
            if self.value is None:
                raise ValueError("literal expressions require value")
            if self.variable_id is not None or self.index is not None:
                raise ValueError("literal expressions accept only value")
        elif self.source is ValueSource.variable:
            if self.variable_id is None:
                raise ValueError("variable expressions require variableId")
            if self.value is not None or self.index is not None:
                raise ValueError("variable expressions accept only variableId")
        elif self.source in {ValueSource.activity_location, ValueSource.activity_resource}:
            if self.index is None:
                raise ValueError(f"{self.source} expressions require index")
            if self.value is not None or self.variable_id is not None:
                raise ValueError(f"{self.source} expressions accept only index")
        elif any(item is not None for item in (self.value, self.variable_id, self.index)):
            raise ValueError(f"{self.source} expressions do not accept additional fields")
        return self


class VariableCondition(ContractModel):
    variable_id: str = Field(min_length=1)
    operator: ConditionOperator = ConditionOperator.truthy
    value: JsonValue | None = None

    @model_validator(mode="after")
    def check_value_policy(self) -> VariableCondition:
        unary = {
            ConditionOperator.truthy,
            ConditionOperator.falsy,
            ConditionOperator.exists,
            ConditionOperator.not_exists,
        }
        if self.operator in unary and self.value is not None:
            raise ValueError(f"operator '{self.operator}' does not accept a value")
        if self.operator not in unary and self.value is None:
            raise ValueError(f"operator '{self.operator}' requires a value")
        numeric = {
            ConditionOperator.gt,
            ConditionOperator.gte,
            ConditionOperator.lt,
            ConditionOperator.lte,
        }
        if self.operator in numeric and (
            isinstance(self.value, bool) or not isinstance(self.value, (int, float))
        ):
            raise ValueError(f"operator '{self.operator}' requires a numeric value")
        membership = {ConditionOperator.in_, ConditionOperator.not_in}
        if self.operator in membership and not isinstance(self.value, list):
            raise ValueError(f"operator '{self.operator}' requires an array value")
        return self


class ProcessNodeKind(StrEnum):
    start = "start"
    end = "end"
    action = "action"
    choice = "choice"
    parallel_split = "parallel_split"
    parallel_join = "parallel_join"
    loop = "loop"


class ProcessNode(ContractModel):
    node_id: str = Field(min_length=1)
    kind: ProcessNodeKind
    action_type: str | None = None
    arguments: dict[str, ValueExpression] = Field(default_factory=dict)
    duration: DurationRange | None = None
    duration_weight: float | None = Field(default=None, gt=0)
    preconditions: list[VariableCondition] = Field(default_factory=list)
    effects: list[StateEffect] = Field(default_factory=list)
    max_iterations: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def check_kind_fields(self) -> ProcessNode:
        action_fields_present = bool(
            self.action_type
            or self.arguments
            or self.duration
            or self.duration_weight
            or self.preconditions
            or self.effects
        )
        if self.kind is ProcessNodeKind.action:
            if self.action_type is None:
                raise ValueError("action nodes require actionType")
            if self.duration_weight is None:
                raise ValueError("action nodes require durationWeight")
            if self.max_iterations is not None:
                raise ValueError("action nodes cannot define maxIterations")
        elif action_fields_present:
            raise ValueError("only action nodes may define action fields")
        if self.kind is ProcessNodeKind.loop:
            if self.max_iterations is None:
                raise ValueError("loop nodes require maxIterations")
        elif self.max_iterations is not None:
            raise ValueError("only loop nodes may define maxIterations")
        return self


class ProcessEdge(ContractModel):
    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    condition: VariableCondition | None = None
    is_default: bool = False

    @model_validator(mode="after")
    def check_default_condition(self) -> ProcessEdge:
        if self.is_default and self.condition is not None:
            raise ValueError("default edges cannot define a condition")
        return self


class ProcessModel(ContractModel):
    process_model_id: str = Field(min_length=1)
    process_model_version: str = Field(min_length=1)
    resident_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    implemented_components: list[str] = Field(min_length=1)
    nodes: list[ProcessNode] = Field(min_length=2)
    edges: list[ProcessEdge] = Field(min_length=1)


class ProcessBinding(ContractModel):
    binding_id: str = Field(min_length=1)
    resident_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    process_model_id: str = Field(min_length=1)
    applicability: list[VariableCondition] = Field(default_factory=list)
    fallback: bool = False


class PersonalProcessPackage(ContractModel):
    model_config = ConfigDict(
        **ContractModel.model_config,
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:smart-home-simulator:schema:personal-process-package:1.0.0",
            "title": "Smart Home Personal Process Package 1.0.0",
        },
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_type: Literal["personal_process_package"] = "personal_process_package"
    package_id: str = Field(min_length=1)
    package_version: str = Field(min_length=1)
    source_scenario_id: str = Field(min_length=1)
    source_scenario_version: str = Field(min_length=1)
    language: str = Field(min_length=2)
    provenance: Provenance
    catalogs: BehaviorCatalogReferences
    process_models: list[ProcessModel] = Field(min_length=1)
    bindings: list[ProcessBinding] = Field(min_length=1)

    @model_validator(mode="after")
    def check_authoring_provenance(self) -> PersonalProcessPackage:
        if self.provenance.generated_at is None:
            raise ValueError("behavioral provenance requires generatedAt")
        if self.provenance.author_type in {
            AuthorType.external_llm,
            AuthorType.rule_generator,
        } and (not self.provenance.generator_name or not self.provenance.generator_version):
            raise ValueError("generated behavior requires generatorName and generatorVersion")
        if self.provenance.author_type is AuthorType.external_llm and (
            not self.provenance.model_name or not self.provenance.prompt_template_version
        ):
            raise ValueError("LLM-authored behavior requires modelName and promptTemplateVersion")
        return self
