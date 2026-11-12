import sys

from openpyxl import load_workbook

path = sys.argv[1]
wb = load_workbook(path)  # formulas as written

for ws in wb.worksheets:
    print(f"\n=== sheet '{ws.title}' | state: {ws.sheet_state} | size: {ws.dimensions}")
    print("merged ranges:", [str(r) for r in ws.merged_cells.ranges])
    hidden_rows = [r for r, d in ws.row_dimensions.items() if d.hidden]
    hidden_cols = [c for c, d in ws.column_dimensions.items() if d.hidden]
    print("hidden rows:", hidden_rows, "| hidden cols:", hidden_cols)
    for row in ws.iter_rows():
        values = [(c.coordinate, c.value) for c in row if c.value is not None]
        if values:
            print(values)