import yaml


def load(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def label_values(cfg: dict, label: str) -> list[str]:
    return list(cfg.get("labels", {}).get(label, {}).get("values", {}).keys())


def label_descriptions(cfg: dict, label: str) -> dict[str, str]:
    values = cfg.get("labels", {}).get(label, {}).get("values", {})
    return {k: v.get("description", "") for k, v in values.items()}
