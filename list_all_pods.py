import sys
import urllib3
from kubernetes import client, config

urllib3.disable_warnings()

if len(sys.argv) > 1:
    config.load_kube_config(sys.argv[1])
else:
    # Utilise le fichier ~/.kube/config par défaut
    config.load_kube_config()

v1 = client.CoreV1Api()
print("Listing pods with their IPs:")
ret = v1.list_pod_for_all_namespaces()
for i in ret.items:
    print(f"{i.status.pod_ip}\t{i.metadata.namespace}\t{i.metadata.name}")

