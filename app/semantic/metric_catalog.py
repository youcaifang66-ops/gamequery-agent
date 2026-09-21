from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    aliases: tuple[str, ...]
    formula: str
    source_table: str
    time_column: str
    grain: str
    required_tables: tuple[str, ...] = field(default_factory=tuple)


class MetricCatalog:
    def __init__(self, metrics: list[MetricDefinition]):
        self.metrics = {metric.name: metric for metric in metrics}
        self.lookup = {
            alias.lower(): metric.name
            for metric in metrics
            for alias in (metric.name, *metric.aliases)
        }

    @classmethod
    def load(cls, path: str | Path):
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(
            [
                MetricDefinition(
                    name=item["name"],
                    aliases=tuple(item["aliases"]),
                    formula=item["formula"],
                    source_table=item["source_table"],
                    time_column=item["time_column"],
                    grain=item["grain"],
                    required_tables=tuple(item.get("required_tables", [item["source_table"]])),
                )
                for item in payload["metrics"]
            ]
        )

    def resolve(self, query: str) -> list[MetricDefinition]:
        lowered = query.lower()
        names = {name for alias, name in self.lookup.items() if alias in lowered}
        return [self.metrics[name] for name in sorted(names)]

    def prompt_context(self, query: str) -> list[dict]:
        return [
            {
                "name": item.name,
                "formula": item.formula,
                "required_tables": item.required_tables,
                "time_column": item.time_column,
                "grain": item.grain,
            }
            for item in self.resolve(query)
        ]
