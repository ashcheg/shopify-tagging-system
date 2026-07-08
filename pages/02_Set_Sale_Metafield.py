from __future__ import annotations

from io import StringIO
from typing import Any

import pandas as pd
import streamlit as st


HANDLE_COLUMN = "Handle"
TITLE_COLUMN = "Title"
SKU_COLUMN = "Variant SKU"
PRICE_COLUMN = "Variant Price"
COMPARE_AT_PRICE_COLUMN = "Variant Compare At Price"
SALE_METAFIELD_COLUMN = "Metafield: custom.sale [single_line_text_field]"

CURRENT_SALE_VALUE_COLUMN = "Current custom.sale value"
NEW_SALE_VALUE_COLUMN = "New custom.sale value"
INCLUDED_COLUMN = "Included In Output"
SKIP_REASON_COLUMN = "Skip Reason"

SALE_VALUE = "Sale"
REQUIRED_COLUMNS = [HANDLE_COLUMN, PRICE_COLUMN, COMPARE_AT_PRICE_COLUMN]
PRICE_DATA_SKIP_REASONS = {
    "missing price",
    "missing compare-at price",
    "invalid price data",
}


def display_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def to_number(value: Any) -> float | None:
    text = display_value(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def is_sale_variant(row: pd.Series) -> tuple[bool, str]:
    price_text = display_value(row.get(PRICE_COLUMN))
    compare_at_price_text = display_value(row.get(COMPARE_AT_PRICE_COLUMN))

    if not price_text:
        return False, "missing price"
    if not compare_at_price_text:
        return False, "missing compare-at price"

    price = to_number(price_text)
    compare_at_price = to_number(compare_at_price_text)
    if price is None or compare_at_price is None:
        return False, "invalid price data"

    if compare_at_price > price:
        return True, ""
    return False, "not on sale"


def is_marked_sale(value: Any) -> bool:
    return display_value(value).casefold() == SALE_VALUE


def read_uploaded_file(uploaded_file: Any) -> pd.DataFrame:
    filename = uploaded_file.name.lower()
    if filename.endswith((".xlsx", ".xlsm")):
        return pd.read_excel(uploaded_file, dtype=object)
    return pd.read_csv(uploaded_file, dtype=object, keep_default_na=False)


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    buffer = StringIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8-sig")


def build_sale_review_report(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    rows: list[dict[str, str]] = []
    has_sale_metafield = SALE_METAFIELD_COLUMN in df.columns
    valid_handles = df[HANDLE_COLUMN].map(display_value)
    row_skip_reasons: list[str] = []
    products_with_sale_variant: set[str] = set()
    products_already_sale: set[str] = set()
    products_included: set[str] = set()
    product_sale_status: dict[str, bool] = {}
    product_existing_sale_status: dict[str, bool] = {}

    for handle, product_rows in df[valid_handles != ""].groupby(valid_handles[valid_handles != ""], sort=False):
        product_has_sale = False
        for _, row in product_rows.iterrows():
            sale_variant, _ = is_sale_variant(row)
            product_has_sale = product_has_sale or sale_variant

        already_sale = (
            has_sale_metafield
            and product_rows[SALE_METAFIELD_COLUMN].map(is_marked_sale).any()
        )

        product_sale_status[handle] = product_has_sale
        product_existing_sale_status[handle] = already_sale

        if product_has_sale:
            products_with_sale_variant.add(handle)
        if product_has_sale and already_sale:
            products_already_sale.add(handle)
        if product_has_sale and not already_sale:
            products_included.add(handle)

    for _, row in df.iterrows():
        handle = display_value(row.get(HANDLE_COLUMN))
        sale_variant, row_skip_reason = is_sale_variant(row)
        row_skip_reasons.append(row_skip_reason)
        product_has_sale = product_sale_status.get(handle, sale_variant)
        already_sale = product_existing_sale_status.get(handle, False)
        included = bool(handle and product_has_sale and not already_sale)

        if included and sale_variant:
            skip_reason = ""
        elif already_sale and product_has_sale:
            skip_reason = "already marked sale"
        else:
            skip_reason = row_skip_reason

        review_row = {
            HANDLE_COLUMN: handle,
            PRICE_COLUMN: display_value(row.get(PRICE_COLUMN)),
            COMPARE_AT_PRICE_COLUMN: display_value(row.get(COMPARE_AT_PRICE_COLUMN)),
            CURRENT_SALE_VALUE_COLUMN: (
                display_value(row.get(SALE_METAFIELD_COLUMN)) if has_sale_metafield else ""
            ),
            NEW_SALE_VALUE_COLUMN: SALE_VALUE if included else "",
            INCLUDED_COLUMN: "yes" if included else "no",
            SKIP_REASON_COLUMN: skip_reason,
        }

        if TITLE_COLUMN in df.columns:
            review_row[TITLE_COLUMN] = display_value(row.get(TITLE_COLUMN))
        if SKU_COLUMN in df.columns:
            review_row[SKU_COLUMN] = display_value(row.get(SKU_COLUMN))

        rows.append(review_row)

    review_columns = [HANDLE_COLUMN]
    if TITLE_COLUMN in df.columns:
        review_columns.append(TITLE_COLUMN)
    if SKU_COLUMN in df.columns:
        review_columns.append(SKU_COLUMN)
    review_columns.extend(
        [
            PRICE_COLUMN,
            COMPARE_AT_PRICE_COLUMN,
            CURRENT_SALE_VALUE_COLUMN,
            NEW_SALE_VALUE_COLUMN,
            INCLUDED_COLUMN,
            SKIP_REASON_COLUMN,
        ]
    )

    metrics = {
        "total_rows_scanned": len(df),
        "unique_products_scanned": valid_handles.replace("", pd.NA).dropna().nunique(),
        "products_with_sale_variant": len(products_with_sale_variant),
        "products_skipped_already_sale": len(products_already_sale),
        "products_included": len(products_included),
        "rows_skipped_invalid_or_missing_price": sum(
            reason in PRICE_DATA_SKIP_REASONS for reason in row_skip_reasons
        ),
    }

    return pd.DataFrame(rows, columns=review_columns), metrics


def build_sale_metafield_output(review_df: pd.DataFrame) -> pd.DataFrame:
    included_handles = (
        review_df.loc[review_df[INCLUDED_COLUMN] == "yes", HANDLE_COLUMN]
        .map(display_value)
        .replace("", pd.NA)
        .dropna()
        .drop_duplicates()
    )

    return pd.DataFrame(
        {
            HANDLE_COLUMN: included_handles,
            SALE_METAFIELD_COLUMN: SALE_VALUE,
        },
        columns=[HANDLE_COLUMN, SALE_METAFIELD_COLUMN],
    )


def build_preview(review_df: pd.DataFrame) -> pd.DataFrame:
    preview_columns = [
        HANDLE_COLUMN,
        TITLE_COLUMN,
        SKU_COLUMN,
        PRICE_COLUMN,
        COMPARE_AT_PRICE_COLUMN,
        CURRENT_SALE_VALUE_COLUMN,
        NEW_SALE_VALUE_COLUMN,
    ]
    return review_df[[column for column in preview_columns if column in review_df.columns]]


def render_metrics(metrics: dict[str, int]) -> None:
    metric_columns = st.columns(3)
    metric_values = [
        ("Total rows scanned", metrics["total_rows_scanned"]),
        ("Unique products scanned", metrics["unique_products_scanned"]),
        ("Products with at least one sale variant", metrics["products_with_sale_variant"]),
        (
            "Products skipped because custom.sale is already sale",
            metrics["products_skipped_already_sale"],
        ),
        ("Products included in output", metrics["products_included"]),
        (
            "Rows skipped because of invalid or missing price data",
            metrics["rows_skipped_invalid_or_missing_price"],
        ),
    ]

    for index, (label, value) in enumerate(metric_values):
        metric_columns[index % 3].metric(label, value)


def main() -> None:
    st.set_page_config(page_title="Set Sale Metafield", page_icon="tag", layout="wide")

    st.title("Set Sale Metafield")
    st.write(
        'Upload a Shopify/Matrixify product export. This tool finds products where at least one variant has Variant Compare At Price greater than Variant Price, then generates a Matrixify import file that sets custom.sale to "sale".'
    )

    uploaded_file = st.file_uploader(
        "Upload Shopify/Matrixify product export",
        type=["csv", "xlsx", "xlsm"],
    )

    if uploaded_file is None:
        st.info("Upload a CSV or XLSX file to begin.")
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

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing_columns:
        st.error(f"Missing required column(s): {', '.join(missing_columns)}")
        return

    review_df, metrics = build_sale_review_report(df)
    output_df = build_sale_metafield_output(review_df)

    st.subheader("Preview Summary")
    render_metrics(metrics)

    st.subheader("Review Preview")
    st.dataframe(build_preview(review_df).head(200), width="stretch")

    st.info(
        'This file does not update Shopify directly. Review it, then import it through Matrixify. It will set custom.sale to "sale" for products where at least one variant has Compare At Price greater than Price.'
    )

    downloads = st.columns(2)
    with downloads[0]:
        st.download_button(
            "Download Matrixify import CSV",
            data=dataframe_to_csv_bytes(output_df),
            file_name="matrixify-set-sale-metafield.csv",
            mime="text/csv",
            disabled=output_df.empty,
        )
    with downloads[1]:
        st.download_button(
            "Download review report CSV",
            data=dataframe_to_csv_bytes(review_df),
            file_name="matrixify-set-sale-metafield-review-report.csv",
            mime="text/csv",
        )


if __name__ == "__main__":
    main()
