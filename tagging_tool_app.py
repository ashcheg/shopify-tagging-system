from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO
from typing import Any

import pandas as pd
import streamlit as st


OUTPUT_COLUMNS = ["Handle", "Tags", "Tags Command"]
REVIEW_COLUMNS = [
    "Handle",
    "Title",
    "Existing Tags",
    "Target Tag",
    "Matched Source Tag",
    "Condition Result",
    "Matched Condition Details",
    "Included In Output",
    "Skip Reason",
]

OPERATORS = [
    "equals",
    "does not equal",
    "contains",
    "does not contain",
    "is blank",
    "is not blank",
    "greater than",
    "greater than or equal to",
    "less than",
    "less than or equal to",
]

NUMERIC_OPERATORS = {
    "greater than",
    "greater than or equal to",
    "less than",
    "less than or equal to",
}

PRESETS: dict[str, dict[str, Any]] = {
    "Add gravel bikes": {
        "source_tags": [
            "gravel & cyclocross",
            "gravel",
            "e-gravel",
            "all gravel bikes",
        ],
        "target_tag": "gravel bikes",
        "groups": [
            {
                "group_mode": "ANY",
                "conditions": [
                    {
                        "column": "Product Category",
                        "operator": "equals",
                        "value": "Road Bikes",
                    },
                    {
                        "column": "Product Category",
                        "operator": "equals",
                        "value": "Electric Bikes",
                    },
                ],
            },
            {
                "group_mode": "ALL",
                "conditions": [
                    {
                        "column": "Variant Inventory Qty",
                        "operator": "greater than",
                        "value": "0",
                    }
                ],
            },
        ],
        "global_group_mode": "ALL",
    }
}


@dataclass
class ConditionOutcome:
    matched: bool
    detail: str
    warning: str | None = None


@dataclass
class ProductEvaluation:
    handle: str
    title: str = ""
    existing_tags: list[str] = field(default_factory=list)
    matched_source_tags: list[str] = field(default_factory=list)
    already_has_target_tag: bool = False
    condition_result: bool = True
    matched_condition_details: list[str] = field(default_factory=list)
    included_in_output: bool = False
    skip_reason: str = ""


def display_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def normalize_tag(value: Any) -> str:
    return " ".join(display_value(value).split()).casefold()


def split_tags(tags_value: Any) -> list[str]:
    return [tag for tag in (normalize_tag(part) for part in display_value(tags_value).split(",")) if tag]


def split_tag_input(value: str) -> list[str]:
    return [tag for tag in (display_value(part) for part in value.split(",")) if tag]


def row_has_any_source_tag(row: pd.Series, source_tags: set[str]) -> tuple[bool, list[str]]:
    row_tags = set(split_tags(row.get("Tags")))
    matched = sorted(row_tags.intersection(source_tags))
    return bool(matched), matched


def row_has_target_tag(row: pd.Series, target_tag: str) -> bool:
    return target_tag in set(split_tags(row.get("Tags")))


