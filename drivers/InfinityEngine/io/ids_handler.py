"""
Parses Infinity Engine IDS identifier tables.
"""


class IdsHandler:
    def __init__(self, text):
        self.text = text or ""
        self.entries = {}
        self.reverse_entries = {}
        self._parse()

    def _parse(self):
        for raw_line in self.text.splitlines():
            line = raw_line.split("//", 1)[0].strip()
            if not line:
                continue

            upper = line.upper()
            if upper == "IDS" or upper.startswith("IDS V"):
                continue

            parts = line.split()
            if len(parts) < 2:
                continue

            try:
                value = int(parts[0], 0)
            except ValueError:
                continue

            symbol = parts[1].strip()
            if not symbol:
                continue

            self.entries[value] = symbol
            self.reverse_entries[symbol] = value

    def resolve(self, value):
        return self.entries.get(value)

    def lookup(self, symbol):
        return self.reverse_entries.get(symbol)
