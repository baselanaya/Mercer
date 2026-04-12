from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from core.models import (
    AnnotatedSchema,
    AuditEntry,
    ColumnSchema,
    CorrectionStep,
    EntityContext,
    EntityMatch,
    ExecutionResult,
    FilteredSchema,
    JoinPath,
    PipelineState,
    QueryPlan,
    RawSchema,
    SQLCandidate,
    TableSchema,
)

# ---------------------------------------------------------------------------
# Fixtures — reusable minimal valid instances
# ---------------------------------------------------------------------------

@pytest.fixture
def column() -> ColumnSchema:
    return ColumnSchema(name="customer_id", type="INTEGER", description="Primary key", is_primary_key=True)


@pytest.fixture
def table(column: ColumnSchema) -> TableSchema:
    return TableSchema(name="customer", description="Customer master", columns=[column])


@pytest.fixture
def join_path() -> JoinPath:
    return JoinPath(from_table="rental", from_column="customer_id", to_table="customer", to_column="customer_id")


@pytest.fixture
def raw_schema(table: TableSchema) -> RawSchema:
    return RawSchema(db_url_hash="abc123", tables=[table])


@pytest.fixture
def annotated_schema(table: TableSchema) -> AnnotatedSchema:
    return AnnotatedSchema(
        db_url_hash="abc123",
        tables=[table],
        glossary={"revenue": "SUM(payment.amount)"},
    )


@pytest.fixture
def entity_match() -> EntityMatch:
    return EntityMatch(token="RETAIL", table="customer", column="cust_seg_cd", matched_value="RETAIL", score=0.95)


@pytest.fixture
def entity_context(entity_match: EntityMatch) -> EntityContext:
    return EntityContext(
        original_question="Show top customers",
        expanded_question="Show customers ordered by SUM(payment.amount) DESC",
        glossary_expansions={"top customers": "customers ordered by SUM(payment.amount) DESC"},
        entity_matches=[entity_match],
    )


@pytest.fixture
def filtered_schema(table: TableSchema, join_path: JoinPath) -> FilteredSchema:
    return FilteredSchema(tables=[table], join_paths=[join_path])


@pytest.fixture
def query_plan() -> QueryPlan:
    return QueryPlan(
        aggregations=["SUM(payment.amount)"],
        filters=["payment_date >= DATE_TRUNC('quarter', NOW())"],
        joins=["customer JOIN payment ON customer.customer_id = payment.customer_id"],
        ordering="total_spend DESC",
        subqueries=[],
        reasoning="Need to aggregate payments per customer then order.",
    )


@pytest.fixture
def execution_result() -> ExecutionResult:
    return ExecutionResult(
        success=True,
        sql="SELECT 1",
        row_count=1,
        columns=["customer_id", "total_spend"],
        sample_rows=[{"customer_id": 1, "total_spend": 150.00}],
        execution_time_ms=12.5,
    )


@pytest.fixture
def sql_candidate(execution_result: ExecutionResult) -> SQLCandidate:
    return SQLCandidate(
        sql="SELECT customer_id, SUM(amount) FROM payment GROUP BY customer_id",
        strategy="direct_cot",
        execution_result=execution_result,
        score=0.9,
    )


@pytest.fixture
def correction_step() -> CorrectionStep:
    return CorrectionStep(
        iteration=1,
        error_class="schema_error",
        original_sql="SELECT * FROM payments",
        corrected_sql="SELECT * FROM payment",
        success=True,
    )


@pytest.fixture
def audit_entry(correction_step: CorrectionStep) -> AuditEntry:
    return AuditEntry(
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        question="Show top customers",
        final_sql="SELECT customer_id, SUM(amount) FROM payment GROUP BY customer_id LIMIT 10",
        tables_used=["customer", "payment"],
        columns_used=["customer_id", "amount"],
        model_used="claude-sonnet-4-6",
        backend_used="anthropic",
        correction_steps=[correction_step],
        total_latency_ms=1234.5,
        success=True,
    )


@pytest.fixture
def pipeline_state(
    entity_context: EntityContext,
    filtered_schema: FilteredSchema,
    query_plan: QueryPlan,
    sql_candidate: SQLCandidate,
    correction_step: CorrectionStep,
    audit_entry: AuditEntry,
) -> PipelineState:
    return PipelineState(
        question="Show top customers",
        entity_context=entity_context,
        filtered_schema=filtered_schema,
        query_plan=query_plan,
        candidates=[sql_candidate],
        best_candidate=sql_candidate,
        final_sql="SELECT customer_id, SUM(amount) FROM payment GROUP BY customer_id LIMIT 10",
        correction_log=[correction_step],
        audit_entry=audit_entry,
    )


# ---------------------------------------------------------------------------
# Instantiation tests — every model with valid data
# ---------------------------------------------------------------------------

def test_column_schema_defaults():
    col = ColumnSchema(name="id", type="INTEGER")
    assert col.is_primary_key is False
    assert col.is_foreign_key is False
    assert col.description is None


def test_column_schema_full(column: ColumnSchema):
    assert column.name == "customer_id"
    assert column.is_primary_key is True


def test_table_schema(table: TableSchema):
    assert table.name == "customer"
    assert len(table.columns) == 1


def test_table_schema_empty_columns():
    t = TableSchema(name="empty_table", columns=[])
    assert t.columns == []


def test_join_path(join_path: JoinPath):
    assert join_path.from_table == "rental"
    assert join_path.to_table == "customer"


def test_raw_schema(raw_schema: RawSchema):
    assert raw_schema.db_url_hash == "abc123"
    assert len(raw_schema.tables) == 1