def safe_number(value: Any) -> float | None:
    text = display_value(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def evaluate_condition(row: pd.Series, condition: dict[str, str]) -> ConditionOutcome:
    column = condition.get("column", "")
    operator = condition.get("operator", "equals")
    expected_raw = condition.get("value", "")

    if not column or column not in row.index:
        return ConditionOutcome(False, f"{column or 'Column'} is not available", None)

    actual_raw = row.get(column)
    actual = normalize_tag(actual_raw)
    expected = normalize_tag(expected_raw)
    label = f"{column} {operator}" if operator in {"is blank", "is not blank"} else f"{column} {operator} {expected_raw}"

    if operator == "equals":
        return ConditionOutcome(actual == expected, label)
    if operator == "does not equal":
        return ConditionOutcome(actual != expected, label)
    if operator == "contains":
        return ConditionOutcome(expected in actual, label)
    if operator == "does not contain":
        return ConditionOutcome(expected not in actual, label)
    if operator == "is blank":
        return ConditionOutcome(actual == "", label)
    if operator == "is not blank":
        return ConditionOutcome(actual != "", label)

    if operator in NUMERIC_OPERATORS:
        actual_number = safe_number(actual_raw)
        expected_number = safe_number(expected_raw)
        if actual_number is None:
            return ConditionOutcome(
                False,
                label,
                f"{column} value '{display_value(actual_raw)}' could not be read as a number.",
            )
        if expected_number is None:
            return ConditionOutcome(
                False,
                label,
                f"Condition value '{expected_raw}' for {column} could not be read as a number.",
            )
        if operator == "greater than":
            return ConditionOutcome(actual_number > expected_number, label)
        if operator == "greater than or equal to":
            return ConditionOutcome(actual_number >= expected_number, label)
        if operator == "less than":
            return ConditionOutcome(actual_number < expected_number, label)
        if operator == "less than or equal to":
            return ConditionOutcome(actual_number <= expected_number, label)

    return ConditionOutcome(False, f"Unsupported operator: {operator}", None)


def evaluate_condition_group(row: pd.Series, group: dict[str, Any]) -> ConditionOutcome:
    conditions = [condition for condition in group.get("conditions", []) if condition.get("column")]
    if not conditions:
        return ConditionOutcome(True, "No conditions in group")

    outcomes = [evaluate_condition(row, condition) for condition in conditions]
    mode = group.get("group_mode", "ANY")
    matched = all(outcome.matched for outcome in outcomes) if mode == "ALL" else any(outcome.matched for outcome in outcomes)
    joiner = " AND " if mode == "ALL" else " OR "
    matched_details = [outcome.detail for outcome in outcomes if outcome.matched]
    detail = joiner.join(matched_details) if matched_details else "No condition matched"
    warnings = [outcome.warning for outcome in outcomes if outcome.warning]
    return ConditionOutcome(matched, detail, "; ".join(warnings) if warnings else None)


def evaluate_all_condition_groups(
    rows: pd.DataFrame,
    groups: list[dict[str, Any]],
    global_group_mode: str,
    conditions_enabled: bool,
) -> tuple[bool, list[str], list[str]]:
    if not conditions_enabled or not groups:
        return True, ["No conditions enabled"], []

    group_matches: list[bool] = []
    details: list[str] = []
    warnings: list[str] = []

    for index, group in enumerate(groups, start=1):
        row_outcomes = [evaluate_condition_group(row, group) for _, row in rows.iterrows()]
        group_matched = any(outcome.matched for outcome in row_outcomes)
        group_matches.append(group_matched)

        matched_detail = next((outcome.detail for outcome in row_outcomes if outcome.matched), "")
        if group_matched:
            details.append(f"Group {index}: {matched_detail}")
        else:
            details.append(f"Group {index}: not matched")

        warnings.extend(outcome.warning for outcome in row_outcomes if outcome.warning)

    final_match = all(group_matches) if global_group_mode == "ALL" else any(group_matches)
    return final_match, details, sorted(set(warnings))


def first_non_blank(rows: pd.DataFrame, column: str) -> str:
    if column not in rows.columns:
        return ""
    for value in rows[column]:
        text = display_value(value)
        if text:
            return text
    return ""


def unique_existing_tags(rows: pd.DataFrame) -> list[str]:
    seen: dict[str, str] = {}
    for value in rows.get("Tags", pd.Series(dtype=str)):
        for raw_tag in display_value(value).split(","):
            display = display_value(raw_tag)
            normalized = normalize_tag(display)
            if normalized and normalized not in seen:
                seen[normalized] = display
    return list(seen.values())


def build_product_evaluations(
    df: pd.DataFrame,
    source_tag_labels: list[str],
    target_tag_label: str,
    groups: list[dict[str, Any]],
    global_group_mode: str,
    conditions_enabled: bool,
) -> tuple[list[ProductEvaluation], list[str]]:
    source_tags = {normalize_tag(tag) for tag in source_tag_labels if normalize_tag(tag)}
    source_display_by_normalized = {normalize_tag(tag): display_value(tag) for tag in source_tag_labels}
    target_tag = normalize_tag(target_tag_label)
    evaluations: list[ProductEvaluation] = []
    warnings: list[str] = []

    missing_handle_rows = df[df["Handle"].map(display_value) == ""]
    for _, row in missing_handle_rows.iterrows():
        evaluations.append(
            ProductEvaluation(
                handle="",
                title=display_value(row.get("Title")),
                existing_tags=unique_existing_tags(pd.DataFrame([row])),
                condition_result=False,
                included_in_output=False,
                skip_reason="missing handle",
            )
        )

    valid_df = df[df["Handle"].map(display_value) != ""].copy()
    for handle, product_rows in valid_df.groupby(valid_df["Handle"].map(display_value), sort=False):
        matched_source: dict[str, str] = {}
        already_has_target = False

        for _, row in product_rows.iterrows():
            _, row_source_matches = row_has_any_source_tag(row, source_tags)
            for tag in row_source_matches:
                matched_source[tag] = source_display_by_normalized.get(tag, tag)
            already_has_target = already_has_target or row_has_target_tag(row, target_tag)

        condition_result, condition_details, condition_warnings = evaluate_all_condition_groups(
            product_rows,
            groups,
            global_group_mode,
            conditions_enabled,
        )
        warnings.extend(condition_warnings)

        skip_reason = ""
        included = False
        if not matched_source:
            skip_reason = "source tag not found"
        elif not condition_result:
            skip_reason = "conditions not met"
        elif already_has_target:
            skip_reason = "already has target tag"
        else:
            included = True

        evaluations.append(
            ProductEvaluation(
                handle=handle,
                title=first_non_blank(product_rows, "Title"),
                existing_tags=unique_existing_tags(product_rows),
                matched_source_tags=list(matched_source.values()),
                already_has_target_tag=already_has_target,
                condition_result=condition_result,
                matched_condition_details=condition_details,
                included_in_output=included,
                skip_reason=skip_reason,
            )
        )

    return evaluations, sorted(set(warnings))


def build_output_dataframe(evaluations: list[ProductEvaluation], target_tag: str) -> pd.DataFrame:
    rows = [
        {"Handle": item.handle, "Tags": target_tag, "Tags Command": "MERGE"}
        for item in evaluations
        if item.included_in_output
    ]
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def build_review_report(evaluations: list[ProductEvaluation], target_tag: str) -> pd.DataFrame:
    rows = []
    for item in evaluations:
        rows.append(
            {
                "Handle": item.handle,
                "Title": item.title,
                "Existing Tags": ", ".join(item.existing_tags),
                "Target Tag": target_tag,
                "Matched Source Tag": ", ".join(item.matched_source_tags),
                "Condition Result": "yes" if item.condition_result else "no",
                "Matched Condition Details": "; ".join(item.matched_condition_details),
                "Included In Output": "yes" if item.included_in_output else "no",
                "Skip Reason": item.skip_reason,
            }
        )
    return pd.DataFrame(rows, columns=REVIEW_COLUMNS)


def read_uploaded_file(uploaded_file: Any) -> pd.DataFrame:
    if uploaded_file.name.lower().endswith(".xlsx"):
        return pd.read_excel(uploaded_file, dtype=object)
    return pd.read_csv(uploaded_file, dtype=object, keep_default_na=False)


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    buffer = StringIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8-sig")


def default_group() -> dict[str, Any]:
    return {
        "group_mode": "ANY",
        "conditions": [{"column": "", "operator": "equals", "value": ""}],
    }


def ensure_session_state() -> None:
    st.session_state.setdefault("operation_id", 0)
    st.session_state.setdefault("source_tags_input", "")
    st.session_state.setdefault("target_tag", "")
    st.session_state.setdefault("conditions_enabled", False)
    st.session_state.setdefault("global_group_mode", "ALL")
    st.session_state.setdefault("condition_groups", [default_group()])


def reset_operation_state() -> None:
    st.session_state.operation_id += 1
    st.session_state.source_tags_input = ""
    st.session_state.target_tag = ""
    st.session_state.conditions_enabled = False
    st.session_state.global_group_mode = "ALL"
    st.session_state.condition_groups = [default_group()]


def apply_preset(name: str) -> None:
    preset = PRESETS[name]
    st.session_state.source_tags_input = ", ".join(preset["source_tags"])
    st.session_state.target_tag = preset["target_tag"]
    st.session_state.conditions_enabled = True
    st.session_state.global_group_mode = preset.get("global_group_mode", "ALL")
    st.session_state.condition_groups = [
        {
            "group_mode": group.get("group_mode", "ANY"),
            "conditions": [dict(condition) for condition in group.get("conditions", [])],
        }
        for group in preset.get("groups", [])
    ] or [default_group()]


def mode_label_to_value(label: str) -> str:
    return "ALL" if "ALL" in label else "ANY"


def mode_value_to_label(value: str, scope: str) -> str:
    if scope == "group":
        return "Match ALL conditions in this group" if value == "ALL" else "Match ANY condition in this group"
    return "Match all groups" if value == "ALL" else "Match any group"


def build_logic_preview(source_tags: list[str], target_tag: str, groups: list[dict[str, Any]], global_mode: str, enabled: bool) -> str:
    lines = [
        "Existing tag matches one of:",
        ", ".join(source_tags) if source_tags else "(enter source tags)",
    ]
    if enabled and groups:
        lines.append("")
        lines.append("AND" if global_mode == "ALL" else "AND/OR group logic")
        group_joiner = "\n\nAND\n\n" if global_mode == "ALL" else "\n\nOR\n\n"
        group_blocks = []
        for group in groups:
            condition_joiner = "\n  AND " if group.get("group_mode") == "ALL" else "\n  OR "
            condition_lines = []
            for condition in group.get("conditions", []):
                column = condition.get("column") or "(choose column)"
                operator = condition.get("operator", "equals")
                value = "" if operator in {"is blank", "is not blank"} else f" {condition.get('value', '')}"
                condition_lines.append(f"{column} {operator}{value}")
            group_blocks.append("(\n  " + condition_joiner.join(condition_lines) + "\n)")
        lines.append(group_joiner.join(group_blocks))
    lines.extend(["", "THEN add:", target_tag or "(enter target tag)"])
    return "\n".join(lines)


def render_condition_builder(columns: list[str]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = st.session_state.condition_groups
    cleaned_groups: list[dict[str, Any]] = []
    operation_id = st.session_state.operation_id

    for group_index, group in enumerate(groups):
        st.subheader(f"Condition Group {group_index + 1}")
        group_mode_label = st.radio(
            "Group match mode",
            ["Match ANY condition in this group", "Match ALL conditions in this group"],
            index=0 if group.get("group_mode", "ANY") == "ANY" else 1,
            key=f"group_mode_{operation_id}_{group_index}",
            horizontal=True,
        )

        cleaned_conditions = []
        for condition_index, condition in enumerate(group.get("conditions", [])):
            cols = st.columns([2.2, 1.4, 2.2, 0.6])
            column_options = [""] + columns
            current_column = condition.get("column", "")
            column_index = column_options.index(current_column) if current_column in column_options else 0
            operator = condition.get("operator", "equals")
            operator_index = OPERATORS.index(operator) if operator in OPERATORS else 0

            with cols[0]:
                selected_column = st.selectbox(
                    "Column",
                    column_options,
                    index=column_index,
                    key=f"condition_column_{operation_id}_{group_index}_{condition_index}",
                )
            with cols[1]:
                selected_operator = st.selectbox(
                    "Operator",
                    OPERATORS,
                    index=operator_index,
                    key=f"condition_operator_{operation_id}_{group_index}_{condition_index}",
                )
            with cols[2]:
                selected_value = st.text_input(
                    "Value",
                    value=condition.get("value", ""),
                    disabled=selected_operator in {"is blank", "is not blank"},
                    key=f"condition_value_{operation_id}_{group_index}_{condition_index}",
                )
            with cols[3]:
                st.write("")
                st.write("")
                if st.button("Remove", key=f"remove_condition_{operation_id}_{group_index}_{condition_index}"):
                    group["conditions"].pop(condition_index)
                    st.rerun()

            cleaned_conditions.append(
                {
                    "column": selected_column,
                    "operator": selected_operator,
                    "value": "" if selected_operator in {"is blank", "is not blank"} else selected_value,
                }
            )

        if st.button("Add condition to this group", key=f"add_condition_{operation_id}_{group_index}"):
            group.setdefault("conditions", []).append({"column": "", "operator": "equals", "value": ""})
            st.rerun()

        cleaned_groups.append(
            {
                "group_mode": mode_label_to_value(group_mode_label),
                "conditions": cleaned_conditions or [{"column": "", "operator": "equals", "value": ""}],
            }
        )

    controls = st.columns([1, 1])
    with controls[0]:
        if st.button("Add another group", key=f"add_group_{operation_id}"):
            groups.append(default_group())
            st.rerun()
    with controls[1]:
        if len(groups) > 1 and st.button("Remove last group", key=f"remove_group_{operation_id}"):
            groups.pop()
            st.rerun()

    st.session_state.condition_groups = cleaned_groups
    return cleaned_groups


def main() -> None:
    st.set_page_config(page_title="Shopify Matrixify Tagging Tool", page_icon="tag", layout="wide")
    ensure_session_state()

    st.title("Shopify Matrixify Tagging Tool")
    st.warning(
        "Safety check: this app only creates a Matrixify import file that adds tags with MERGE. "
        "It never changes the original export and it does not remove existing tags. "
        "Review the preview and report before importing with Matrixify."
    )

    if st.button("Start New Operation"):
        reset_operation_state()
        st.rerun()

    operation_id = st.session_state.operation_id
    uploaded_file = st.file_uploader(
        "Upload Shopify/Matrixify product export",
        type=["csv", "xlsx"],
        key=f"uploaded_file_{operation_id}",
    )

    preset_names = ["No preset"] + list(PRESETS)
    preset_choice = st.selectbox("Optional preset", preset_names, key=f"preset_choice_{operation_id}")
    if preset_choice != "No preset" and st.button("Load preset"):
        apply_preset(preset_choice)
        st.rerun()

    source_tags_input = st.text_area(
        "Source tags to look for, separated by commas",
        key="source_tags_input",
        placeholder="gravel & cyclocross, gravel, e-gravel, all gravel bikes",
    )
    target_tag = st.text_input("Target tag to add", key="target_tag", placeholder="gravel bikes")

    if uploaded_file is None:
        st.info("Upload a CSV export to begin. XLSX files are supported when openpyxl is installed.")
        return

    try:
        df = read_uploaded_file(uploaded_file)
    except ImportError:
        st.error("XLSX support requires openpyxl. Install it with: pip install openpyxl")
        return
    except Exception as exc:
        st.error(f"Could not read the uploaded file: {exc}")
        return

    df.columns = [display_value(column) for column in df.columns]
    columns = list(df.columns)
    st.caption("Detected columns")
    st.write(columns)

    missing_columns = [column for column in ["Handle", "Tags"] if column not in columns]
    if missing_columns:
        st.error(f"Missing required column(s): {', '.join(missing_columns)}")
        return

    conditions_enabled = st.checkbox("Enable conditions", key="conditions_enabled")
    global_mode_label = st.radio(
        "How should groups be matched?",
        ["Match all groups", "Match any group"],
        index=0 if st.session_state.global_group_mode == "ALL" else 1,
        horizontal=True,
        disabled=not conditions_enabled,
        key=f"global_group_mode_label_{operation_id}",
    )
    st.session_state.global_group_mode = mode_label_to_value(global_mode_label)

    groups = st.session_state.condition_groups
    if conditions_enabled:
        groups = render_condition_builder(columns)

    source_tags = split_tag_input(source_tags_input)
    st.text_area(
        "Rule preview",
        value=build_logic_preview(source_tags, target_tag, groups, st.session_state.global_group_mode, conditions_enabled),
        height=220,
        disabled=True,
    )

    if not source_tags:
        st.error("Enter at least one source tag.")
        return
    if not display_value(target_tag):
        st.error("Enter the target tag to add.")
        return

    evaluations, warnings = build_product_evaluations(
        df=df,
        source_tag_labels=source_tags,
        target_tag_label=target_tag,
        groups=groups,
        global_group_mode=st.session_state.global_group_mode,
        conditions_enabled=conditions_enabled,
    )
    output_df = build_output_dataframe(evaluations, target_tag)
    review_df = build_review_report(evaluations, target_tag)

    matching_source = [item for item in evaluations if item.handle and item.matched_source_tags]
    matching_source_conditions = [
        item for item in matching_source if item.condition_result
    ]
    skipped_existing = [
        item for item in matching_source_conditions if item.already_has_target_tag
    ]

    st.subheader("Preview Summary")
    metrics = st.columns(6)
    metrics[0].metric("total rows scanned", len(df))
    metrics[1].metric("unique products scanned", df["Handle"].map(display_value).replace("", pd.NA).dropna().nunique())
    metrics[2].metric("products matching source tags", len(matching_source))
    metrics[3].metric("source tags + conditions", len(matching_source_conditions))
    metrics[4].metric("skipped existing tag", len(skipped_existing))
    metrics[5].metric("final output", len(output_df))

    for warning in warnings[:20]:
        st.warning(warning)
    if len(warnings) > 20:
        st.warning(f"{len(warnings) - 20} additional numeric conversion warnings were hidden.")

    preview_columns = {
        "Handle": "Handle",
        "Title": "Title",
        "Existing Tags": "Existing Tags",
        "Target Tag": "Target Tag",
        "Condition Result": "Condition Result",
        "Matched Condition Details": "Matched Condition Details",
    }
    st.subheader("Review Preview")
    st.dataframe(review_df[list(preview_columns)].head(200), width=None)

    downloads = st.columns(2)
    with downloads[0]:
        st.download_button(
            "Download Matrixify import CSV",
            data=dataframe_to_csv_bytes(output_df),
            file_name="matrixify-tag-import.csv",
            mime="text/csv",
            disabled=output_df.empty,
        )
    with downloads[1]:
        st.download_button(
            "Download review report CSV",
            data=dataframe_to_csv_bytes(review_df),
            file_name="matrixify-tag-review-report.csv",
            mime="text/csv",
        )


if __name__ == "__main__":
    main()
