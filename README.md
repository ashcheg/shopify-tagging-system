# Shopify Tagging System

Streamlit app for creating Shopify/Matrixify tag import files. The app reads a Shopify/Matrixify product export, previews which products match a tag-addition rule, and generates a Matrixify-ready CSV that adds one target tag with `Tags Command = MERGE`.

The app does not connect to Shopify and never modifies the original export.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run Locally

```powershell
streamlit run tagging_tool_app.py
```

Streamlit will print a local URL, usually `http://localhost:8501`.

## Use The App

1. Export products from Shopify/Matrixify as CSV or XLSX.
2. Upload the export in the app.
3. Confirm the detected columns. The file must include `Handle` and `Tags`.
4. Enter source tags separated by commas.
5. Enter the target tag to add.
6. Optionally enable conditions and add condition groups.
7. Review the summary counts and preview table.
8. Download the Matrixify import CSV and the review report CSV.
9. Click `Start New Operation` to clear the upload, tags, conditions, preset
   choice, preview, and downloads before starting another rule.

## Import With Matrixify

The Matrixify import file contains exactly these columns:

```text
Handle
Tags
Tags Command
```

Every output row sets `Tags` to the target tag only and `Tags Command` to `MERGE`. This tells Matrixify to add the tag without replacing or removing existing product tags.

Review the preview and report before importing. The output includes only products that need the new tag added.

## Condition Groups

Conditions are optional. Each condition has a column, operator, and value.

Supported operators:

```text
equals
does not equal
contains
does not contain
is blank
is not blank
greater than
greater than or equal to
less than
less than or equal to
```

Each group can match either:

```text
Match ANY condition in this group
Match ALL conditions in this group
```

Groups can then be combined with:

```text
Match all groups
Match any group
```

For example, this rule:

```text
Group 1, Match ANY:
Product Category equals Road Bikes
Product Category equals Electric Bikes

Group 2, Match ALL:
Variant Inventory Qty greater than 0

Global mode:
Match all groups
```

Evaluates as:

```text
(Product Category equals Road Bikes OR Product Category equals Electric Bikes)
AND
(Variant Inventory Qty greater than 0)
```

For products with multiple variant rows, the app evaluates conditions across all rows for the same handle. A product can match a group when at least one row for that handle satisfies that group.

## Presets

Reusable rules live in the `PRESETS` dictionary in `tagging_tool_app.py`.

Example:

```python
PRESETS = {
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
```

Add or edit presets in that dictionary, then restart Streamlit if the app is already running.

## Outputs

The app provides two downloads:

```text
Download Matrixify import CSV
Download review report CSV
```

The review report includes every product handle from the uploaded export plus rows with missing handles, with skip reasons such as:

```text
already has target tag
source tag not found
conditions not met
missing handle
```
