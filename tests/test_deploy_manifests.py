"""Consistency checks for the Kubernetes and Compose deployment files.

CI also validates the rendered manifests against the Kubernetes schemas with
kubeconform; these tests catch the cross-object mistakes a schema can't:
selectors that match no pods, an HPA pointing at nothing, probes on ports that
don't exist, the settings the app actually reads.
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "deploy" / "k8s" / "base"
OPTIONAL = ROOT / "deploy" / "k8s" / "optional"


def _docs(path: Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _base_objects() -> list[dict]:
    kustomization = yaml.safe_load((BASE / "kustomization.yaml").read_text())
    objects = []
    for resource in kustomization["resources"]:
        objects.extend(_docs(BASE / resource))
    return objects


def _by_kind(kind: str) -> list[dict]:
    return [o for o in _base_objects() if o["kind"] == kind]


def test_kustomization_lists_every_base_file():
    kustomization = yaml.safe_load((BASE / "kustomization.yaml").read_text())
    on_disk = {p.name for p in BASE.glob("*.yaml")} - {"kustomization.yaml"}
    assert set(kustomization["resources"]) == on_disk


@pytest.mark.parametrize("path", sorted([*BASE.glob("*.yaml"), *OPTIONAL.glob("*.yaml")]), ids=lambda p: p.name)
def test_every_document_is_well_formed(path: Path):
    for doc in _docs(path):
        if path.name == "kustomization.yaml":
            continue
        assert doc.get("apiVersion") and doc.get("kind"), path
        assert doc.get("metadata", {}).get("name"), path


def test_service_selectors_match_deployment_pods():
    pods = {d["metadata"]["name"]: d["spec"]["template"]["metadata"]["labels"] for d in _by_kind("Deployment")}
    for svc in _by_kind("Service"):
        selector = svc["spec"]["selector"]
        assert any(selector.items() <= labels.items() for labels in pods.values()), svc["metadata"]["name"]


def test_deployment_selectors_match_their_templates():
    for dep in _by_kind("Deployment"):
        selector = dep["spec"]["selector"]["matchLabels"]
        assert selector.items() <= dep["spec"]["template"]["metadata"]["labels"].items()


def test_hpas_and_pdbs_target_real_deployments():
    deployments = {d["metadata"]["name"]: d for d in _by_kind("Deployment")}
    for hpa in _by_kind("HorizontalPodAutoscaler"):
        ref = hpa["spec"]["scaleTargetRef"]
        assert ref["kind"] == "Deployment" and ref["name"] in deployments
        assert 1 < hpa["spec"]["minReplicas"] <= hpa["spec"]["maxReplicas"]
        # Utilization targets need resource requests on every container.
        for container in deployments[ref["name"]]["spec"]["template"]["spec"]["containers"]:
            assert container["resources"]["requests"]["cpu"]
    labels = [d["spec"]["template"]["metadata"]["labels"] for d in deployments.values()]
    for pdb in _by_kind("PodDisruptionBudget"):
        sel = pdb["spec"]["selector"]["matchLabels"]
        assert any(sel.items() <= lab.items() for lab in labels), pdb["metadata"]["name"]


def test_probes_use_declared_ports_and_real_endpoints():
    for dep in _by_kind("Deployment"):
        for c in dep["spec"]["template"]["spec"]["containers"]:
            port_names = {p["name"] for p in c["ports"]}
            for probe in ("startupProbe", "livenessProbe", "readinessProbe"):
                if probe in c:
                    assert c[probe]["httpGet"]["port"] in port_names
    api = next(d for d in _by_kind("Deployment") if d["metadata"]["name"] == "api")
    c = api["spec"]["template"]["spec"]["containers"][0]
    assert c["readinessProbe"]["httpGet"]["path"] == "/ready"
    assert c["livenessProbe"]["httpGet"]["path"] == "/health"


def test_pods_are_locked_down():
    for dep in _by_kind("Deployment"):
        pod = dep["spec"]["template"]["spec"]
        assert pod["securityContext"]["runAsNonRoot"] is True
        assert pod["automountServiceAccountToken"] is False
        for c in pod["containers"]:
            sc = c["securityContext"]
            assert sc["allowPrivilegeEscalation"] is False
            assert sc["readOnlyRootFilesystem"] is True
            assert sc["capabilities"]["drop"] == ["ALL"]


def test_grace_period_covers_prestop_and_uvicorn_drain():
    api = next(d for d in _by_kind("Deployment") if d["metadata"]["name"] == "api")
    pod = api["spec"]["template"]["spec"]
    prestop = int(pod["containers"][0]["lifecycle"]["preStop"]["exec"]["command"][-1])
    dockerfile = (ROOT / "api" / "Dockerfile").read_text()
    drain = int(dockerfile.split('"--timeout-graceful-shutdown", "')[1].split('"')[0])
    assert pod["terminationGracePeriodSeconds"] >= prestop + drain


def test_configmap_only_sets_settings_the_app_reads():
    import re

    source = "\n".join(p.read_text() for p in (ROOT / "api" / "app").rglob("*.py"))
    read = set(re.findall(r'"((?:ERID|EVENT_BUS|CORS|DATABASE)_[A-Z_]+|FORWARDED_ALLOW_IPS)"', source))
    read.add("FORWARDED_ALLOW_IPS")  # read by uvicorn itself
    config = next(o for o in _base_objects() if o["kind"] == "ConfigMap")
    unknown = set(config["data"]) - read
    assert not unknown, f"ConfigMap sets settings nothing reads: {unknown}"


def test_connection_budget_fits_default_postgres():
    config = next(o for o in _base_objects() if o["kind"] == "ConfigMap")["data"]
    hpa = next(h for h in _by_kind("HorizontalPodAutoscaler") if h["metadata"]["name"] == "api")
    per_pod = int(config["ERID_DB_POOL_SIZE"]) + int(config["ERID_DB_MAX_OVERFLOW"]) + 1  # + LISTEN
    assert hpa["spec"]["maxReplicas"] * per_pod < 100


def test_ingress_backends_exist_and_skip_internal_endpoints():
    services = {s["metadata"]["name"]: {p["name"] for p in s["spec"]["ports"]} for s in _by_kind("Service")}
    ingress = _by_kind("Ingress")[0]
    paths = []
    for rule in ingress["spec"]["rules"]:
        for p in rule["http"]["paths"]:
            backend = p["backend"]["service"]
            assert backend["port"]["name"] in services[backend["name"]]
            paths.append(p["path"])
    for internal in ("/metrics", "/ready", "/docs"):
        assert internal not in paths


def test_compose_prod_overlay_does_not_publish_api_or_web():
    prod = (ROOT / "docker-compose.prod.yml").read_text()
    doc = yaml.safe_load(prod.replace("!reset", ""))
    assert doc["services"]["api"]["ports"] in (None, [])
    assert doc["services"]["web"]["ports"] in (None, [])
