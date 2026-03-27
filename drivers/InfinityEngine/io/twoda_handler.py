"""
Parses Infinity Engine 2DA tables.
"""


class TwoDAHandler:
    def __init__(self, text):
        self.text = text or ""
        self.default_value = ""
        self.columns = []
        self.rows = []
        self.row_map = {}
        self._parse()

    def _parse(self):
        lines = [line.strip() for line in self.text.splitlines() if line.strip()]
        if not lines:
            return

        signature = lines[0].lstrip("\ufeff")
        if not signature.upper().startswith("2DA V1.0"):
            raise ValueError("Invalid 2DA signature")

        self.default_value = lines[1].split()[0] if len(lines) > 1 and lines[1].split() else ""
        self.columns = lines[2].split() if len(lines) > 2 else []

        for raw_line in lines[3:]:
            parts = raw_line.split()
            if not parts:
                continue

            row_label = parts[0]
            cells = parts[1:]
            if len(cells) < len(self.columns):
                cells.extend([self.default_value] * (len(self.columns) - len(cells)))

            row = {"_row_label": row_label}
            for index, column in enumerate(self.columns):
                row[column] = cells[index] if index < len(cells) else self.default_value

            self.rows.append(row)
            self.row_map[row_label] = row

    def get_row(self, key, row_mode="label"):
        if row_mode == "index":
            try:
                index = int(key)
            except (TypeError, ValueError):
                return None

            if 0 <= index < len(self.rows):
                return self.rows[index]
            return None

        return self.row_map.get(str(key))

    def resolve(self, key, column=None, row_mode="label"):
        row = self.get_row(key, row_mode=row_mode)
        if row is None:
            return None

        if column is None:
            return dict(row)

        return row.get(column, self.default_value)