def test_annotated_schema_inherits_raw(annotated_schema: AnnotatedSchema):
    assert annotated_schema.db_url_hash == "abc123"
    assert "revenue" in annotated_schema.glossary


def test_annotated_schema_empty_glossary(table: TableSchema):
    schema = AnnotatedSchema(db_url_hash="xyz", tables=[table])
    assert schema.glossary == {}


def test_entity_match(entity_match: EntityMatch):
    assert entity_match.score == 0.95
    assert entity_match.matched_value == "RETAIL"


def test_entity_context(entity_context: EntityContext):
    assert entity_context.original_question != entity_context.expanded_question
    assert len(entity_context.entity_matches) == 1


def test_entity_context_empty_matches():
    ctx = EntityContext(
        original_question="q",
        expanded_question="q",
        glossary_expansions={},
        entity_matches=[],
    )
    assert ctx.entity_matches == []


def test_filtered_schema(filtered_schema: FilteredSchema):
    assert len(filtered_schema.tables) == 1
    assert len(filtered_schema.join_paths) == 1


def test_query_plan(query_plan: QueryPlan):
    assert query_plan.ordering == "total_spend DESC"
    assert query_plan.subqueries == []


def test_query_plan_no_ordering():
    plan = QueryPlan(
        aggregations=[],
        filters=[],
        joins=[],
        ordering=None,
        subqueries=[],
        reasoning="Simple lookup.",
    )
    assert plan.ordering is None


def test_execution_result_success(execution_result: ExecutionResult):
    assert execution_result.success is True
    assert execution_result.row_count == 1
    assert execution_result.error_message is None


def test_execution_result_failure():
    result = ExecutionResult(
        success=False,
        sql="SELECT * FROM nonexistent",
        row_count=0,
        columns=[],
        sample_rows=[],
        error_message="relation \"nonexistent\" does not exist",
    )
    assert result.success is False
    assert result.error_message is not None
    assert result.execution_time_ms == 0.0


def test_sql_candidate_defaults():
    candidate = SQLCandidate(sql="SELECT 1", strategy="direct_cot")
    assert candidate.score == 0.0
    assert candidate.execution_result is None


def test_sql_candidate_with_result(sql_candidate: SQLCandidate):
    assert sql_candidate.score == 0.9
    assert sql_candidate.execution_result is not None


def test_correction_step(correction_step: CorrectionStep):
    assert correction_step.iteration == 1
    assert correction_step.error_class == "schema_error"
    assert correction_step.success is True


def test_audit_entry_auto_id(audit_entry: AuditEntry):
    assert audit_entry.id is not None
    assert len(audit_entry.id) == 36  # UUID4 format


def test_audit_entry_unique_ids():
    kwargs = dict(
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        question="q",
        tables_used=[],
        columns_used=[],
        model_used="m",
        backend_used="b",
        correction_steps=[],
        total_latency_ms=0.0,
        success=True,
    )
    a1 = AuditEntry(**kwargs)
    a2 = AuditEntry(**kwargs)
    assert a1.id != a2.id


def test_audit_entry_explicit_id():
    entry = AuditEntry(
        id="fixed-id",
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        question="q",
        tables_used=[],
        columns_used=[],
        model_used="m",
        backend_used="b",
        correction_steps=[],
        total_latency_ms=0.0,
        success=True,
    )
    assert entry.id == "fixed-id"


def test_pipeline_state_minimal():
    state = PipelineState(question="How many customers?")
    assert state.candidates == []
    assert state.correction_log == []
    assert state.entity_context is None
    assert state.final_sql is None


def test_pipeline_state_full(pipeline_state: PipelineState):
    assert pipeline_state.entity_context is not None
    assert pipeline_state.filtered_schema is not None
    assert pipeline_state.query_plan is not None
    assert len(pipeline_state.candidates) == 1
    assert pipeline_state.best_candidate is not None
    assert pipeline_state.final_sql is not None
    assert len(pipeline_state.correction_log) == 1
    assert pipeline_state.audit_entry is not None


# ---------------------------------------------------------------------------
# Validation error tests
# ---------------------------------------------------------------------------

def test_column_schema_missing_name():
    with pytest.raises(ValidationError):
        ColumnSchema(type="INTEGER")


def test_column_schema_missing_type():
    with pytest.raises(ValidationError):
        ColumnSchema(name="id")


def test_table_schema_missing_name():
    with pytest.raises(ValidationError):
        TableSchema(columns=[])


def test_table_schema_missing_columns():
    with pytest.raises(ValidationError):
        TableSchema(name="t")


def test_join_path_missing_fields():
    with pytest.raises(ValidationError):
        JoinPath(from_table="a", from_column="id")


def test_raw_schema_missing_hash():
    with pytest.raises(ValidationError):
        RawSchema(tables=[])


def test_entity_match_missing_score():
    with pytest.raises(ValidationError):
        EntityMatch(token="x", table="t", column="c", matched_value="v")


def test_execution_result_missing_required():
    with pytest.raises(ValidationError):
        ExecutionResult(success=True, sql="SELECT 1")


def test_sql_candidate_missing_strategy():
    with pytest.raises(ValidationError):
        SQLCandidate(sql="SELECT 1")


def test_correction_step_missing_fields():
    with pytest.raises(ValidationError):
        CorrectionStep(iteration=1, error_class="schema_error")


def test_audit_entry_missing_timestamp():
    with pytest.raises(ValidationError):
        AuditEntry(
            question="q",
            tables_used=[],
            columns_used=[],
            model_used="m",
            backend_used="b",
            correction_steps=[],
            total_latency_ms=0.0,
            success=True,
        )


def test_pipeline_state_missing_question():
    with pytest.raises(ValidationError):
        PipelineState()
